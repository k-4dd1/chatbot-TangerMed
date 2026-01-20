from __future__ import annotations

from cgitb import text
import re
from typing import List, Iterable
from langchain_text_splitters.markdown import RecursiveCharacterTextSplitter



class GoldenChunker:
    """Advanced Markdown chunker tailored for *Sowelni* ingestion.

    Pipeline overview (configurable via constructor):

    1. **Section split** – Input is first divided on separator lines that contain
       only dashes (``---``).  Each section is processed independently.

    2. **Recursive header split** – Within an oversize section we split on ATX
       headings starting at level-1 through level-6.  After each pass, *only*
       the parts whose length exceeds *``chunk_size``* are forwarded to the next
       (finer) heading level.  This preserves as much context as possible.

    3. **Small-chunk merge** – Header-split fragments whose length is below
       *``min_size``* are glued to an adjacent chunk.  Direction is controlled by
       *``merge_reversed``*:
       • ``True``  – merge bottom-up (default).
       • ``False`` – merge top-down.

    4. **Fallback splitter (LangChain)** – If, after step 3, any fragment still
       exceeds *``max_size``* we invoke a ``RecursiveCharacterTextSplitter`` with
       ``chunk_size`` (=preferred working size) and ``chunk_overlap=0``.  Leading
       heading lines in the fragment are *prepended to every produced piece* so
       that header context is shared.

    Key parameters
    ---------------
    max_size
        Absolute upper bound.  A chunk larger than this can *never* leave the
        chunker; the fallback splitter is guaranteed to break it.
    chunk_size
        Preferred target size used for all *regular* splitting operations.
    min_size
        Lower bound for header-split fragments; smaller pieces are merged.
    merge_reversed
        Choose merge direction (see step 3).

    Heading lines are **preserved** at the beginning of the chunk they belong
    to, and all size checks use ``len(chunk)`` (raw character count).
    """

    SECTION_PATTERN = re.compile(r"^\s*---+\s*$", flags=re.MULTILINE)

    def __init__(
        self,
        *,
        max_size: int,
        chunk_size: int,
        min_size: int = 0,
        merge_reversed: bool = False,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be a positive integer")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer")
        if min_size < 0:
            raise ValueError("min_size must be >= 0")
        if min_size > max_size:
            raise ValueError("min_size cannot exceed max_size")
        if chunk_size > max_size:
            raise ValueError("chunk_size cannot exceed max_size")
        self.max_size = max_size
        self.chunk_size = chunk_size
        self.min_size = min_size
        self.merge_reversed = merge_reversed

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def __call__(self, text: str) -> List[str]:
        return self.chunk(text)

    def chunk(self, text: str) -> List[str]:
        """Return a list of chunks whose lengths are **<=** ``self.max_size``.

        Parameters
        ----------
        text: str
            Markdown document to be chunked.
        """
        chunks: List[str] = []
        for section in self._split_by_section(text):
            if len(section) <= self.chunk_size:
                chunks.append(section)
            else:
                chunks.extend(self._split_recursively(section))
        return chunks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _split_by_section(self, text: str) -> Iterable[str]:
        """Yield raw sections separated by SECTION_PATTERN delimiter lines."""
        for part in re.split(self.SECTION_PATTERN, text):
            if part:  # ignore empty strings that result from split
                yield part

    def _split_recursively(self, text: str) -> List[str]:
        """Recursively split *text* on headings until chunks fit ``max_size``."""
        oversized: List[str] = [text]
        chunks: List[str] = []

        for level in range(1, 7):
            next_round: List[str] = []
            for piece in oversized:
                if len(piece) <= self.chunk_size:
                    chunks.append(piece)
                    continue

                sub_parts = self._split_by_heading_level(piece, level)
                # If we failed to find headings of this level, keep the piece as-is
                if len(sub_parts) == 1:
                    next_round.append(piece)
                    continue

                for sub in sub_parts:
                    target = chunks if len(sub) <= self.chunk_size else next_round
                    target.append(sub)

            oversized = next_round
            if not oversized:  # Everything fits – we can stop early.
                break

        # Glue small chunks that originated from header splitting *before* fallback.
        chunks = self._merge_small_chunks(chunks)

        # Fallback – split only if remainder exceeds *max_size*.
        for remainder in oversized:
            if len(remainder) > self.max_size:
                chunks.extend(self._fallback_split_with_headers(remainder))
            else:
                chunks.append(remainder)
        return chunks

    def _split_by_heading_level(self, text: str, level: int) -> List[str]:
        """Split *text* on ATX headings of the given *level* **keeping** headings.

        If no headings of *level* are found the original text is returned as a
        single-element list so that callers can easily detect the situation.
        """
        # RegEx for an *exact* level heading, e.g. level-2 => "## "
        pattern = re.compile(rf"^({'#' * level})\s+.*$", flags=re.MULTILINE)
        matches = list(pattern.finditer(text))
        if not matches:
            return [text]

        # Build slices that start at each heading and end right *before* the
        # next heading (or EOF).
        chunks: List[str] = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            chunks.append(text[start:end])

        # Pre-heading content (if any) should precede the first chunk.
        preamble = text[: matches[0].start()].strip("\n")
        if preamble:
            chunks.insert(0, preamble)
        return chunks

    # ------------------------------------------------------------------
    # Post-processing helpers
    # ------------------------------------------------------------------
    def _merge_small_chunks(self, chunks: List[str]) -> List[str]:
        """Merge adjacent *header-split* chunks whose length < ``min_size``.

        The merge is performed from the *bottom up* (i.e. end → start) so that
        glueing tends to keep hierarchy context – a small sub-section is first
        appended to the section that precedes it.

        A merge is executed only if the resulting chunk will still be ≤
        ``max_size``.  Otherwise the small chunk is left as-is.
        """
        if self.min_size == 0 or not chunks:
            return chunks

        merged: List[str] = chunks.copy()

        if self.merge_reversed:  # Bottom-up
            i = len(merged) - 1
            while i > 0:
                if len(merged[i]) < self.min_size:
                    candidate = merged[i - 1] + merged[i]
                    if len(candidate) <= self.max_size:
                        merged[i - 1] = candidate
                        del merged[i]
                        i = min(i, len(merged) - 1)
                        continue
                i -= 1
        else:  # Top-down
            i = 0
            while i < len(merged) - 1:
                if len(merged[i]) < self.min_size:
                    candidate = merged[i] + merged[i + 1]
                    if len(candidate) <= self.max_size:
                        merged[i] = candidate
                        del merged[i + 1]
                        # Do not increment i – re-evaluate merged chunk
                        continue
                i += 1
        return merged

    # ------------------------------------------------------------------
    # Fallback splitter using langchain
    # ------------------------------------------------------------------
    def _fallback_split_with_headers(self, text: str) -> List[str]:
        """Split *text* with a RecursiveCharacterTextSplitter (0 overlap).

        Any leading ATX header lines present at the *beginning* of *text* are
        considered *context* and will be **prepended** to every produced chunk
        so that header information is shared.
        """

        header_match = re.match(r"^(?:#+\s+.*(?:\n|$))+", text)
        header_prefix = header_match.group(0) if header_match else ""

        effective_size = (
            self.chunk_size - len(header_prefix) if header_prefix else self.chunk_size
        )
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=effective_size,
            chunk_overlap=0,
            add_start_index=False,
        )
        body = text[len(header_prefix) :] if header_prefix else text
        body_chunks = splitter.split_text(body)

        if not header_prefix:
            return body_chunks

        return [header_prefix + chunk for chunk in body_chunks]
