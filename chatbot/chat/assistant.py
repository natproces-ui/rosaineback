# backend/chat/assistant.py
from fastapi import Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import google.generativeai as genai
import time
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("GOOGLE_API_KEY manquante dans le fichier .env")

genai.configure(api_key=api_key)
model = genai.GenerativeModel("models/gemini-2.0-flash")
print("✅ Modèle Gemini configuré")


# ===================== MODÈLES PYDANTIC =====================

class TranscriptSegment(BaseModel):
    start: float
    duration: float
    text: str

class AssistantRequest(BaseModel):
    question: str
    grade: Optional[str] = None
    subject: Optional[str] = None
    course_title: Optional[str] = None
    course_level: Optional[str] = None
    video_title: Optional[str] = None
    video_url: Optional[str] = None
    current_time: Optional[float] = None
    transcript: Optional[List[TranscriptSegment]] = None


# ===================== HELPERS =====================

def format_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"

def format_transcript(transcript: List[TranscriptSegment], start: float = None, end: float = None) -> str:
    if not transcript:
        return ""
    filtered = transcript
    if start is not None:
        filtered = [s for s in filtered if s.start >= start]
    if end is not None:
        filtered = [s for s in filtered if s.start <= end]
    return "\n".join([f"[{format_time(s.start)}] {s.text}" for s in filtered])


# ===================== POST (avec transcription) =====================

async def ai_assistant_text_post(request: AssistantRequest):
    """Assistant avec accès à la transcription complète"""
    try:
        context_parts = []
        if request.course_title:
            context_parts.append(f"📚 Cours: {request.course_title}")
        if request.course_level:
            context_parts.append(f"🎓 Niveau: {request.course_level}")
        if request.video_title:
            context_parts.append(f"🎬 Vidéo: {request.video_title}")
        if request.current_time is not None:
            context_parts.append(f"⏱️ Position: {format_time(request.current_time)}")

        transcript_section = ""
        if request.transcript:
            full = format_transcript(request.transcript)
            transcript_section = f"\nTRANSCRIPTION COMPLÈTE:\n{full}\n"

        prompt = f"""
Tu es un assistant pédagogique qui aide l'élève à comprendre son cours.

CONTEXTE:
{chr(10).join(context_parts)}
Matière: {request.subject or "Mathématiques"}
{transcript_section}

CAPACITÉS:
- Tu as accès à TOUTE la transcription avec timestamps
- Si l'élève demande une plage (ex: "de 4:00 à 5:00"), CITE ce passage
- Format citation: "À [MM:SS], le prof dit: '[texte]'"

MATHS EN LATEX:
- Inline: $x^2$, $\\frac{{a}}{{b}}$, $\\sqrt{{x}}$
- Ensembles: $\\mathbb{{R}}$, $\\mathbb{{N}}$, $\\mathbb{{Z}}$

STRUCTURE:
📺 [Citation avec timing si pertinent]
💡 [Explication simple]
📝 [Exemple concret]
✅ [Question de vérification]

Style: amical, concis, 5-8 phrases max.

QUESTION: {request.question}
"""

        print(f"🔍 Question: {request.question}")
        print(f"📝 Segments: {len(request.transcript) if request.transcript else 0}")

        response = model.generate_content(prompt)
        return JSONResponse(content={"response": response.text})

    except Exception as e:
        print(f"❌ Erreur: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ===================== GET (version légère) =====================

async def ai_assistant_text(
    grade: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    question: str = Query(...),
    course_title: Optional[str] = Query(None),
    course_level: Optional[str] = Query(None),
    video_title: Optional[str] = Query(None),
    video_url: Optional[str] = Query(None),
    transcript_context: Optional[str] = Query(None)
):
    """Version GET (sans transcription complète)"""
    try:
        context_parts = []
        if course_title:
            context_parts.append(f"Cours: {course_title}")
        if course_level:
            context_parts.append(f"Niveau: {course_level}")
        if video_title:
            context_parts.append(f"Vidéo: {video_title}")
        if transcript_context:
            context_parts.append(f"Extrait vidéo:\n{transcript_context}")

        prompt = f"""
Tu es un assistant pédagogique.

CONTEXTE:
{chr(10).join(context_parts) or "Aucun contexte."}
Niveau: {grade or "Non spécifié"}
Matière: {subject or "Non spécifié"}

QUESTION: {question}

Réponds de façon concise et pédagogique. Utilise $...$ pour les maths.
"""

        response = model.generate_content(prompt)
        return JSONResponse(content={"response": response.text})

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ===================== IMAGE =====================

async def ai_assistant_image(
    grade: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    question: str = Query(...),
    file_path: str = Query(...),
    course_title: Optional[str] = Query(None),
    course_level: Optional[str] = Query(None),
    video_title: Optional[str] = Query(None)
):
    try:
        uploaded_file = genai.upload_file(path=file_path, display_name="image")
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(5)
            uploaded_file = genai.get_file(uploaded_file.name)

        prompt = f"Analyse cette image. Niveau: {grade}. Question: {question}"
        response = model.generate_content([prompt, uploaded_file])
        return JSONResponse(content={"response": response.text})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ===================== RECOMMANDATIONS =====================

async def course_recommendation(
    grade: Optional[str] = Query(None),
    subject: Optional[str] = Query(None)
):
    return JSONResponse(content={
        "response": f"Recommandations pour {grade or 'niveau'} en {subject or 'matière'}."
    })