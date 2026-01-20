from api.authentication import get_authenticated_user, User
from . import ChatsystemRouter
from pydantic import BaseModel, ConfigDict, constr
import datetime
import uuid
from typing import Annotated, List, Optional
from database import session_scope
from database.models import Conversation, Message
from fastapi import APIRouter, HTTPException, Depends, Request

####### MODELS ##########

class ConversationModel(BaseModel):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime
    title: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)

class MessageResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime.datetime
    role: str
    content: str
    rating: Optional[bool]
    feedback: Optional[str]

    model_config = ConfigDict(from_attributes=True)



###### /MODELS #########




######### Conversations List ######

@ChatsystemRouter.get("/conversations", response_model=List[ConversationModel])
async def list_conversations(
    current_user: Annotated[User, Depends(get_authenticated_user)]
    ):
    """Lists conversations, paginated.
    # Requires authentication.
    """
    with session_scope() as db:
        conversations = (
            db.query(Conversation)
            .filter(Conversation.owner_id == current_user.id)
            .order_by(Conversation.updated_at.desc())
            .all()
        )
    return conversations

@ChatsystemRouter.post("/conversations", response_model=ConversationModel)
async def create_conversation(
    current_user: Annotated[User, Depends(get_authenticated_user)]
    ):
    """
    Creates a new conversation and returns the conversation_id.
    # Requires authentication.
    """
    try:
        with session_scope(write_enabled=True) as db:
            conversation = Conversation(owner_id=current_user.id)
            db.add(conversation)
            db.flush()
            db.refresh(conversation)
        return conversation
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


########## /Conversations List #####



######### Conversation History #####
@ChatsystemRouter.get("/conversations/{conversation_id}/history", response_model=List[MessageResponse])
async def get_conversation_history(conversation_id: str,
    current_user: Annotated[User, Depends(get_authenticated_user)]
    ):
    """Gets chat history for a specific conversation, paginated.
    # Requires authentication.
    """
    with session_scope() as db:
        try:
            # Validate the UUID format early
            conversation_uuid = uuid.UUID(str(conversation_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid conversation_id")

        # Ensure the conversation exists and belongs to the current user
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_uuid, Conversation.owner_id == current_user.id)
            .first()
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Fetch messages ordered by creation time (latest first)
        messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_uuid)
            .order_by(Message.created_at)
            .all()
        )
    return messages 
######### /conversation history #####
