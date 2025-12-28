# backend/chat/assistant.py
from fastapi import Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import time

# Import centralisé depuis manager
from manager import model, log_question, log_success, log_error, log_info
from manager.quota_manager import check_quota, increment_quota, get_quota_warning_level
import google.generativeai as genai


# ===================== MODÈLES PYDANTIC =====================

class TranscriptSegment(BaseModel):
    start: float
    duration: float
    text: str

class AssistantRequest(BaseModel):
    question: str
    user_id: str  # 🆕 AJOUTÉ
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
        # 🔒 ÉTAPE 1 : Vérifier le quota
        log_info(f"Vérification quota pour user {request.user_id}", "🔒")
        quota_info = await check_quota(request.user_id, "video_assistant")
        
        if not quota_info["allowed"]:
            log_info(f"❌ Quota dépassé pour {request.user_id}", "🚫")
            warning_level = get_quota_warning_level(quota_info["percentage"])
            
            return JSONResponse(
                content={
                    "error": "Quota quotidien dépassé",
                    "message": "Vous avez atteint votre limite de questions vidéo pour aujourd'hui.",
                    "quota": {
                        "used": quota_info["used"],
                        "limit": quota_info["limit"],
                        "remaining": quota_info["remaining"],
                        "percentage": quota_info["percentage"],
                        "warning_level": warning_level
                    },
                    "upgrade_url": "/pricing",
                    "plan": quota_info["plan"]
                },
                status_code=429
            )
        
        # Logging avec info quota
        log_question(request.question, f"Vidéo: {request.video_title or 'Aucune'} | Quota: {quota_info['used']}/{quota_info['limit']}")
        log_info(f"Segments: {len(request.transcript) if request.transcript else 0}", "📝")
        
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

STRUCTURE DE RÉPONSE:
📺 [Citation avec timing si pertinent]
💡 [Explication simple]
📝 [Exemple concret]
✅ [Question de vérification]

STYLE:
- Ton bienveillant et encourageant
- Phrases courtes et précises
- Emojis pour structurer (📺 💡 📝 ✅)
- Maximum 5-8 phrases (sauf explication complexe)

QUESTION: {request.question}
"""

        response = model.generate_content(prompt)
        
        # ✅ ÉTAPE 2 : Incrémenter le quota après succès
        await increment_quota(request.user_id, "video_assistant")
        
        # Calculer le nouveau quota
        new_used = quota_info["used"] + 1
        new_remaining = quota_info["limit"] - new_used
        new_percentage = round((new_used / quota_info["limit"]) * 100, 1)
        warning_level = get_quota_warning_level(new_percentage)
        
        log_success(f"Quota: {new_used}/{quota_info['limit']}")
        
        return JSONResponse(content={
            "response": response.text,
            "quota": {
                "used": new_used,
                "limit": quota_info["limit"],
                "remaining": new_remaining,
                "percentage": new_percentage,
                "warning_level": warning_level
            },
            "timestamp": datetime.now().isoformat()
        })

    except AttributeError as e:
        error_msg = f"Erreur de configuration de l'API: {str(e)}"
        log_error(e, "Configuration API")
        return JSONResponse(content={"error": error_msg}, status_code=500)
    except Exception as e:
        error_msg = f"Erreur lors de la génération: {str(e)}"
        log_error(e, "Génération réponse")
        return JSONResponse(content={"error": error_msg}, status_code=500)


# ===================== GET (version légère) =====================

async def ai_assistant_text(
    user_id: str = Query(..., description="ID de l'utilisateur (Firebase UID)"),  # 🆕 AJOUTÉ
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
        # 🔒 Vérifier le quota
        log_info(f"Vérification quota pour user {user_id}", "🔒")
        quota_info = await check_quota(user_id, "video_assistant")
        
        if not quota_info["allowed"]:
            log_info(f"❌ Quota dépassé pour {user_id}", "🚫")
            warning_level = get_quota_warning_level(quota_info["percentage"])
            
            return JSONResponse(
                content={
                    "error": "Quota quotidien dépassé",
                    "message": "Vous avez atteint votre limite de questions vidéo pour aujourd'hui.",
                    "quota": {
                        "used": quota_info["used"],
                        "limit": quota_info["limit"],
                        "remaining": quota_info["remaining"],
                        "percentage": quota_info["percentage"],
                        "warning_level": warning_level
                    },
                    "upgrade_url": "/pricing",
                    "plan": quota_info["plan"]
                },
                status_code=429
            )
        
        # Logging
        log_question(question, f"GET | Quota: {quota_info['used']}/{quota_info['limit']}")
        
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

STYLE:
- Ton bienveillant et encourageant
- Phrases courtes et précises
- Emojis pour structurer (💡 📝 ✅)
- Concis et pédagogique

QUESTION: {question}

Réponds de façon concise et pédagogique. Utilise $...$ pour les maths.
"""

        response = model.generate_content(prompt)
        
        # ✅ Incrémenter le quota
        await increment_quota(user_id, "video_assistant")
        
        # Calculer le nouveau quota
        new_used = quota_info["used"] + 1
        new_remaining = quota_info["limit"] - new_used
        new_percentage = round((new_used / quota_info["limit"]) * 100, 1)
        warning_level = get_quota_warning_level(new_percentage)
        
        log_success(f"Quota: {new_used}/{quota_info['limit']}")
        
        return JSONResponse(content={
            "response": response.text,
            "quota": {
                "used": new_used,
                "limit": quota_info["limit"],
                "remaining": new_remaining,
                "percentage": new_percentage,
                "warning_level": warning_level
            },
            "timestamp": datetime.now().isoformat()
        })

    except AttributeError as e:
        error_msg = f"Erreur de configuration de l'API: {str(e)}"
        log_error(e, "Configuration API")
        return JSONResponse(content={"error": error_msg}, status_code=500)
    except Exception as e:
        error_msg = f"Erreur lors de la génération: {str(e)}"
        log_error(e, "Génération réponse")
        return JSONResponse(content={"error": error_msg}, status_code=500)


