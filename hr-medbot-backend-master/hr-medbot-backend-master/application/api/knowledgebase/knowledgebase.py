from __future__ import annotations

"""CRUD operations for knowledge-base `File` objects.

Admin-only endpoints:
* GET    /               – list files
* GET    /{file_id}      – retrieve one
* PUT    /{file_id}      – update metadata (title, tangermed_* fields)
* DELETE /{file_id}      – delete file and cascade chunks
"""

from typing import Annotated, List, Optional
import uuid

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, constr

from database import session_scope
from database.models.knowledgebase import File, FileStatus
from api.authentication.authentication import get_authenticated_user
from database.models import User


class FileResponse(BaseModel):
    id: str
    title: str
    status: str
    class Config:  # noqa: D106
        from_attributes = True


class UpdateFileRequest(BaseModel):
    title: Optional[constr(strip_whitespace=True, min_length=1, max_length=255)] = None  # type: ignore[name-defined]


KNOWLEDGEBASE_ROUTER = APIRouter()


def _ensure_admin(user: User):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")


@KNOWLEDGEBASE_ROUTER.get("/", response_model=List[FileResponse])
async def list_files(current_user: Annotated[User, Depends(get_authenticated_user)], status_filter: Optional[str] = None):
    """Return all files. Optional **status_filter** to filter by FileStatus."""
    _ensure_admin(current_user)
    with session_scope() as db:
        q = db.query(File)
        if status_filter is not None:
            try:
                status_val = FileStatus(status_filter)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid status filter")
            q = q.filter(File.status == status_val)
        files = q.order_by(File.datetime.desc()).all()
        return files


@KNOWLEDGEBASE_ROUTER.get("/{file_id}", response_model=FileResponse)
async def get_file(file_id: str, current_user: Annotated[User, Depends(get_authenticated_user)]):
    _ensure_admin(current_user)
    with session_scope() as db:
        file = db.query(File).filter(File.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="File not found")
        return file


@KNOWLEDGEBASE_ROUTER.put("/{file_id}", response_model=FileResponse)
async def update_file(file_id: str, req: UpdateFileRequest, current_user: Annotated[User, Depends(get_authenticated_user)]):
    _ensure_admin(current_user)
    with session_scope(write_enabled=True) as db:
        file = db.query(File).filter(File.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="File not found")
        if req.title is not None:
            file.title = req.title
        db.add(file)
        db.flush()
        db.refresh(file)
        return file


@KNOWLEDGEBASE_ROUTER.delete("/{file_id}")
async def delete_file(file_id: str, current_user: Annotated[User, Depends(get_authenticated_user)]):
    _ensure_admin(current_user)
    with session_scope(write_enabled=True) as db:
        file = db.query(File).filter(File.id == file_id).first()
        if not file:
            raise HTTPException(status_code=404, detail="File not found")
        db.delete(file)
        return {"message": "Deleted"}
