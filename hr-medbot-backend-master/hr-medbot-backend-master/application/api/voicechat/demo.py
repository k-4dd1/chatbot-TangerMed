import io
import random
import httpx
from fastapi import Query, Depends
from fastapi.responses import StreamingResponse
from typing import Annotated

from api.authentication import get_authenticated_user, User

from . import router, engine

_DEMO_PHRASES = [
    # English variations
    "Hello! How can I help you today?",
    "Hi! What can I do for you?",
    "Greetings! I'm here to assist you.",
    # French variations
    "Bonjour! Comment puis-je vous aider aujourd'hui ?",
    "Salut ! Je suis là pour répondre à vos questions.",
    "Bienvenue ! Que puis-je faire pour vous ?",
    # Arabic variations
    "مرحبا, كيف يمكنني مساعدتك اليوم؟",
    "أهلا وسهلا, تفضلوا بطرح أي سؤال.",
    "تحياتي, أنا هنا لمساعدتكم."
]


@router.get("/speakers/test", include_in_schema=True)
async def speaker_test_endpoint(
    user: Annotated[User, Depends(get_authenticated_user)],
    speaker: str = Query(str(engine.XTTS_DEFAULT_SPEAKER_IDX)),
):
    """Return a short demo phrase synthesised via Phonebooth for the given *speaker*."""

    speakers_dict = engine.XTTS_SPEAKERS
    if speaker not in speakers_dict:
        return {
            "error": f"Invalid speaker id '{speaker}'. Available: {list(speakers_dict.keys())}"
        }

    text = random.choice(_DEMO_PHRASES)

    async with httpx.AsyncClient(base_url=engine.PHONEBOOTH_URL, timeout=40.0, headers=engine.PHONEBOOTH_HEADERS) as client:
        resp = await client.post("/tts", json={"text": text, "speaker": speaker})
        resp.raise_for_status()
        wav_bytes = resp.content

    return StreamingResponse(io.BytesIO(wav_bytes), media_type="audio/wav")
