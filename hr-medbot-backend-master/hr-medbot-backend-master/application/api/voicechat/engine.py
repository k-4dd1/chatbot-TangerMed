"""STT/TTS proxy for the core chat system.

This file **does not** load any AI models itself.  Instead, it talks to an
external *Phonebooth* service (see ``phonebooth/__init__.py``) over HTTP.  This
lets multiple application servers share a single GPU-heavy speech service that
can be deployed separately.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncGenerator, Dict

import httpx  # type: ignore[import]

# ---------------------------------------------------------------------------
# Configuration – where is the phonebooth service?
# ---------------------------------------------------------------------------

PHONEBOOTH_URL = os.getenv("PHONEBOOTH_URL", "http://host.docker.internal:13338")
PHONEBOOTH_KEY = os.getenv("PHONEBOOTH_KEY", "")

# Prepare headers with API key if provided
_phonebooth_headers: Dict[str, str] = {}
if PHONEBOOTH_KEY:
    _phonebooth_headers["Authorization"] = f"Bearer {PHONEBOOTH_KEY}"

# Export headers for use in other modules
PHONEBOOTH_HEADERS = _phonebooth_headers

# Fetch speaker list synchronously at import time so the rest of the server
# can use it immediately (e.g. for parameter validation in query strings).
try:
    _resp = httpx.get(f"{PHONEBOOTH_URL}/speakers", timeout=5, headers=_phonebooth_headers)
    _resp.raise_for_status()
    XTTS_SPEAKERS: Dict[str, str] = _resp.json()
    XTTS_DEFAULT_SPEAKER_IDX: int = 53
except Exception as exc:  # noqa: BLE001
    XTTS_SPEAKERS = {}
    XTTS_DEFAULT_SPEAKER_IDX = 53

# ---------------------------------------------------------------------------
# Persistent HTTP client (re-used for streaming) to avoid connection overhead
# ---------------------------------------------------------------------------

_shared_async_client = httpx.AsyncClient(base_url=PHONEBOOTH_URL, timeout=None, headers=_phonebooth_headers)

# No heavy models loaded here – only lightweight HTTP operations.


async def transcribe_audio(raw_audio: bytes) -> str:
    """Convert *raw_audio* (WAV bytes) to text via Phonebooth."""
    async with httpx.AsyncClient(base_url=PHONEBOOTH_URL, timeout=40.0, headers=_phonebooth_headers) as client:
        files = {"file": ("audio.wav", raw_audio, "audio/wav")}
        resp = await client.post("/transcribe", files=files)
        resp.raise_for_status()
        return resp.json()["text"]


async def xtts_stream(
    text: str,
    speaker: str,
    chunk_tokens: int = 150,  # kept for API compatibility; unused locally
) -> AsyncGenerator[bytes, None]:
    """Stream 1-second WAV chunks for *text* from Phonebooth.

    This simply forwards the request to Phonebooth's ``/tts_stream`` endpoint
    and yields the raw byte chunks it sends back.  No heavy audio processing is
    done here.
    """

    # We receive a raw byte stream from Phonebooth – individual TCP frames may
    # split our WAV chunks arbitrarily.  Buffer incoming bytes and only yield a
    # **complete** WAV (header+data) at a time so downstream consumers always
    # receive a valid, self-contained WAV file.  This prevents decode errors in
    # the browser which caused playback to stop mid-sentence.

    WAV_HEADER_SIZE = 44  # standard PCM header length

    async with _shared_async_client.stream("POST", "/tts_stream", json={"text": text, "speaker": speaker}) as resp:
        resp.raise_for_status()

        buf = bytearray()
        expected_size: int | None = None  # total bytes for the current WAV

        async for chunk in resp.aiter_bytes():
            if not chunk:  # skip keep-alive/empty chunks
                continue

            buf.extend(chunk)

            while True:
                # Determine expected total size once we have the full header
                if expected_size is None and len(buf) >= WAV_HEADER_SIZE:
                    data_size = int.from_bytes(buf[40:44], "little")
                    expected_size = WAV_HEADER_SIZE + data_size

                # If we have a full WAV payload, yield it
                if expected_size is not None and len(buf) >= expected_size:
                    wav_bytes = bytes(buf[:expected_size])
                    del buf[:expected_size]
                    expected_size = None  # reset for next chunk
                    yield wav_bytes
                else:
                    break

        # Flush any remaining (valid) WAV data after stream ends
        if buf and expected_size is not None and len(buf) >= expected_size:
            yield bytes(buf)


async def llm_to_tts(
    llm_stream: AsyncGenerator[str, None],
    speaker: str,
    out_q: asyncio.Queue[bytes],
    min_words: int = 10,
    max_words: int = 80,
) -> None:
    """Convert streamed LLM tokens to queued WAV chunks via Phonebooth."""
    buf = ""
    async for tok in llm_stream:
        buf += tok
        word_count = len(buf.split())
        if (
            (tok.endswith((".", "?", "!", "\n")) and word_count >= min_words)
            or word_count >= max_words
        ):
            if buf.strip():
                async for wav in xtts_stream(buf, speaker):
                    await out_q.put(wav)
            buf = ""

    # final tail
    if buf.strip():
        async for wav in xtts_stream(buf, speaker):
            await out_q.put(wav)
    await out_q.put(b"")  # poison-pill