# ===================== IMAGE =====================

async def ai_assistant_image(
    user_id: str = Query(..., description="ID de l'utilisateur (Firebase UID)"),  # 🆕 AJOUTÉ
    grade: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    question: str = Query(...),
    file_path: str = Query(...),
    course_title: Optional[str] = Query(None),
    course_level: Optional[str] = Query(None),
    video_title: Optional[str] = Query(None)
):
    try:
        # 🔒 Vérifier le quota
        log_info(f"Vérification quota pour user {user_id}", "🔒")
        quota_info = await check_quota(user_id, "image_upload")
        
        if not quota_info["allowed"]:
            log_info(f"❌ Quota dépassé pour {user_id}", "🚫")
            warning_level = get_quota_warning_level(quota_info["percentage"])
            
            return JSONResponse(
                content={
                    "error": "Quota quotidien dépassé",
                    "message": "Vous avez atteint votre limite d'uploads d'images pour aujourd'hui.",
                    "quota": {
                        "used": quota_info["used"],
                        "limit": quota_info["limit"],
                        "remaining": quota_info["remaining"],
                        "percentage": quota_info["percentage"],
                        "warning_level": warning_level
                    },
                    "upgrade_url": "/pricing",
                    "plan": quota_info["plan"]
                },
                status_code=429
            )
        
        # Logging
        log_question(question, f"IMAGE | Quota: {quota_info['used']}/{quota_info['limit']}")
        log_info(f"Fichier: {file_path}", "📁")
        
        uploaded_file = genai.upload_file(path=file_path, display_name="image")
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(5)
            uploaded_file = genai.get_file(uploaded_file.name)

        prompt = f"""
Tu es un assistant pédagogique qui analyse des images/captures d'écran.

CONTEXTE:
Niveau: {grade or "Non spécifié"}
Matière: {subject or "Non spécifié"}
Cours: {course_title or "Non spécifié"}

STYLE:
- Ton bienveillant et encourageant
- Phrases courtes et précises
- Emojis pour structurer (💡 📝 ✅)
- Utilise $...$ pour les formules mathématiques

QUESTION: {question}

Analyse l'image et réponds de façon pédagogique.
"""
        
        response = model.generate_content([prompt, uploaded_file])
        
        # ✅ Incrémenter le quota
        await increment_quota(user_id, "image_upload")
        
        # Calculer le nouveau quota
        new_used = quota_info["used"] + 1
        new_remaining = quota_info["limit"] - new_used
        new_percentage = round((new_used / quota_info["limit"]) * 100, 1) if quota_info["limit"] > 0 else 100
        warning_level = get_quota_warning_level(new_percentage)
        
        log_success(f"Réponse image générée | Quota: {new_used}/{quota_info['limit']}")
        
        return JSONResponse(content={
            "response": response.text,
            "quota": {
                "used": new_used,
                "limit": quota_info["limit"],
                "remaining": new_remaining,
                "percentage": new_percentage,
                "warning_level": warning_level
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except AttributeError as e:
        error_msg = f"Erreur de configuration de l'API: {str(e)}"
        log_error(e, "Configuration API")
        return JSONResponse(content={"error": error_msg}, status_code=500)
    except Exception as e:
        error_msg = f"Erreur lors de la génération: {str(e)}"
        log_error(e, "Génération réponse")
        return JSONResponse(content={"error": error_msg}, status_code=500)


# ===================== RECOMMANDATIONS =====================

async def course_recommendation(
    grade: Optional[str] = Query(None),
    subject: Optional[str] = Query(None)
):
    return JSONResponse(content={
        "response": f"Recommandations pour {grade or 'niveau'} en {subject or 'matière'}."
    })