from pydantic import BaseModel
from typing import List, Dict

class ChatRequest(BaseModel):
    message: str
    site_name: str
    site_id: str
    history: List[Dict[str, str]] = []

class ChatResponse(BaseModel):
    reply: str
