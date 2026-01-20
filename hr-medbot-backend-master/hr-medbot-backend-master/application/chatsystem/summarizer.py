from __future__ import annotations

from typing import List
import re

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

# Placeholders:
#   {max_tokens} – integer token limit
#   {history}    – chat history lines (role: content) joined by \n
#   {query}      – user question

REWRITE_PROMPT_PREFIX = (
    """<|im_start|>system
###INSTRUCTIONS###
You are given chat history and a new user question. Rewrite the question so it stands alone without prior context, preserving its meaning. Respond with exactly one line starting with 'REWRITE:' followed by the rewritten question. Do not exceed {max_tokens} tokens.

###EXAMPLES###
User question: Où puis-je le trouver ?
REWRITE: Où puis-je trouver la politique de voyage de l’entreprise ?

###HISTORY###
{history}

###QUESTION###
{query}
<|im_end|>
<|im_start|>assistant
"""
)

SUMMARY_PROMPT_PREFIX = (
    """<|im_start|>system
###INSTRUCTIONS###
Provide a concise summary of the conversation so far. Respond with exactly one line starting with 'SUMMARY:' followed by the summary. Keep it under {max_tokens} tokens.

###EXAMPLES###
SUMMARY: The user is asking about annual leave policy details.

###CONVERSATION###
{history}
<|im_end|>
<|im_start|>assistant
"""
)

TITLE_PROMPT_PREFIX = (
"""<|im_start|>system
###INSTRUCTIONS###
You are a conversation title generator.  
You will receive a chat history.
Produce one concise title (5 words max) that captures the essence of the conversation.
The title must be written in the same language as the history.
Respond with exactly one line starting with 'TITLE:' followed by the title (no quotes). Keep it concise and within {max_tokens} tokens.

### Expected Output Format ###
Title: <Your short title>
###EXAMPLES###
TITLE: Annual Leave Policy Query

###Chat history###
User: {user_msg}
Assistant: {assistant_msg}
<|im_end|>
<|im_start|>assistant
"""
)

from llm_client.generator import Generator

class ConversationUtils:
    """Utility wrapper around Generator for conversation-level tasks."""

    def __init__(self, generator: Generator | None = None, max_tokens: int = 50):
        """Create a ConversationUtils instance.

        Parameters
        ----------
        generator
            Optional custom `Generator` instance. If not provided, a default one
            is created.
        max_tokens
            Soft upper-bound for the length of model responses (used only in
            prompt instructions, *not* enforced at API level). Defaults to 50
            as requested.
        """
        self.generator = generator or Generator(max_tokens=max_tokens)
        self.max_tokens = max_tokens

    # --------- Internal helpers ---------
    @staticmethod
    def _extract_prefixed(text: str, prefix: str) -> str:
        """Return content that follows the given prefix (case-insensitive).

        Parameters
        ----------
        text
            Raw model output.
        prefix
            The expected leading keyword, e.g. "REWRITE", "SUMMARY", "TITLE".
        """
        pattern = rf"^\s*{re.escape(prefix)}:\s*(.+)$"
        match = re.search(pattern, text, re.I | re.M)
        if not match:
            raise ValueError(f"Model response did not start with '{prefix}:'")
        return match.group(1).strip()

    # --------- Query rewrite ---------
    def rewrite(self, query: str, history_openai: List[dict]) -> str:
        """Return a self-contained version of *query*.

        If *history_openai* is empty, we assume the question is already
        self-contained and immediately return it. Otherwise, we ask the model to
        rewrite *query* so that it stands alone without the prior context. The
        model must wrap its answer in `<RESULT>` tags and stay within
        `self.max_tokens` tokens. The wrapper is stripped out before returning.
        """

        # Fast path when there is no history to rely on.
        if not history_openai:
            return query

        prompt = REWRITE_PROMPT_PREFIX.format(
            max_tokens=self.max_tokens,
            history="\n".join([f"{m['role']}: {m['content']}" for m in history_openai]),
            query=query,
        )

        # We intentionally leave the closing tag to the model.
        raw_response = self.generator.invoke(prompt, stream=False)
        try:
            rewritten = self._extract_prefixed(raw_response, "REWRITE")
        except ValueError as e:
            # Fall back to raw trimmed text if tagging failed.
            print(f"[ConversationUtils] WARNING: {e}. Returning raw model output.")
            rewritten = raw_response.strip()

        print(f">> REWRITTEN QUERY: {rewritten}")
        return rewritten

    # --------- Summarise ---------
    def summarise(self, history_openai: List[dict]) -> str:
        """Return a concise summary of *history_openai*.

        The model is instructed to respond solely inside `<RESULT>` tags and to
        keep the answer under `self.max_tokens` tokens. The content is then
        extracted and returned.
        """
        prompt = SUMMARY_PROMPT_PREFIX.format(
            max_tokens=self.max_tokens,
            history="\n".join([f"{m['role']}: {m['content']}" for m in history_openai]),
        )

        raw_response = self.generator.invoke(prompt, stream=False)
        try:
            return self._extract_prefixed(raw_response, "SUMMARY")
        except ValueError as e:
            print(f"[ConversationUtils] WARNING: {e}. Returning raw model output.")
            return raw_response.strip()

    # --------- Title ---------
    def generate_title(self, first_user_msg: str, assistant_response: str) -> str:
        """Generate a descriptive title for the conversation so far."""
        prompt = TITLE_PROMPT_PREFIX.format(
            max_tokens=self.max_tokens,
            user_msg=first_user_msg,
            assistant_msg=assistant_response,
        )

        raw_response = self.generator.invoke(prompt, stream=False)
        try:
            return self._extract_prefixed(raw_response, "TITLE")
        except ValueError as e:
            print(f"[ConversationUtils] WARNING: {e}. Returning raw model output.")
            return raw_response.strip()
