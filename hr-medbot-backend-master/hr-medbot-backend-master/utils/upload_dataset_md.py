from __future__ import annotations

import json
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from requests import Response
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Purpose: Upload markdown files from data_playground/dataset/ to the
#          knowledge base API endpoint.
#
# Usage:
#   Set environment variables (or edit globals below):
#     KB_BASE_URL=http://localhost:13537
#     KB_USERNAME=admin
#     KB_PASSWORD=bot-admin-1337
#
#   Run: python utils/upload_dataset_md.py
#
# Features:
#   - Resumes from last checkpoint (upload_progress.jsonl)
#   - Handles server busy states and network retries
#   - Progress bar shows upload status
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CONFIG (edit these globals)
# ---------------------------------------------------------------------------

# Server base URL, e.g. "http://localhost:13337" or "https://your-domain.tld"
BASE_URL = os.getenv("KB_BASE_URL", "http://localhost:13537").rstrip("/")

# Credentials for an admin user (required by /knowledgebase/upload)
USERNAME = os.getenv("KB_USERNAME", "admin")
PASSWORD = os.getenv("KB_PASSWORD", "bot-admin-1337")

# Dataset root folder. Title will be the relative path from DATA_ROOT_PARENT, e.g. "dataset/..."
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT_PARENT = REPO_ROOT / "data_playground"
DATASET_ROOT = DATA_ROOT_PARENT / "dataset"

# Progress checkpoint file (JSONL). Safe to delete to re-upload everything.
PROGRESS_FILE = DATA_ROOT_PARENT / "upload_progress.jsonl"

# Upload endpoint (do not change unless server routes changed)
AUTH_TOKEN_PATH = "/auth/token"
UPLOAD_PATH = "/knowledgebase/upload"

# Upload behavior
FILE_GLOB = "*.md"
REQUEST_TIMEOUT_S = 60

# Server-busy (queue full) handling
BUSY_MAX_WAIT_S = 15 * 60  # total time to keep retrying on HTTP 503
BUSY_BASE_SLEEP_S = 5
BUSY_MAX_SLEEP_S = 30

# Network retry handling
NET_MAX_RETRIES = 5
NET_BASE_SLEEP_S = 2
NET_MAX_SLEEP_S = 20

# Optional pacing between successful uploads (helps avoid hammering)
SUCCESS_SLEEP_S = 0.0


@dataclass
class ProgressRecord:
    rel_path: str
    abs_path: str
    status: str  # "uploaded" | "failed"
    http_status: int | None = None
    job_id: str | None = None
    error: str | None = None
    ts: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "abs_path": self.abs_path,
            "status": self.status,
            "http_status": self.http_status,
            "job_id": self.job_id,
            "error": self.error,
            "ts": self.ts,
        }


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sleep_with_jitter(base_s: float, max_s: float, attempt: int) -> None:
    # Exponential backoff with jitter, capped
    raw = min(max_s, base_s * (2 ** max(0, attempt - 1)))
    time.sleep(raw * (0.75 + random.random() * 0.5))


def _load_already_uploaded(progress_path: Path) -> set[str]:
    uploaded: set[str] = set()
    if not progress_path.exists():
        return uploaded
    with progress_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("status") == "uploaded" and rec.get("rel_path"):
                    uploaded.add(str(rec["rel_path"]))
            except Exception:
                # Ignore malformed lines; keep going
                continue
    return uploaded


def _append_progress(progress_path: Path, rec: ProgressRecord) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with progress_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec.to_json(), ensure_ascii=False) + "\n")


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


