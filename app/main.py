from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.models import ChatRequest, ChatResponse
from app.services import call_openrouter

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):

    system_prompt = f"""
    You are HUMSAFAR, an intelligent heritage guide.

    User is currently at: {req.site_name}

    Instructions:
    - If question is about the monument, answer in detail.
    - Suggest important areas to explore.
    - If question is general, answer normally.
    - Keep responses engaging and clear.
    - Do not hallucinate unknown facts.
    """

    messages = [{"role": "system", "content": system_prompt}]
    messages += req.history
    messages.append({"role": "user", "content": req.message})

    reply = await call_openrouter(messages)

    return ChatResponse(reply=reply)
