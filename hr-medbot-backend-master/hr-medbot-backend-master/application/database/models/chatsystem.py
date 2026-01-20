from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, ARRAY, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
from sqlalchemy.orm import relationship
from .base import Base

# -----------------------------
# Chat related tables
# -----------------------------

class Conversation(Base):
    """A single chat session belonging to a user. In-memory instances are persisted when the session ends."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # owner of the conversation (nullable for system conversations)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    owner = relationship("User", backref="conversations")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Optional: running summary for token budgeting
    token_budgeting_summary = Column(String, nullable=True)
    token_budgeting_message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", use_alter=True, name="fk_conversation_first_message"), nullable=True)

    # Title generated after first assistant response
    title = Column(String, nullable=True)

    # relationship to Messages (explicit foreign key to avoid ambiguity)
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", foreign_keys="Message.conversation_id")

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, owner={self.owner_id}, title={self.title})>"


class Message(Base):
    """Individual message inside a conversation."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"))
    conversation = relationship("Conversation", back_populates="messages", foreign_keys=[conversation_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    role = Column(String, nullable=False)  # "user" | "assistant" | "system"
    content = Column(String, nullable=False)

    # JSONB payload to store retrieved chunks ids or other metadata
    context = Column(JSONB, nullable=True)

    # Whether this message is a summary replacement (for token budgeting)
    is_summary = Column(Boolean, default=False)

    # rating and feedback
    rating = Column(Boolean, nullable=True)
    feedback = Column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role}, conversation={self.conversation_id})>"

