import os
from pathlib import Path
from fastapi.responses import HTMLResponse

from . import router

# Read PROXY_PREFIX from environment (same as in main.py)
PROXY_PREFIX = os.getenv("PROXY_PREFIX", "").rstrip("/")
if PROXY_PREFIX and not PROXY_PREFIX.startswith("/"):
    PROXY_PREFIX = "/" + PROXY_PREFIX


def _inject_proxy_prefix(html_content: str) -> str:
    """Inject a script tag that sets the PROXY_PREFIX global variable."""
    prefix_script = f'<script>window.PROXY_PREFIX = "{PROXY_PREFIX}";</script>'
    # Insert the script right after <head> tag
    if "<head>" in html_content:
        html_content = html_content.replace("<head>", f"<head>\n  {prefix_script}", 1)
    elif "<html>" in html_content:
        # If no <head> tag, insert after <html>
        html_content = html_content.replace("<html>", f"<html>\n  {prefix_script}", 1)
    else:
        # Fallback: prepend to content
        html_content = prefix_script + "\n" + html_content
    return html_content


@router.get("/", include_in_schema=False)
async def root_index():
    """Serve the client index.html file."""
    idx_path = Path(__file__).resolve().parent / "static/voicechat_index.html"
    with open(idx_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    html_content = _inject_proxy_prefix(html_content)
    return HTMLResponse(content=html_content, media_type="text/html")


@router.get("/stt-text", include_in_schema=False)
async def stt_text_index():
    """Serve the STT text demo page."""
    idx_path = Path(__file__).resolve().parent / "static/voicechat_stt_text.html"
    with open(idx_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    html_content = _inject_proxy_prefix(html_content)
    return HTMLResponse(content=html_content, media_type="text/html")
