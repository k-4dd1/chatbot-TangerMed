from chatsystem import ChatSystem
from . import ChatsystemRouter
from pydantic import BaseModel, ConfigDict, constr
from typing import Annotated, AsyncGenerator, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from api.authentication import get_authenticated_user, User
from database import session_scope, models
import uuid
from starlette.responses import StreamingResponse
import datetime
import re


class ChatRequest(BaseModel):
    # Limit the incoming user message to a maximum of 512 characters.
    message: constr(max_length=512)

class FeedbackRequest(BaseModel):
    rating: bool | None = None
    feedback: str | None = None

class NonStreamChatResponse(BaseModel):
    response: str
    user_msg_id: str | None = None
    assistant_msg_id: str | None = None

class MessageResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime.datetime
    role: str
    content: str
    rating: Optional[bool]
    feedback: Optional[str]

    model_config = ConfigDict(from_attributes=True)


async def stream_response_content(response_generator, http_request, bot_uuid: str | None = None) -> AsyncGenerator[str, None]:
    """Yield message ID first (if any) then assistant chunks while the client remains connected."""
    # Send the UUIDs first if they exist
    if bot_uuid:
        yield f"{bot_uuid}\n\n"
    for chunk in response_generator:
        # Stop streaming if the client disconnected
        if await http_request.is_disconnected():
            break
        chunk = str(chunk)
        chunk_pl = "[DONE]" if not chunk else chunk
        if re.fullmatch(r"\n+", str(chunk)):
            chunk_pl = '\n'.join(["[NEWLINE]" for _ in chunk])
        yield f"{chunk_pl}\n"

@ChatsystemRouter.post("/conversations/{conversation_id}/chat")
async def chat_with_system(
    conversation_id: str,
    chat_request: ChatRequest,
    http_request: Request,
    current_user: Annotated[User, Depends(get_authenticated_user)],
    stream: bool = Query(False),
    precreate_uuids: bool = Query(False),
):
    try:
        # Validate the UUID format early
        conversation_uuid = uuid.UUID(str(conversation_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id")
    with session_scope() as db:
         conversation = (
            db.query(models.Conversation)
            .filter(models.Conversation.id == conversation_uuid, models.Conversation.owner_id == current_user.id)
            .first()
        )
    try:
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        chat_system = ChatSystem(user = current_user, conversation = conversation)
        cs_resp, ids  = chat_system.receive(chat_request.message, stream = stream, include_ids=True)
        if stream:
            return StreamingResponse(stream_response_content(
                cs_resp, http_request, bot_uuid=(ids['assistant_id'] if precreate_uuids else None)
            ))
        return NonStreamChatResponse(
            response = cs_resp,
            user_msg_id = ids['user_id'],
            assistant_msg_id = ids['assistant_id']
        )
    except:
            raise HTTPException(status_code=500, detail="something went wrong")
    finally:
        chat_system.close()


@ChatsystemRouter.post("/conversations/{conversation_id}/messages/{message_id}/feedback", response_model=MessageResponse)
async def rate_message(
    conversation_id: str,
    message_id: str,
    payload: FeedbackRequest,
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Rate and/or give feedback on an assistant message.
    - Requires authentication.
    - Applies only to assistant messages belonging to the user's conversation.
    """
    if payload.rating is None and (payload.feedback is None or payload.feedback == ""):
        raise HTTPException(status_code=400, detail="Provide at least one of: rating or feedback")
    try:
        with session_scope(write_enabled=True) as session:
            msg: models.Message | None = (
                session.query(models.Message)
                .join(models.Conversation, models.Conversation.id == models.Message.conversation_id)
                .filter(
                    models.Message.id == message_id,
                    models.Message.conversation_id == conversation_id,
                    models.Message.role == "assistant",
                    models.Conversation.owner_id == current_user.id,
                )
                .one_or_none()
            )

            if msg is None:
                raise HTTPException(status_code=404, detail="Message not found or not accessible")

            if payload.rating is not None:
                msg.rating = payload.rating
            if payload.feedback is not None:
                msg.feedback = payload.feedback

            session.add(msg)
            session.flush()
            session.refresh(msg)
            return msg
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
