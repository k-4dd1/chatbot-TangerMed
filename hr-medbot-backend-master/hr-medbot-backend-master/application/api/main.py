import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import authentication
from . import chatsystem
from . import voicechat
from . import user_management
from . import knowledgebase

# Read PROXY_PREFIX from environment (e.g., "/subpath" for nginx proxy_pass)
PROXY_PREFIX = os.getenv("PROXY_PREFIX", "").rstrip("/")
# Ensure prefix starts with / if provided
if PROXY_PREFIX and not PROXY_PREFIX.startswith("/"):
    PROXY_PREFIX = "/" + PROXY_PREFIX

app = FastAPI(root_path=PROXY_PREFIX if PROXY_PREFIX else None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"]
)

app.include_router(authentication.AUTH_ROUTER, prefix="/auth", tags=["Authentication"])
app.include_router(authentication.PASS_RESET_ROUTER, prefix='/auth/password-reset', tags=["Authentication"])
app.include_router(user_management.UserManagementRouter, prefix='/administration', tags=['Administration'])
app.include_router(knowledgebase.KNOWLEDGEBASE_ROUTER, prefix='/knowledgebase', tags=['Knowledgebase'])
app.include_router(knowledgebase.UPLOAD_ROUTER, prefix='/knowledgebase', tags=['Knowledgebase'])
app.include_router(chatsystem.ChatsystemRouter, prefix='/chatsystem', tags=['Chatsystem'])
app.include_router(voicechat.router, prefix='/voicechat', tags=['Voicechat'])

@app.get("/")
async def root():
    return {"serive-status": "healthy"} 

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)