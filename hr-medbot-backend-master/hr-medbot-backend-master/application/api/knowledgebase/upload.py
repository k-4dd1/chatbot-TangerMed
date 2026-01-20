from __future__ import annotations


"""Knowledgebase upload & background processing API."""

import os
import uuid
import shutil
from pathlib import Path
from typing import Annotated, Literal, Optional, List
from threading import Thread

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, status, Depends, Form
from diskcache import Cache, Deque, Lock

from api.authentication.authentication import get_authenticated_user
from database.models import User
from insertion.neo_inserter import NeoInserter

CONCURRENCY_LIMIT: int = int(os.getenv("KB_CONCURRENCY_LIMIT", "3"))
QUEUE_LIMIT: int = int(os.getenv("KB_QUEUE_LIMIT", "10"))
CACHE_DIR = os.getenv("KB_CACHE_DIR", "/tmp/neo_kb_queue")
UPLOAD_TMP_DIR = Path(os.getenv("KB_UPLOAD_TMP_DIR", "/tmp/neo_kb_uploads"))
UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)

cache = Cache(CACHE_DIR)
queue: Deque[str] = Deque(cache)  # type: ignore[assignment]
queue_lock = Lock(cache, "queue_lock")

IN_PROGRESS_KEY = "in_progress"


def _with_lock(func):
    def wrapper(*args, **kwargs):
        with queue_lock:
            return func(*args, **kwargs)
    return wrapper


def _get_in_progress() -> set[str]:
    return set(cache.get(IN_PROGRESS_KEY, set()))


def _set_in_progress(s: set[str]) -> None:
    cache.set(IN_PROGRESS_KEY, s)


@_with_lock
def _enqueue_job(file_path: Path, title: str, file_kwargs: dict[str, list[str]] | None = None) -> str:
    if len(queue) >= QUEUE_LIMIT:
        raise HTTPException(status_code=503, detail="Server busy, please try again later.")
    job_id = str(uuid.uuid4())
    cache.set(
        f"job:{job_id}",
        {
            "status": "queued",
            "file_path": str(file_path),
            "title": title,
            "file_kwargs": file_kwargs or {},
        },
    )
    queue.append(job_id)
    return job_id


def _process_job(job_id: str):
    job_key = f"job:{job_id}"
    job = cache.get(job_key)
    if not job:
        return
    file_path = Path(job["file_path"])
    title = job["title"]
    file_kwargs: dict[str, list[str]] = job.get("file_kwargs", {})

    inserter = NeoInserter()
    try:
        with open(file_path, "r", encoding="utf-8") as fp:
            text = fp.read()
        inserter.insert(title, text, **file_kwargs)
        new_status: Literal["completed", "failed"] = "completed"
    except Exception as exc:
        new_status = "failed"
        job["error"] = str(exc)
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass

    with queue_lock:
        in_prog = _get_in_progress()
        in_prog.discard(job_id)
        _set_in_progress(in_prog)
        job["status"] = new_status
        cache.set(job_key, job)

    _maybe_start_next_job()


@_with_lock
def _maybe_start_next_job():
    in_prog = _get_in_progress()
    if len(in_prog) >= CONCURRENCY_LIMIT or not queue:
        return
    job_id: str = queue.popleft()
    in_prog.add(job_id)
    _set_in_progress(in_prog)
    job = cache.get(f"job:{job_id}") or {}
    job["status"] = "processing"
    cache.set(f"job:{job_id}", job)
    Thread(target=_process_job, args=(job_id,), daemon=True).start()


UPLOAD_ROUTER = APIRouter()


@UPLOAD_ROUTER.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    uploaded_file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_authenticated_user)],
    title: Annotated[str | None, Form(description="Override file title")] = None,
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    suffix = Path(uploaded_file.filename or "upload.txt").suffix or ".txt"
    tmp_path = UPLOAD_TMP_DIR / f"{uuid.uuid4()}{suffix}"
    with tmp_path.open("wb") as dst:
        shutil.copyfileobj(uploaded_file.file, dst)

    effective_title = title or uploaded_file.filename or tmp_path.name
    job_id = _enqueue_job(tmp_path, effective_title)
    background_tasks.add_task(_maybe_start_next_job)
    return {"job_id": job_id, "status": "queued"}


@UPLOAD_ROUTER.get("/jobs")
async def list_jobs(
    current_user: Annotated[User, Depends(get_authenticated_user)],
    status: Optional[str] = None,
    limit: int | None = 100,
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    acceptable = {None, "queued", "processing", "completed", "failed"}
    if status not in acceptable:
        raise HTTPException(status_code=400, detail="Invalid status filter")
    jobs: List[dict] = []
    for key in cache.iterkeys():  # type: ignore[attr-defined]
        if isinstance(key, str) and key.startswith("job:"):
            job_id = key[4:]
            job = cache.get(key)
            if job and (status is None or job.get("status") == status):
                jobs.append({"job_id": job_id, **{k: v for k, v in job.items() if k != "file_path"}})
            if limit is not None and len(jobs) >= limit:
                break
    return jobs


@UPLOAD_ROUTER.get("/jobs/{job_id}")
async def job_status(job_id: str, current_user: Annotated[User, Depends(get_authenticated_user)]):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job = cache.get(f"job:{job_id}")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **{k: v for k, v in job.items() if k != "file_path"}}