def _login(session: requests.Session) -> str:
    resp = session.post(
        _url(AUTH_TOKEN_PATH),
        json={"username": USERNAME, "password": PASSWORD},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Login succeeded but no access_token in response: {data!r}")
    return str(token)


def _is_busy_response(resp: Response) -> bool:
    if resp.status_code != 503:
        return False
    try:
        data = resp.json()
        return str(data.get("detail", "")).lower().startswith("server busy")
    except Exception:
        return True


def _iter_md_files(root: Path) -> Iterable[Path]:
    # Deterministic order for stable resume behavior
    yield from sorted(root.rglob(FILE_GLOB), key=lambda p: p.as_posix())


def _rel_title(path: Path) -> str:
    # Title is path relative to DATA_ROOT_PARENT, e.g. dataset/...
    return path.relative_to(DATA_ROOT_PARENT).as_posix()


def _upload_one(
    session: requests.Session,
    token: str,
    file_path: Path,
    title: str,
) -> tuple[Response, dict[str, Any] | None]:
    headers = {"Authorization": f"Bearer {token}"}
    with file_path.open("rb") as fp:
        files = {"uploaded_file": (file_path.name, fp, "text/markdown")}
        data = {"title": title}
        resp = session.post(
            _url(UPLOAD_PATH),
            headers=headers,
            files=files,
            data=data,
            timeout=REQUEST_TIMEOUT_S,
        )
    payload = None
    try:
        payload = resp.json()
    except Exception:
        payload = None
    return resp, payload


def main() -> int:
    if not DATASET_ROOT.exists():
        print(f"Dataset folder not found: {DATASET_ROOT}", file=sys.stderr)
        return 2

    if not USERNAME or not PASSWORD:
        print("Missing KB_USERNAME or KB_PASSWORD (or edit USERNAME/PASSWORD globals).", file=sys.stderr)
        return 2

    already = _load_already_uploaded(PROGRESS_FILE)
    all_files = list(_iter_md_files(DATASET_ROOT))
    pending = [p for p in all_files if _rel_title(p) not in already]

    print(f"Base URL: {BASE_URL}")
    print(f"Dataset root: {DATASET_ROOT}")
    print(f"Progress file: {PROGRESS_FILE}")
    print(f"Total .md files: {len(all_files)}")
    print(f"Already uploaded: {len(already)}")
    print(f"Pending: {len(pending)}")

    session = requests.Session()
    token = _login(session)

    with tqdm(total=len(pending), unit="file") as bar:
        for p in pending:
            title = _rel_title(p)
            busy_start = time.time()

            # network-level retries
            net_attempt = 0
            while True:
                try:
                    resp, payload = _upload_one(session, token, p, title)

                    # Token expired / invalid: refresh and retry once
                    if resp.status_code in (401, 403):
                        token = _login(session)
                        resp, payload = _upload_one(session, token, p, title)

                    # Queue full / server busy: wait and retry until BUSY_MAX_WAIT_S
                    if _is_busy_response(resp):
                        if time.time() - busy_start > BUSY_MAX_WAIT_S:
                            _append_progress(
                                PROGRESS_FILE,
                                ProgressRecord(
                                    rel_path=title,
                                    abs_path=str(p),
                                    status="failed",
                                    http_status=resp.status_code,
                                    error="server busy timeout",
                                    ts=_utc_ts(),
                                ),
                            )
                            break
                        _sleep_with_jitter(BUSY_BASE_SLEEP_S, BUSY_MAX_SLEEP_S, attempt=1)
                        continue

                    if resp.ok:
                        job_id = None
                        if isinstance(payload, dict):
                            job_id = payload.get("job_id")
                        _append_progress(
                            PROGRESS_FILE,
                            ProgressRecord(
                                rel_path=title,
                                abs_path=str(p),
                                status="uploaded",
                                http_status=resp.status_code,
                                job_id=str(job_id) if job_id else None,
                                ts=_utc_ts(),
                            ),
                        )
                    else:
                        _append_progress(
                            PROGRESS_FILE,
                            ProgressRecord(
                                rel_path=title,
                                abs_path=str(p),
                                status="failed",
                                http_status=resp.status_code,
                                error=(payload if isinstance(payload, dict) else resp.text)[:2000],
                                ts=_utc_ts(),
                            ),
                        )
                    break
                except requests.RequestException as exc:
                    net_attempt += 1
                    if net_attempt > NET_MAX_RETRIES:
                        _append_progress(
                            PROGRESS_FILE,
                            ProgressRecord(
                                rel_path=title,
                                abs_path=str(p),
                                status="failed",
                                error=f"network error after retries: {exc}",
                                ts=_utc_ts(),
                            ),
                        )
                        break
                    _sleep_with_jitter(NET_BASE_SLEEP_S, NET_MAX_SLEEP_S, attempt=net_attempt)

            bar.update(1)
            if SUCCESS_SLEEP_S > 0:
                time.sleep(SUCCESS_SLEEP_S)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


