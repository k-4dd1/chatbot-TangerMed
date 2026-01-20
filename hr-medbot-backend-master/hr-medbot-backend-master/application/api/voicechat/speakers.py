from . import engine
from . import router


@router.get("/speakers", response_model=dict[str, str])
async def speakers_endpoint() -> dict[str, str]:
    """Return mapping of speaker index to speaker name."""
    return engine.XTTS_SPEAKERS
