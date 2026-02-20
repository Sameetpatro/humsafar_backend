# app/services/openrouter.py
# NEW FILE — extracted verbatim from the existing app/services.py
# The original services.py can be DELETED after adding this file.
# Import path for existing code: `from app.services import call_openrouter`
# (unchanged — __init__.py re-exports it).

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
_OPENROUTER_TIMEOUT = 60.0


async def call_openrouter(messages: list) -> str:
    """
    Sends messages to OpenRouter (OpenAI-compatible) and returns the reply text.
    Raises RuntimeError on non-200 status or missing response fields.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in environment")

    async with httpx.AsyncClient(timeout=_OPENROUTER_TIMEOUT) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":    "openai/gpt-4o-mini",
                "messages": messages,
            }
        )

    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter error {response.status_code}: {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"]