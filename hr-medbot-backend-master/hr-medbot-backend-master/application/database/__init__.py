import os
import sqlalchemy
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
from . import models

DATABASE_URL = os.getenv("DATABASE_URI")

engine = sqlalchemy.create_engine(
    DATABASE_URL,
    pool_size=5, # default pool size
    max_overflow=10, # allow 10 connections beyond pool_size
    pool_timeout=30, # timeout after 30s waiting for a connection
    pool_recycle=1800, # recycle connections after 30 min
    pool_pre_ping=True, # verify connections before using from pool
    executemany_mode='values_plus_batch' # optimize batch operations
)

# Create a session factory with thread safety
session_factory = sessionmaker(bind=engine,
                               autoflush=False,
                               expire_on_commit=False)
Session = scoped_session(session_factory)

# Context manager for safer session handling

@contextmanager
def session_scope(write_enabled=False):
    """Provide a transactional scope around a series of operations."""
    session = Session()
    try:
        yield session
        if write_enabled:
            session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

__all__ = ["session_scope", "models"]
