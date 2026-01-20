from __future__ import annotations

# Standard library
import logging
import time
from typing import Callable, Generator, List, Dict, Any, Optional
from uuid import uuid4

from llm_client.generator import Generator


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

BASE_SYSTEM_PREAMBLE = (
"""
you are a friendly and enthusiastic HR AI Assistant for TANGER MED. 💖

## Core Directive
Your primary purpose is to answer employee questions **exclusively** based on the provided context block, which contains TANGER MED's official HR policies. You must **never** invent information or use knowledge outside of this context.

## Rules of Engagement
1.  **Synthesize, Don't Recite:** This is your most important rule. You must **synthesize and rephrase** the information from the context in your own friendly, conversational words. **Never copy text verbatim.** Your goal is to make policies easy to understand. For example, convert bullet points from the text into a natural sentence.
2.  **Confirm the Question:** Always start your response by briefly and cheerfully restating the user's question to ensure you've understood it.
3.  **Stay Focused:** If a user asks about anything other than TANGER MED HR policies, gently and politely steer them back to your designated topic. 💫
4.  **Be Concise:** Keep your answers clear and to the point.
5.  **Cite Your Source:** Always end your answer by citing the source file on a new line: `Reference: [file_name]`.
6.  **Match the Language:** Respond in the same language the user writes in (only Arabic, French, English).

## Fallback Protocol
If the provided context does **not** contain the answer, you must state that you don't have the information. **Do not guess.** Politely apologize and suggest how they might find the answer, like this: "I couldn't find the specifics on that in my documents! You might want to reach out directly to the HR department for more details. 🤗"
"""
)

# Instructions specialised for voice chat / TTS pipelines.
# Keep sentences short, avoid code blocks and markdown formatting.
# You may tweak SSML guidance here if your TTS engine supports it.
VOICE_SYSTEM_PREAMBLE = (
    """
You are MED Voice, the HR voice assistant for TANGER MED employees in Morocco.
You are speaking aloud via a text to speech system, keep sentences short and clear, do not use markdown.
The user message is transcribed from audio and may contain errors, be careful and confirm intent with a short restatement.

You must answer questions about TANGER MED HR policies and procedures only.
If the user asks about something outside this scope, politely say you are an HR representative and can only help with HR policies and procedures.
Refuse political geopolitical religious or sensitive topics outside the company HR context.

A context block is provided containing snippets from the company knowledge base related to the latest message.
Always base your answer on the context block, synthesize and rephrase it, do not copy verbatim.
Never invent assume or guess information.
If the context block does not contain the needed information, apologize and say you do not have that information, or ask the user for more details.

Match the language of the user input.
Be polite professional and concise, keep the reply under one hundred tokens unless the user asks for more detail.
Start by briefly restating the user request, then give the answer.

Voice output constraints for every reply.
Plain text only.
One single paragraph.
Use only dots and commas as punctuation.
Do not use emojis symbols visual bullet points brackets or slashes.
If you need to list items, use short phrases like first, second, finally.
Avoid abbreviations and acronyms unless you are sure of the full form.
When referring to websites, mention the website name only.
Write numbers in full words.
Do not write separated number formats.
For currency say Moroccan Dirham, Dirham Maroccain, or الدرهم المغربي.
"""
)

CONTEXT_BLOCK_TEMPLATE = """
These snippets are from the company knowledgebase.
You may base your answer on the knowledgebase if it contains the needed information.
if the information is not included in this block or the block is empty DO NOT make up an answer, kindly apologize that you couldn't find it in your knowledge base, you may ask the user questions that could make their request clearer.
<context>
{context}
</context>
"""

from database import models
from .history_manager import ChatHistory
from .summarizer import ConversationUtils
from retrieval.augmented_retriever import AugmentedRetriever
from datetime import datetime, timezone

class GenerationAborted(Exception):
    """Raised when the generator connection closes before completion"""

    def __init__(self, partial: str):
        super().__init__("Generation aborted early")
        self.partial = partial

