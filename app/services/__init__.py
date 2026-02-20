# app/services/__init__.py
# Makes call_openrouter importable as `from app.services import call_openrouter`
# so existing main.py /chat endpoint and new voice_orchestrator both work
# without changing their import paths.

from app.services.openrouter import call_openrouter  # noqa: F401