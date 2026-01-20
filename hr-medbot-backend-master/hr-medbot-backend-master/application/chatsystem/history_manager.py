from __future__ import annotations

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from collections import deque

from llm_client.generator import Generator
from database import session_scope, models
from uuid import uuid4

# ---------------------------------------------------------------------------
# Prompt template for conversation summarisation
# ---------------------------------------------------------------------------

CONVERSATION_SUMMARIZER_PROMPT = """
<|im_start|>system
### Instruction ###
You are an agent that summarizes conversations.
You are given a conversation history, summarize it in a few sentences.

### Examples ###
# Example 1:
# Conversation History:
User: Comment ajouter mes enfants à ma couverture médicale ?
Assistant: Pour ajouter vos enfants, veuillez fournir leurs actes de naissance
User: J'ai un fils de 5 ans et une fille de 7 ans
# Summary:
L'utilisateur demande comment ajouter ses deux enfants (5 et 7 ans) à sa couverture médicale et l'assistant a répondu sur les documents nécessaires.
---
# Example 2:
# Conversation History:
User: Je besoin d'aide pour calculer ma pension de retraite
Assistant: Quel est votre dernier salaire mensuel ?
User: Mon salaire est de 15000 DH
Assistant: Depuis combien d'années avez-vous cotisé ?
User: 25 ans
# Summary:
L'utilisateur cherche à calculer sa pension de retraite avec un salaire de 15000 DH et 25 ans de cotisation.
/no_think
<|im_end|>
<|im_start|>user
### Conversation History ###
{conversation_history}
<|im_end|>
<|im_start|>assistant
### Summary ###
"""


class ChatHistory:
    """In-memory chat history for a single conversation. Persist with `flush_to_db`."""

    def __init__(self, conversation: models.Conversation | None = None, *, user: models.User | None = None, token_threshold: int = 3000):
        if conversation is None:
            conversation = models.Conversation(owner=user) if user else models.Conversation()
        self.conversation = conversation
        self.generator = Generator()
        self.token_threshold = token_threshold

        # messages deque; each item: {role, content, created_at, context, persisted}
        self.messages: deque[Dict[str, Any]] = deque()

        # If conversation already exists in DB, preload history respecting token budget
        if self.conversation.id is not None:
            self._load_existing()

    # ---------------- Public API ----------------
    def add(
        self,
        role: str,
        content: str,
        *,
        msg_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        context: Optional[dict] = None,
    ):
       
        if msg_id is None:
            msg_id = str(uuid4())
        self.messages.append({
            "id": msg_id,
            "role": role,
            "content": content,
            "context": context or {},
            "created_at": created_at or datetime.now(timezone.utc),
            "persisted": False,
        })

    def to_openai_format(self) -> List[Dict[str, str]]:
        return [{"role": m["role"], "content": m["content"]} for m in self.messages]

    def token_count(self) -> int:
        try:
            return self.generator.count_conversation_tokens(self.to_openai_format())[0]
        except Exception:
            # fallback rough count
            return sum(len(m["content"].split()) for m in self.messages)

    def maybe_summarise(self):
        if self.token_count() < self.token_threshold:
            return
        prompt = CONVERSATION_SUMMARIZER_PROMPT.format(
            conversation_history=self._history_as_plain()
        )
        summary_text = self.generator.invoke(prompt, stream=False)

        # Persist current messages before altering history to avoid data loss
        self.flush_to_db()

        # Reduce history by dropping oldest persisted messages until under threshold
        while self.token_count() > self.token_threshold and len(self.messages) > 1:
            dropped = self.messages.popleft()

        # After trimming, record summary and cutoff
        self.conversation.token_budgeting_summary = summary_text
        # If the first remaining message already persisted, record its id; else None (will update on flush)
        first_msg = self.messages[0]
        self.conversation.token_budgeting_message_id = first_msg.get("db_id")

        # Persist the updated conversation fields
        self.flush_to_db()

    # ---------------- Persistence ----------------
    def flush_to_db(self):
        """Persist conversation & messages, idempotent for a single flush."""
        with session_scope() as session:
            # if self.conversation.id is None:
            # always trigger conversation update
            session.add(self.conversation)
            session.flush()  # to get id
            for m in self.messages:
                if m.get("persisted", False):
                    continue  # already in DB
                msg_model = models.Message(
                    id=m.get("id"),
                    conversation_id=self.conversation.id,
                    role=m["role"],
                    content=m["content"],
                    context=m.get("context"),
                    created_at=m["created_at"],
                )
                session.add(msg_model)
                session.flush()  # get id
                m["persisted"] = True
                m["db_id"] = msg_model.id

                # If conversation token_budgeting_message_id is None and this is first message, set it
                if self.conversation.token_budgeting_message_id is None and m is self.messages[0]:
                    self.conversation.token_budgeting_message_id = msg_model.id
            session.commit()

    # ---------------- Internal helpers ----------------
    def _history_as_plain(self) -> str:
        return "\n".join([f"{m['role']}: {m['content']}" for m in self.messages])

    # ---------------- Loading ----------------
    def _load_existing(self):
        """Load existing messages for the conversation up to the token budget (latest first)."""
        with session_scope() as session:
            query = (
                session.query(models.Message)
                .filter(models.Message.conversation_id == self.conversation.id)
                .order_by(models.Message.created_at.desc())
                .yield_per(50)
            )

        reverse_acc: List[Dict[str, Any]] = []
        token_count = 0
        for msg in query:
            reverse_acc.append({
                "role": msg.role,
                "content": msg.content,
                "context": msg.context,
                "created_at": msg.created_at,
                "persisted": True,
                "db_id": msg.id,
            })
            token_count = self._tokens_in(reverse_acc)
            if token_count > self.token_threshold:
                reverse_acc.pop()
                break
            if self.conversation.token_budgeting_message_id and msg.id == self.conversation.token_budgeting_message_id:
                break

        # --- Inject earlier summary, if any ---
        if self.conversation.token_budgeting_summary:
            summary_msg = {
                "role": "system",
                "content": f"(earlier summary) {self.conversation.token_budgeting_summary}",
                "context": {"token_budget": True},
                "created_at": getattr(self.conversation, "updated_at", None),
                "persisted": True,
            }
            # Tentatively prepend; we'll enforce budget afterwards
            self.messages.append(summary_msg)

        # Add the persisted messages in chronological order
        for m in reversed(reverse_acc):
            self.messages.append(m)

        # Ensure we stay within token threshold (rare, but guard just in case)
        while self.token_count() > self.token_threshold and len(self.messages) > 1:
            self.messages.popleft()

    def _tokens_in(self, msgs: List[Dict[str, Any]]) -> int:
        try:
            return self.generator.count_conversation_tokens([{"role": m["role"], "content": m["content"]} for m in msgs])[0]
        except Exception:
            return sum(len(m["content"].split()) for m in msgs)
