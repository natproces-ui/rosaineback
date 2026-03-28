# chatbot/chat/exo_assistant.py

from fastapi import Query, UploadFile, File
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime
import json
import io
import base64
from PIL import Image

from manager import model, model_json, log_question, log_success, log_error, log_info
from manager.quota_manager import check_quota, increment_quota, get_quota_warning_level
from chat.json_utils import safe_json_loads
from chat.exo_prompts import build_assistant_prompt, EXTRACTION_PROMPT


# ─── HELPERS CONTEXTE ──────────────────────────────────────────────────────────

def build_multi_exercise_context(active_exercises: Optional[str]) -> str:
    if not active_exercises:
        return ""
    try:
        exercises_list = json.loads(active_exercises)
        if not exercises_list:
            return ""

        context = f"\n📚 EXERCICES SELECTIONNES PAR L'ELEVE ({len(exercises_list)}):\n\n"
        for ex in exercises_list:
            exo_number = ex.get('order', '?')
            context += f"═══ EXERCICE {exo_number} ═══\n"
            context += f"Titre: {ex.get('title', 'Sans titre')}\n"
            if ex.get('difficulty'):
                context += f"Difficulté: {ex['difficulty']}\n"
            if ex.get('isMultiCourse'):
                courses_list = ex.get('courses', [])
                if courses_list:
                    context += f"🔗 EXERCICE MULTI-THEMATIQUES ({len(courses_list)} cours): {', '.join(courses_list)}\n"
            elif ex.get('courses') and len(ex.get('courses', [])) > 0:
                context += f"Cours: {', '.join(ex['courses'])}\n"
            if ex.get('tags'):
                context += f"Mots-clés: {ex['tags']}\n"
            if ex.get('statement'):
                statement = ex['statement']
                if len(statement) > 1500:
                    statement = statement[:1500] + "..."
                context += f"\nÉnoncé:\n{statement}\n"
            context += "\n"

        context += "L'élève a sélectionné ces exercices pour que tu puisses t'y référer.\n"
        return context

    except json.JSONDecodeError as e:
        log_error(e, "Erreur parsing active_exercises")
        return ""
    except Exception as e:
        log_error(e, "Erreur inattendue dans build_multi_exercise_context")
        return ""


def build_main_exercise_context(exo_id, exo_title, exo_difficulty, exo_tags, exo_statement, exo_solution) -> str:
    if not exo_id or not exo_title:
        return ""
    context = "\n📝 EXERCICE PRINCIPAL (celui d'où l'élève a ouvert l'assistant):\n"
    context += f"Titre: {exo_title}\n"
    if exo_difficulty:
        context += f"Difficulté: {exo_difficulty}\n"
    if exo_tags:
        context += f"Mots-clés: {exo_tags}\n"
    if exo_statement:
        context += f"\nÉnoncé complet:\n{exo_statement}\n"
    if exo_solution:
        context += "\n✅ Une solution corrigée existe pour cet exercice.\n"
    return context


def build_history_context(conversation_history: Optional[str]) -> str:
    if not conversation_history:
        return ""
    return f"\n💬 HISTORIQUE DE LA CONVERSATION:\n{conversation_history}\n"


# ─── ROUTE : ASSISTANT EXO (questions texte) ───────────────────────────────────

async def ai_assistant_exo(
    user_id: str = Query(..., description="ID de l'utilisateur (Firebase UID)"),
    question: str = Query(..., description="Question de l'élève"),
    user_level: Optional[str] = Query(None),
    user_subject: Optional[str] = Query(None),
    exo_id: Optional[str] = Query(None),
    exo_title: Optional[str] = Query(None),
    exo_statement: Optional[str] = Query(None),
    exo_solution: Optional[str] = Query(None),
    exo_difficulty: Optional[str] = Query(None),
    exo_tags: Optional[str] = Query(None),
    conversation_history: Optional[str] = Query(None),
    active_exercises: Optional[str] = Query(None),
):
    try:
        log_info(f"Vérification quota pour user {user_id}", "🔒")
        # Questions texte → quota exo_assistant
        quota_info = await check_quota(user_id, "exo_assistant")

        if not quota_info["allowed"]:
            warning_level = get_quota_warning_level(quota_info["percentage"])
            return JSONResponse(
                content={
                    "error": "Quota quotidien dépassé",
                    "message": "Vous avez atteint votre limite de questions pour aujourd'hui.",
                    "quota": {
                        "used": quota_info["used"],
                        "limit": quota_info["limit"],
                        "remaining": quota_info["remaining"],
                        "percentage": quota_info["percentage"],
                        "warning_level": warning_level,
                    },
                    "upgrade_url": "/pricing",
                    "plan": quota_info["plan"],
                },
                status_code=429,
            )

        log_question(question, f"Exercice: {exo_id or 'Aucun'} | Quota: {quota_info['used']}/{quota_info['limit']}")
        log_info(f"Niveau: {user_level or 'Non spécifié'}", "👤")

        multi_exo_context = build_multi_exercise_context(active_exercises)
        exo_context = build_main_exercise_context(exo_id, exo_title, exo_difficulty, exo_tags, exo_statement, exo_solution)
        history_context = build_history_context(conversation_history)

        prompt = build_assistant_prompt(
            user_level, user_subject,
            multi_exo_context, exo_context, history_context,
            question
        )

        response = await model.generate_content_async(prompt)
        response_text = response.text

        # Incrémenter exo_assistant
        await increment_quota(user_id, "exo_assistant")
        new_used = quota_info["used"] + 1
        new_remaining = quota_info["limit"] - new_used
        new_percentage = round((new_used / quota_info["limit"]) * 100, 1)
        warning_level = get_quota_warning_level(new_percentage)
        log_success(f"Quota exo_assistant: {new_used}/{quota_info['limit']}")

        return JSONResponse(content={
            "response": response_text,
            "exo_id": exo_id,
            "quota": {
                "used": new_used,
                "limit": quota_info["limit"],
                "remaining": new_remaining,
                "percentage": new_percentage,
                "warning_level": warning_level,
            },
            "timestamp": datetime.now().isoformat(),
        })

    except AttributeError as e:
        log_error(e, "Configuration API")
        return JSONResponse(content={"error": f"Erreur de configuration: {str(e)}"}, status_code=500)
    except Exception as e:
        log_error(e, "Génération réponse")
        return JSONResponse(content={"error": f"Erreur: {str(e)}"}, status_code=500)


