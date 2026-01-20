import sys
from pathlib import Path
from fastapi import APIRouter

# Ensure project root is on sys.path so that absolute imports like `chatsystem.*` work
sys.path.append(str(Path(__file__).resolve().parents[2]))

# Shared router that all sub-modules will attach their endpoints to
router = APIRouter()

# Import sub-modules for their side-effects (route registration)
from . import conversation  # noqa: F401,E402
from . import speakers      # noqa: F401,E402
from . import demo          # noqa: F401,E402
from . import static        # noqa: F401,E402
# Register stt_text routes
from . import stt_text       # noqa: F401,E402
