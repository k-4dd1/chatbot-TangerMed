import asyncio
import uuid
from typing import AsyncGenerator, Annotated

from fastapi import WebSocket, Depends, Query
from fastapi.websockets import WebSocketDisconnect
from asyncio import QueueEmpty

from api.authentication import get_authenticated_user_websocket
from chatsystem import ChatSystem
from . import engine
from database import models
from . import router
from database import session_scope



async def get_conversation(
    conversation_id: uuid.UUID | None,
    user: models.User,
    create_if_missing: bool = True,
) -> ChatSystem | None:
    """Resolve a valid conversation id (create if necessary)."""
    try:
        with session_scope(write_enabled=True) as db:
            if conversation_id:
                c = db.query(models.Conversation).filter(
                    id=conversation_id,
                    owner_id=user.id
                ).one_or_none()
            if not conversation_id:
                c = models.Conversation(owner_id=user.id)
                db.add(c)
                db.flush()
                db.refresh(c)
        conversation = ChatSystem(user=user, conversation=c,is_voicechat_pipeline=True)
        return conversation
    except Exception:
        return None


async def get_speaker_voice(websocket: WebSocket) -> str:
    """Resolve requested speaker voice (index or direct name)"""
    speakers_dict = engine.XTTS_SPEAKERS
    speaker_param = str(websocket.query_params.get("speaker"))
    if not speaker_param or speaker_param not in speakers_dict.keys():
        speaker_param = str(engine.XTTS_DEFAULT_SPEAKER_IDX)
    return speakers_dict[speaker_param]


# Async pipeline: ASR → LLM → TTS -------------------------------------------------
# Keeping this logic separated from the websocket handler makes the control flow
# clearer and allows unit-testing the heavy lifting independently from network
# concerns.


async def run_generation(
    audio_bytes: bytes,
    conversation: "ChatSystem",
    speaker_voice: str,
    out_q: "asyncio.Queue[bytes]",
) -> None:
    """Full ASR → LLM → TTS pipeline that ultimately pushes WAV chunks to *out_q*.

    1. Transcribes *audio_bytes* to text using *engines.transcribe_audio*.
    2. Streams the LLM response content back using *conversation.chat(stream=True)*.
    3. Converts each response chunk to speech via *engines.llm_to_tts* and pushes
       the resulting WAV bytes to *out_q*.
    """

    try:
        transcription = await engine.transcribe_audio(audio_bytes)

        response_generator, _ = conversation.receive(user_text=transcription, stream=True, include_ids=True)

        async def stream_response_content() -> AsyncGenerator[str, None]:
            for chunk in response_generator:
                yield chunk

        await engine.llm_to_tts(stream_response_content(), speaker_voice, out_q)
    except asyncio.CancelledError:
        await out_q.put(b"")
        raise


# -----------------------------------------------------------------------------
# WebSocket helpers ------------------------------------------------------------
# -----------------------------------------------------------------------------


async def producer(
    websocket: "WebSocket",
    conversation: "ChatSystem",
    speaker_voice: str,
    out_q: "asyncio.Queue[bytes]",
) -> None:
    """Handle incoming audio bytes from *websocket* and kick-off generation tasks."""

    generation_task: asyncio.Task | None = None

    try:
        while True:
            data = await websocket.receive_bytes()

            # Handle explicit stop command ------------------------------------
            if data == b"STOP":
                if generation_task and not generation_task.done():
                    generation_task.cancel()
                    try:
                        await generation_task
                    except asyncio.CancelledError:
                        pass

                # Flush any remaining items in the output queue
                try:
                    while not out_q.empty():
                        out_q.get_nowait()
                except QueueEmpty:
                    pass

                await out_q.put(b"")  # poison pill
                generation_task = None
                continue

            # If a generation task is still running, cancel it before starting
            # a new one so we always respond to the most recent user utterance.
            if generation_task and not generation_task.done():

                generation_task.cancel()
                try:
                    await generation_task
                except asyncio.CancelledError:
                    pass

            # Kick-off a fresh generation task --------------------------------
            generation_task = asyncio.create_task(
                run_generation(data, conversation, speaker_voice, out_q)
            )

    except WebSocketDisconnect:
        if generation_task and not generation_task.done():
            generation_task.cancel()
        await out_q.put(b"")


async def consumer(websocket: "WebSocket", out_q: "asyncio.Queue[bytes]") -> None:
    """Continuously send WAV chunks from *out_q* over *websocket*."""

    try:
        while True:
            wav = await out_q.get()
            if wav == b"":
                continue  # poison pill or queue flush signal
            await websocket.send_bytes(wav)
    except WebSocketDisconnect:
        pass

###############################################################################


@router.websocket("/conversations/chat")
async def websocket_endpoint(
    websocket: WebSocket,
    user: Annotated[models.User, Depends(get_authenticated_user_websocket)],
    conversation_id: uuid.UUID | None = Query(None),
):
    """Main WebSocket endpoint handling real-time voice conversations."""


    conversation = await get_conversation(conversation_id, user)
    if not conversation:
        await websocket.close(code=1008, reason="Valid conversation ID is required")
        return

    await websocket.accept()
    speaker_voice = await get_speaker_voice(websocket)
    out_q: asyncio.Queue[bytes] = asyncio.Queue()

    try:
        await asyncio.gather(
            producer(websocket, conversation, speaker_voice, out_q),
            consumer(websocket, out_q),
        )
    finally:
        # Ensure we properly close the conversation and persist any data even if the
        # websocket disconnects or an error is raised.
        try:
            conversation.close()
        except Exception:
            # We intentionally swallow exceptions during close to avoid masking the
            # original error cause while still attempting cleanup.
            pass