# ─── ROUTE : EXTRACTION IMAGE ──────────────────────────────────────────────────

async def extract_exercise_from_image(
    user_id: str = Query(...),
    file: UploadFile = File(...),
):
    try:
        log_info(f"Extraction image pour user {user_id}", "📷")
        # Upload image → quota image_upload
        quota_info = await check_quota(user_id, "image_upload")

        if not quota_info["allowed"]:
            warning_level = get_quota_warning_level(quota_info["percentage"])
            return JSONResponse(
                content={
                    "error": "Quota quotidien dépassé",
                    "message": "Vous avez atteint votre limite pour aujourd'hui.",
                    "quota": {
                        "used": quota_info["used"],
                        "limit": quota_info["limit"],
                        "remaining": quota_info["remaining"],
                        "percentage": quota_info["percentage"],
                        "warning_level": warning_level,
                    },
                },
                status_code=429,
            )

        image_data = await file.read()

        if len(image_data) > 5 * 1024 * 1024:
            return JSONResponse(content={"error": "Image trop lourde (max 5MB)"}, status_code=400)

        image = Image.open(io.BytesIO(image_data))

        max_size = 2048
        if image.width > max_size or image.height > max_size:
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format=image.format or "PNG")
            image_data = buffer.getvalue()

        base64_image = base64.b64encode(image_data).decode("utf-8")

        response = await model_json.generate_content_async([
            EXTRACTION_PROMPT,
            {
                "mime_type": f"image/{image.format.lower() if image.format else 'png'}",
                "data": base64_image,
            },
        ])

        extracted = safe_json_loads(response.text)

        if not extracted.get("success"):
            return JSONResponse(
                content={
                    "error": extracted.get("error", "Impossible d'extraire l'exercice"),
                    "warning": extracted.get("warning"),
                },
                status_code=400,
            )

        # Incrémenter image_upload
        await increment_quota(user_id, "image_upload")
        new_used = quota_info["used"] + 1
        new_remaining = quota_info["limit"] - new_used
        new_percentage = round((new_used / quota_info["limit"]) * 100, 1)
        warning_level = get_quota_warning_level(new_percentage)
        log_success(f"Exercice extrait | Quota image_upload: {new_used}/{quota_info['limit']}")

        return JSONResponse(content={
            "success": True,
            "exercise": {
                "id": f"photo_{int(datetime.now().timestamp() * 1000)}",
                "title": extracted.get("title", "Exercice (Photo)"),
                "statement": extracted.get("statement", ""),
                "questions": extracted.get("questions", []),
                "difficulty": extracted.get("difficulty", "moyen"),
                "tags": extracted.get("tags", []),
                "source": "photo",
                "warning": extracted.get("warning"),
            },
            "quota": {
                "used": new_used,
                "limit": quota_info["limit"],
                "remaining": new_remaining,
                "percentage": new_percentage,
                "warning_level": warning_level,
            },
            "timestamp": datetime.now().isoformat(),
        })

    except json.JSONDecodeError as e:
        log_error(e, "Parse JSON extraction")
        return JSONResponse(content={"error": "Erreur lors de l'analyse de l'image"}, status_code=500)
    except Exception as e:
        log_error(e, "Extraction image")
        return JSONResponse(content={"error": f"Erreur: {str(e)}"}, status_code=500)