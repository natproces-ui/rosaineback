# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# Import des fonctions depuis les sous-modules
from chat.assistant import (
    ai_assistant_text,
    ai_assistant_image,
    course_recommendation,
    ai_assistant_text_post,  # ✅ NOUVEAU
    AssistantRequest          # ✅ NOUVEAU
)

from chat.assistant_exo import ai_assistant_exo

# Import du router transcription
from transcript import router as transcript_router

app = FastAPI()

# Configuration CORS SÉCURISÉE
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",              # Développement local (React/Next.js)
        "http://localhost:3001",              # Développement local (Svelte)
        "http://localhost:8080",              # Développement local (Vue)
        "https://rosaine-academy.org",        # Production
        "https://www.rosaine-academy.org",    # Production avec www
        "https://rosaine-academy.vercel.app", # Vercel preview (si déployé là)
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# === ENDPOINTS CHAT ===
app.get("/ai_assistant_text")(ai_assistant_text)
app.get("/ai_assistant_image")(ai_assistant_image)
app.get("/course_recommendation")(course_recommendation)
app.get("/ai_assistant_exo")(ai_assistant_exo)

# ✅ NOUVEAU : Route POST pour l'assistant avec transcription
@app.post("/ai_assistant_chat")
async def assistant_chat(request: AssistantRequest):
    return await ai_assistant_text_post(request)

# === ENDPOINTS TRANSCRIPTION ===
app.include_router(transcript_router)

@app.get("/")
async def root():
    return {"message": "Backend plateforme de cours - OK"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )