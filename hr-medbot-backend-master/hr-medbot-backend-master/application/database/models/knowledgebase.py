


from sqlalchemy import Column, String, DateTime, Text, JSON, ForeignKey, Index, Enum, ARRAY
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from .base import Base

import uuid
import datetime
import enum
import os

DB_VECTOR_DIMENSION = int(os.getenv("EMBEDDING_NDIMS", 1024))

"""
This file contains the models operated by the vectorization module.
"""



class FileStatus(enum.Enum):
    PROCESSING = "processing"
    FAILED = "failed"
    OK = "ok"


class File(Base):
    FileStatus = FileStatus
    __tablename__ = "knowledgebase_files"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    datetime = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    title = Column(String, nullable=False)
    summary = Column(String, nullable=True)


    # Processing status
    status = Column(
        Enum(
            FileStatus,
            name="file_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        default=FileStatus.PROCESSING,
    )
    error_message = Column(Text, nullable=True)

    # Relationships
    big_chunks = relationship(
        "BigChunk",
        back_populates="file",
        cascade="all, delete-orphan",
    )
    small_chunks = relationship(
        "SmallChunk",
        back_populates="file",
        cascade="all, delete-orphan",
    )
    summaries = relationship(
        "BigChunkSummary",
        back_populates="file",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<File(id='{self.id}', title='{self.title}', status='{self.status.value}')>"


class BigChunk(Base):
    __tablename__ = "knowledgebase_bigchunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    text = Column(Text, nullable=False)
    file_id = Column(String, ForeignKey("knowledgebase_files.id", ondelete="CASCADE"))

    # Relationships
    file = relationship("File", back_populates="big_chunks")
    summaries = relationship(
        "BigChunkSummary",
        back_populates="big_chunk",
        cascade="all, delete-orphan",
    )
    small_chunks = relationship(
        "SmallChunk",
        back_populates="big_chunk",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<BigChunk(id='{self.id}', file_id='{self.file_id}')>"


class BigChunkSummary(Base):
    __tablename__ = "knowledgebase_bc_summaries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    text = Column(Text, nullable=False)
    big_chunk_id = Column(String, ForeignKey("knowledgebase_bigchunks.id", ondelete="CASCADE"))
    file_id = Column(String, ForeignKey("knowledgebase_files.id", ondelete="CASCADE"))

    embedding = Column(Vector(DB_VECTOR_DIMENSION))

    # Relationships
    big_chunk = relationship("BigChunk", back_populates="summaries")
    file = relationship("File", back_populates="summaries")

    def __repr__(self):
        return f"<BigChunkSummary(id='{self.id}', big_chunk_id='{self.big_chunk_id}')>"


class SmallChunk(Base):
    __tablename__ = "knowledgebase_smallchunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    text = Column(Text, nullable=False)
    big_chunk_id = Column(String, ForeignKey("knowledgebase_bigchunks.id", ondelete="CASCADE"))
    file_id = Column(String, ForeignKey("knowledgebase_files.id", ondelete="CASCADE"))
    embedding = Column(Vector(DB_VECTOR_DIMENSION))

    # Relationships
    big_chunk = relationship("BigChunk", back_populates="small_chunks")
    file = relationship("File", back_populates="small_chunks")

    def __repr__(self):
        return f"<SmallChunk(id='{self.id}', big_chunk_id='{self.big_chunk_id}')>"



Index("idx_smallchunk_embedding_hnsw", SmallChunk.embedding, postgresql_using="hnsw", unique=False, postgresql_ops={'embedding': 'vector_cosine_ops'})
Index("idx_summary_embedding_hnsw", BigChunkSummary.embedding, postgresql_using="hnsw", unique=False, postgresql_ops={'embedding': 'vector_cosine_ops'})




__all__ = [
    "DB_VECTOR_DIMENSION",
    "FileStatus",
    "SmallChunk",
    "BigChunkSummary",
    "BigChunk",
    "File"
]
