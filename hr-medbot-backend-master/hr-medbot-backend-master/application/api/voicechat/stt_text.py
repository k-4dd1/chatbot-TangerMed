from __future__ import annotations

from typing import Annotated, AsyncGenerator

from fastapi import Depends, UploadFile, File, HTTPException, Query
from starlette.responses import StreamingResponse
from pydantic import BaseModel

from api.authentication import get_authenticated_user, User  # type: ignore
from . import engine
from chatsystem import ChatSystem
from database import models, session_scope
from . import router
import uuid

class STTTextResponse(BaseModel):
    transcription: str
    response: str
    user_msg_id: str | None = None
    assistant_msg_id: str | None = None


@router.post(
    "/conversation/{conversation_id}/stt-text")
async def stt_text_endpoint(
    *,
    conversation_id: uuid.UUID,
    stream: bool = Query(False),
    precreate_uuids: bool = Query(False),
    audio_file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Accept an audio recording, transcribe it, send transcription back, pass it to the LLM and return its response.

    Query params:
    - **stream**: stream the LLM response.
    - **precreate_uuids**: behave like `/chat` endpoint and return/generated message IDs.
    """

    try:
        # Read audio bytes
        audio_bytes = await audio_file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file")


        with session_scope() as db:
            conversation = (
                db.query(models.Conversation)
                .filter(models.Conversation.id == conversation_id, models.Conversation.owner_id == current_user.id)
                .first()
            )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        chat_system = ChatSystem(
           user = current_user,
           conversation = conversation
        )

        # Transcribe
        transcription = await engine.transcribe_audio(audio_bytes)

        # Run chat
        response_gen, ids = chat_system.receive(
            user_text=transcription,
            stream=stream,
            include_ids=True
        )

        if stream:
            async def response_stream() -> AsyncGenerator[str, None]:
                # First yield the transcription so the client can display it immediately
                yield transcription + "\n\n"
                # Then yield message id (bot) if available, same convention as /chat
                if precreate_uuids:
                    yield f"{ids['assistant_id']}\n\n"
                # Finally yield the assistant chunks
                for chunk in response_gen:
                    yield chunk + "\n" if chunk else ""

            return StreamingResponse(response_stream(), media_type="text/plain; charset=utf-8")

        # Not streaming --------------------------------------------------------
        return STTTextResponse(
            transcription=transcription,
            response=response_gen,
            user_msg_id=ids['user_id'],
            assistant_msg_id=ids['assistant_id'],
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        # Wrap any other error
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        chat_system.close()