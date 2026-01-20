
from sqlalchemy import Column, String, Boolean, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
from .base import Base
from sqlalchemy.orm import relationship


# sbu, category, site

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    is_admin = Column(Boolean, default=False)
    phone_number = Column(String, unique=True, index=True, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    llm_extra_context = Column(String, nullable=True)

    # Access control fields

    # relationship to conversations
    # conversations = relationship("Conversation", back_populates="owner", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id='{self.id}', username='{self.username}')>"


__all__ = ["User"]