class ChatSystem:
    def __init__(self, user: models.User | None = None, conversation: models.Conversation | None = None,
                 *,
                 retriever: Optional[AugmentedRetriever] = None,
                 generator: Optional[Generator] = None, token_threshold: int = 1000, persistence: bool = True,
                 is_voicechat_pipeline: bool = False):
        self.user = user
        self.generator = generator or Generator()

        if retriever:
            self.retriever = retriever
        else:
            self.retriever = AugmentedRetriever()

        self.history = ChatHistory(token_threshold=token_threshold, user=user, conversation=conversation)
        self.persistence = persistence
        self.is_voicechat_pipeline = is_voicechat_pipeline
        self.utils = ConversationUtils(self.generator)
        self._title_generated = False

    # ---------------- Main entry ----------------
    def receive(
        self,
        user_text: str,
        *,
        stream: bool = False,
        on_token: Optional[Callable[[str], None]] = None,
        include_ids: bool = False
    ):
        """Process a user turn and return assistant response (string or generator of tokens)."""
        user_ts = datetime.now(timezone.utc)
        start_ts = time.perf_counter()

        # Precreate message IDs
        user_msg_id = str(uuid4())
        assistant_msg_id = str(uuid4())

        # 1. optional query rewrite
        rewritten_query = (
            self.utils.rewrite(user_text, self.history.to_openai_format())
            if self.history.messages
            else user_text
        )

        rewrite_end_ts = time.perf_counter()

        # timings accumulator
        timings_base: Dict[str, float] = {
            "rewrite_ms": (rewrite_end_ts - start_ts) * 1000,
        }

        # 2. retrieve context
        context_chunks = self.retriever(rewritten_query)
        # Build helper structures preserving detailed scores
        context_items = []
        if context_chunks:
            for c in context_chunks:
                context_items.append({
                    "id": c["chunk"].id,
                    "summary_score": c.get("summary_score"),
                    "small_chunk_score": c.get("small_chunk_score"),
                    "combined_score": c.get("combined_score"),
                    "rerank_score": c.get("rerank_score"),
                })

        context_text = (
            "\n\n".join([c["chunk"].text for c in context_chunks]) if context_chunks else ""
        )
        retrieval_end_ts = time.perf_counter()
        timings_base["retrieval_ms"] = (retrieval_end_ts - rewrite_end_ts) * 1000

        # 3. build prompt
        history_msgs = self.history.to_openai_format()
        system_preamble = VOICE_SYSTEM_PREAMBLE if self.is_voicechat_pipeline else BASE_SYSTEM_PREAMBLE
        if context_text:
            system_preamble += CONTEXT_BLOCK_TEMPLATE.format(context=context_text)

        # Build Qwen-style prompt
        prompt_parts = [
            f"<|im_start|>system\n{system_preamble}\n<|im_end|>"  # system instructions
        ]
        for msg in history_msgs:
            role_tag = msg["role"]
            content = msg["content"]
            prompt_parts.append(f"<|im_start|>{role_tag}\n{content}\n<|im_end|>")

        # current user turn
        prompt_parts.append(f"<|im_start|>user\n{user_text}\n<|im_end|>")
        # assistant start tag (left open for model to continue)
        prompt_parts.append("<|im_start|>assistant\n")

        prompt_str = "\n".join(prompt_parts)

        # prompt build timing
        prompt_end_ts = time.perf_counter()
        timings_base["prompt_build_ms"] = (prompt_end_ts - retrieval_end_ts) * 1000

        # 4. call generator
        if stream:
            gen = self._stream_response(
                prompt_str,
                user_text,
                user_ts,
                on_token,
                timings_base,
                context_items,
                rewritten_query,
                user_msg_id,
                assistant_msg_id,
            )
            return (gen, {"user_id": user_msg_id, "assistant_id": assistant_msg_id}) if include_ids else gen
        else:
            gen_start = time.perf_counter()
            assistant_reply = self.generator.invoke(prompt_str, stream=False)
            gen_end = time.perf_counter()
            timings = {**timings_base, "generation_ms": (gen_end - gen_start) * 1000}
            assistant_ts = datetime.now(timezone.utc)
            self._finalise_turn(
                user_text,
                assistant_reply,
                user_ts=user_ts,
                assistant_ts=assistant_ts,
                context_items=context_items,
                timings=timings,
                rewritten_query=rewritten_query,
                user_msg_id=user_msg_id,
                assistant_msg_id=assistant_msg_id,
            )
            result = assistant_reply
            if include_ids:
                return result, {"user_id": user_msg_id, "assistant_id": assistant_msg_id}
            return result

    # ---------------- Streaming helpers ----------------
    def _stream_response(
        self,
        prompt_str,
        user_text: str,
        user_ts,
        on_token: Optional[Callable[[str], None]],
        base_timings: Dict[str, float],
        context_items,
        rewritten_query,
        user_msg_id,
        assistant_msg_id,
    ):
        token_acc = []
        partial = ""
        first_token_ms = None
        try:
            gen_start = time.perf_counter()
            for token in self.generator.invoke(prompt_str, stream=True):
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - gen_start) * 1000
                token_acc.append(token)
                partial = "".join(token_acc)
                if on_token:
                    on_token(token)
                yield token
        except Exception as e:
            # abort
            assistant_ts = datetime.now(timezone.utc)
            elapsed = time.perf_counter() - gen_start
            timings = {**base_timings, "generation_ms": elapsed * 1000}
            if first_token_ms is not None:
                timings["first_token_ms"] = first_token_ms
            self._finalise_turn(
                user_text,
                partial,
                user_ts=user_ts,
                assistant_ts=assistant_ts,
                aborted=True,
                context_items=context_items,
                timings=timings,
                rewritten_query=rewritten_query,
                user_msg_id=user_msg_id,
                assistant_msg_id=assistant_msg_id,
            )
            raise GenerationAborted(partial) from e
        # normal finish
        gen_end = time.perf_counter()
        timings = {**base_timings, "generation_ms": (gen_end - gen_start) * 1000}
        if first_token_ms is not None:
            timings["first_token_ms"] = first_token_ms
        assistant_reply = "".join(token_acc)
        assistant_ts = datetime.now(timezone.utc)
        self._finalise_turn(
            user_text,
            assistant_reply,
            user_ts=user_ts,
            assistant_ts=assistant_ts,
            context_items=context_items,
            timings=timings,
            rewritten_query=rewritten_query,
            user_msg_id=user_msg_id,
            assistant_msg_id=assistant_msg_id,
        )

    # ---------------- Internals ----------------
    def _finalise_turn(
        self,
        user_text: str,
        assistant_reply: str,
        *,
        user_ts,
        assistant_ts,
        context_items: Optional[List[dict]] = None,
        timings: Optional[Dict[str, float]] = None,
        rewritten_query: Optional[str] = None,
        user_msg_id: Optional[str] = None,
        assistant_msg_id: Optional[str] = None,
        aborted: bool = False,
    ):
        self.history.add(
            "user",
            user_text,
            msg_id=user_msg_id,
            created_at=user_ts,
            context={"rewritten_query": rewritten_query} if rewritten_query else None,
        )

        # Token usage before adding this turn
        tokens_before = self.history.token_count()

        context_info: Dict[str, Any] = {}
        if context_items:
            context_info["chunks"] = context_items
        if timings:
            context_info["timings"] = timings
        if rewritten_query is not None:
            context_info["rewritten_query"] = rewritten_query

        self.history.add(
            "assistant",
            assistant_reply,
            msg_id=assistant_msg_id,
            created_at=assistant_ts,
            context=context_info or None,
        )
        # Token usage after adding this turn
        tokens_after = self.history.token_count()
        token_delta = tokens_after - tokens_before
        # Update the just-added assistant message context with token stats
        if context_info is not None:
            context_info["token_usage"] = {
                "before": tokens_before,
                "after": tokens_after,
                "delta": token_delta,
            }

        # title generation
        if not self._title_generated and assistant_reply and self.history.messages:
            _tg_start = time.perf_counter()
            title = self.utils.generate_title(user_text, assistant_reply)
            _tg_end = time.perf_counter()
            self.history.conversation.title = title
            # Record timing in context_info
            tg_ms = (_tg_end - _tg_start) * 1000
            if context_info is not None:
                if "timings" not in context_info:
                    context_info["timings"] = {}
                context_info["timings"]["title_gen_ms"] = tg_ms
            self._title_generated = True
        # maybe summarise
        if not aborted:
            self.history.maybe_summarise()

    # ---------------- Lifecycle ----------------
    def close(self):
        """End the session. Persist to DB if persistence enabled."""
        if self.persistence:
            self.history.flush_to_db()


# ---------------------------------------------------------------------------
# Simple CLI for manual testing
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Interactive chat with ChatSystem")
    parser.add_argument("--stream", action="store_true", help="Enable streaming output")
    parser.add_argument("--no-persist", action="store_true", help="Disable DB persistence")
    args = parser.parse_args()

    chat = ChatSystem(persistence=not args.no_persist)

    try:
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in {"quit", "exit", "q"}:
                break
            if not user_input:
                continue

            start = time.time()
            if args.stream:
                print("Assistant: ", end="", flush=True)
                gen, ids = chat.receive(
                    user_input,
                    stream=True,
                    include_ids=True,
                    on_token=lambda t: print(t, end="", flush=True),
                )
                for _ in gen:
                    pass  # tokens printed via callback
                print()  # newline after completion
            else:
                reply, ids = chat.receive(user_input, stream=False, include_ids=True)
                print(f"Assistant: {reply}")

            print(f"[message ids] user={ids['user_id']} assistant={ids['assistant_id']}")
            elapsed = (time.time() - start) * 1000
            print(f"(took {elapsed:.1f} ms)\n")
    finally:
        chat.close()
