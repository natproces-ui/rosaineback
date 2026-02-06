# backend/routes/assistant_exo.py
from fastapi import Query, UploadFile, File
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime
import json
import traceback
import io
import base64
from PIL import Image

# Import centralisé depuis manager
from manager import model, log_question, log_success, log_error, log_info
from manager.quota_manager import check_quota, increment_quota, get_quota_warning_level


def build_multi_exercise_context(active_exercises: Optional[str]) -> str:
    """Construit le contexte des exercices sélectionnés avec support multi-cours"""
    if not active_exercises:
        return ""
    
    try:
        exercises_list = json.loads(active_exercises)
        if not exercises_list or len(exercises_list) == 0:
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


def build_main_exercise_context(exo_id: Optional[str], exo_title: Optional[str], 
                                exo_difficulty: Optional[str], exo_tags: Optional[str],
                                exo_statement: Optional[str], exo_solution: Optional[str]) -> str:
    """Construit le contexte de l'exercice principal"""
    if not exo_id or not exo_title:
        return ""
    
    context = f"\n📝 EXERCICE PRINCIPAL (celui d'où l'élève a ouvert l'assistant):\n"
    context += f"Titre: {exo_title}\n"
    
    if exo_difficulty:
        context += f"Difficulté: {exo_difficulty}\n"
    
    if exo_tags:
        context += f"Mots-clés: {exo_tags}\n"
    
    if exo_statement:
        context += f"\nÉnoncé complet:\n{exo_statement}\n"
    
    if exo_solution:
        context += f"\n✅ Une solution corrigée existe pour cet exercice.\n"
    
    return context


def build_history_context(conversation_history: Optional[str]) -> str:
    """Construit le contexte de l'historique de conversation"""
    if not conversation_history:
        return ""
    
    return f"\n💬 HISTORIQUE DE LA CONVERSATION:\n{conversation_history}\n"


async def ai_assistant_exo(
    user_id: str = Query(..., description="ID de l'utilisateur (Firebase UID)"),
    question: str = Query(..., description="Question de l'élève"),
    user_level: Optional[str] = Query(None, description="Niveau de l'élève"),
    user_subject: Optional[str] = Query(None, description="Matière"),
    exo_id: Optional[str] = Query(None, description="ID exercice ciblé"),
    exo_title: Optional[str] = Query(None, description="Titre exercice"),
    exo_statement: Optional[str] = Query(None, description="Énoncé exercice"),
    exo_solution: Optional[str] = Query(None, description="Solution exercice"),
    exo_difficulty: Optional[str] = Query(None, description="Difficulté"),
    exo_tags: Optional[str] = Query(None, description="Tags séparés par virgules"),
    conversation_history: Optional[str] = Query(None, description="Historique JSON des messages précédents"),
    active_exercises: Optional[str] = Query(None, description="Liste JSON des exercices actifs dans la session")
):
    """
    Assistant pédagogique pour les exercices
    """
    try:
        # 🔒 Vérifier le quota
        log_info(f"Vérification quota pour user {user_id}", "🔒")
        quota_info = await check_quota(user_id, "exo_assistant")
        
        if not quota_info["allowed"]:
            log_info(f"❌ Quota dépassé pour {user_id}", "🚫")
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
                        "warning_level": warning_level
                    },
                    "upgrade_url": "/pricing",
                    "plan": quota_info["plan"]
                },
                status_code=429
            )
        
        log_question(question, f"Exercice: {exo_id or 'Aucun'} | Quota: {quota_info['used']}/{quota_info['limit']}")
        log_info(f"Exercices actifs: {active_exercises[:50] + '...' if active_exercises and len(active_exercises) > 50 else active_exercises or 'Aucun'}", "📚")
        log_info(f"Niveau: {user_level or 'Non spécifié'}", "👤")
        
        # Construction des contextes
        multi_exo_context = build_multi_exercise_context(active_exercises)
        exo_context = build_main_exercise_context(
            exo_id, exo_title, exo_difficulty, exo_tags, exo_statement, exo_solution
        )
        history_context = build_history_context(conversation_history)
        
        # ✅ PROMPT AVEC RÈGLES LATEX STRICTES
        prompt = f"""
Tu es un assistant pédagogique spécialisé dans l'aide aux exercices de mathématiques pour le secondaire (programme français).

CONTEXTE DE L'ÉLÈVE:
Niveau: {user_level or "Non spécifié"}
Matière: {user_subject or "Non spécifié"}
{multi_exo_context}
{exo_context}
{history_context}

🎯 TON RÔLE PRINCIPAL:
Aider l'élève à COMPRENDRE et RÉSOUDRE par lui-même, en t'appuyant sur les exercices qu'il a sélectionnés quand c'est pertinent.

📐 FORMATAGE MATHÉMATIQUE **OBLIGATOIRE** :

**RÈGLES STRICTES LATEX - À RESPECTER ABSOLUMENT :**

1. **Formules inline** : Utilise TOUJOURS \\( et \\) ou $ et $
   - ✅ CORRECT : "Le vecteur \\(\\vec{{i}}\\) est unitaire"
   - ✅ CORRECT : "On a $x^2 + 1 = 0$"
   - ❌ INTERDIT : "Le vecteur \\vec{{i}} est unitaire" (sans délimiteurs)
   - ❌ INTERDIT : "x^2 + 1" (sans délimiteurs)

2. **Formules display (centrées)** : Utilise \\[ et \\] ou $$ et $$
   - ✅ CORRECT : 
```
     \\[
     d : \\begin{{cases}}
     x = 1 \\\\
     y = 2 - k \\\\
     z = 4 - 3k
     \\end{{cases}}
     \\quad k \\in \\mathbb{{R}}
     \\]
```
   - ❌ INTERDIT : Système sans délimiteurs

3. **Symboles mathématiques** : TOUJOURS entre délimiteurs
   - ✅ "La limite \\(\\lim_{{x \\to 0}} \\frac{{\\sin x}}{{x}} = 1\\)"
   - ✅ "Pour tout \\(x \\in \\mathbb{{R}}\\)"
   - ❌ "La limite lim sans délimiteurs"
   - ❌ "Pour tout x ∈ R" (sans LaTeX)

4. **Ensembles** : 
   - ✅ "\\(k \\in \\mathbb{{R}}\\)"
   - ✅ "L'ensemble $\\mathbb{{N}}$ des entiers naturels"
   - ❌ "k ∈ R" (sans délimiteurs)

5. **Vecteurs** :
   - ✅ "Le vecteur \\(\\vec{{AB}}\\) ou \\(\\overrightarrow{{AB}}\\)"
   - ❌ "Le vecteur AB" (sans LaTeX)

**EXEMPLES COMPLETS DE RÉPONSES BIEN FORMATÉES :**

Question : "Comment résoudre ce système ?"
✅ BONNE réponse :
```
Pour résoudre ce système, on cherche \\(k\\) et \\(t\\) tels que :

\\[
\\begin{{cases}}
x = 1 = 2 - t \\\\
y = 2 - k = -3 + 4t \\\\
z = 4 - 3k = 1
\\end{{cases}}
\\]

De la première équation : \\(t = 1\\)

De la troisième : \\(z = 4 - 3k = 1\\) donc \\(3k = 3\\) et \\(k = 1\\).

Vérifions avec la deuxième : \\(y = 2 - 1 = 1\\) et \\(-3 + 4(1) = 1\\) ✓

Le point d'intersection est \\(A(1; 1; 1)\\).
```

❌ MAUVAISE réponse (sans délimiteurs) :
```
Pour résoudre, cherche k et t tels que x = 1 = 2 - t
De la première : t = 1
De z = 4 - 3k = 1 on a k = 1
```

Question : "C'est quoi un vecteur ?"
✅ BONNE réponse :
```
Un vecteur \\(\\vec{{u}}\\) est défini par :
- Une direction (la droite qui le porte)
- Un sens (gauche/droite, haut/bas)
- Une norme \\(\\|\\vec{{u}}\\|\\) (sa longueur)

Notation : \\(\\vec{{AB}}\\) ou \\(\\overrightarrow{{AB}}\\) pour le vecteur allant de \\(A\\) à \\(B\\).

Exemple : Si \\(A(1; 2)\\) et \\(B(4; 6)\\), alors :
\\[
\\vec{{AB}} = \\begin{{pmatrix}} 4-1 \\\\ 6-2 \\end{{pmatrix}} = \\begin{{pmatrix}} 3 \\\\ 4 \\end{{pmatrix}}
\\]
```

**MACROS LATEX DISPONIBLES** (à utiliser entre délimiteurs) :
- Vecteurs : \\vec{{AB}}, \\overrightarrow{{AB}}
- Ensembles : \\mathbb{{R}}, \\mathbb{{N}}, \\mathbb{{Z}}, \\mathbb{{Q}}, \\mathbb{{C}}
- Systèmes : \\begin{{cases}} ... \\end{{cases}}
- Fractions : \\frac{{a}}{{b}}
- Racines : \\sqrt{{x}}, \\sqrt[n]{{x}}
- Limites : \\lim_{{x \\to a}}
- Sommes : \\sum_{{i=1}}^{{n}}
- Produits : \\prod_{{i=1}}^{{n}}
- Intégrales : \\int_{{a}}^{{b}}

📚 UTILISATION DES EXERCICES SÉLECTIONNÉS:

L'élève a coché des exercices pour que tu aies accès à leur contenu.
Tu as accès à TOUS les énoncés des exercices sélectionnés ci-dessus.

✅ CE QUE TU DOIS FAIRE:
- Référer aux exercices par leur NUMÉRO (Exercice 1, Exercice 2, etc.) ou leur TITRE
- JAMAIS mentionner les IDs techniques
- T'appuyer sur les énoncés fournis pour donner des réponses concrètes
- **TOUJOURS formater les maths avec les délimiteurs LaTeX**
- Faire des liens entre les exercices sélectionnés si pertinent

🔗 EXERCICES MULTI-THÉMATIQUES (SYNTHÈSE):
- Si un exercice est marqué "MULTI-THEMATIQUES", mentionne qu'il combine plusieurs chapitres
- Suggère de maîtriser chaque notion séparément avant d'attaquer l'exercice de synthèse

❌ CE QUE TU NE DOIS JAMAIS FAIRE:
- Mentionner les IDs techniques
- Inventer des informations
- Révéler les solutions complètes
- **Écrire des formules mathématiques SANS délimiteurs LaTeX**

STYLE DE RÉPONSE:
- Ton bienveillant et encourageant
- Phrases courtes et précises
- Emojis pour structurer (📝 💡 🎯 ✅ ⚠️)
- **Toutes les formules mathématiques entre délimiteurs LaTeX**
- Maximum 5-6 phrases (sauf explication complexe)

QUESTION DE L'ÉLÈVE:
{question}

Réponds maintenant en suivant SCRUPULEUSEMENT les règles de formatage LaTeX !
CRITIQUE : N'oublie JAMAIS les délimiteurs \\( \\) ou $ $ pour TOUTES les formules !
"""
        
        # Génération de la réponse
        response = model.generate_content(prompt)
        response_text = response.text
        
        # ✅ Incrémenter le quota
        await increment_quota(user_id, "exo_assistant")
        
        new_used = quota_info["used"] + 1
        new_remaining = quota_info["limit"] - new_used
        new_percentage = round((new_used / quota_info["limit"]) * 100, 1)
        warning_level = get_quota_warning_level(new_percentage)
        
        log_success(f"Quota: {new_used}/{quota_info['limit']}")
        
        return JSONResponse(content={
            "response": response_text,
            "exo_id": exo_id,
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


async def extract_exercise_from_image(
    user_id: str = Query(..., description="ID de l'utilisateur"),
    file: UploadFile = File(...)
):
    """
    Extrait un exercice mathématique depuis une image uploadée
    """
    try:
        log_info(f"Extraction image pour user {user_id}", "📷")
        quota_info = await check_quota(user_id, "exo_assistant")
        
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
                        "warning_level": warning_level
                    }
                },
                status_code=429
            )
        
        image_data = await file.read()
        
        if len(image_data) > 5 * 1024 * 1024:
            return JSONResponse(
                content={"error": "Image trop lourde (max 5MB)"},
                status_code=400
            )
        
        image = Image.open(io.BytesIO(image_data))
        
        max_size = 2048
        if image.width > max_size or image.height > max_size:
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format=image.format or "PNG")
            image_data = buffer.getvalue()
        
        base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # ✅ PROMPT AVEC RÈGLES LATEX STRICTES
        prompt = """
Analyse cette image et extrais l'énoncé de l'exercice mathématique.

**RÈGLES STRICTES LATEX :**

1. **Formules inline** : Utilise TOUJOURS \\( et \\) 
   - Exemple : "Le vecteur \\(\\vec{i}\\) est unitaire"
   - Exemple : "Pour \\(k \\in \\mathbb{R}\\)"

2. **Formules display (centrées)** : Utilise \\[ et \\]
   - Exemple : 
```
     \\[
     d : \\begin{cases}
     x = 1 \\\\
     y = 2 - k \\\\
     z = 4 - 3k
     \\end{cases}
     \\quad k \\in \\mathbb{R}
     \\]
```

3. **Structure** : Titre, Énoncé avec LaTeX, Questions numérotées

4. **Si image floue** : signale-le dans "warning"

**FORMAT JSON OBLIGATOIRE :**
{
  "success": true/false,
  "title": "Titre de l'exercice",
  "statement": "Énoncé avec \\\\(formules\\\\) LaTeX correctement délimitées",
  "questions": ["Question 1 avec \\\\(x^2\\\\)...", "Question 2..."],
  "difficulty": "facile/moyen/difficile",
  "tags": ["tag1", "tag2"],
  "warning": "Message si problème"
}

**EXEMPLE CORRECT :**
{
  "success": true,
  "title": "Vecteurs et droites dans l'espace",
  "statement": "On considère les droites \\\\(d\\\\) et \\\\(d'\\\\) de représentations paramétriques suivantes :\\n\\n\\\\[\\nd : \\\\begin{cases}\\nx = 1 \\\\\\\\\\ny = 2 - k \\\\\\\\\\nz = 4 - 3k\\n\\\\end{cases}\\n\\\\quad k \\\\in \\\\mathbb{R}\\n\\\\]\\n\\n\\\\[\\nd' : \\\\begin{cases}\\nx = 2 - t \\\\\\\\\\ny = -3 + 4t \\\\\\\\\\nz = 1\\n\\\\end{cases}\\n\\\\quad t \\\\in \\\\mathbb{R}\\n\\\\]",
  "questions": [
    "Montrer que les droites \\\\(d\\\\) et \\\\(d'\\\\) sont sécantes en un point \\\\(A\\\\), dont on donnera les coordonnées.",
    "Justifier que le point \\\\(B(3; -7; 2)\\\\) n'appartient pas au plan défini par \\\\(d\\\\) et \\\\(d'\\\\).",
    "À tout point \\\\(M\\\\) de la droite \\\\(d'\\\\), on associe la fonction \\\\(f(t) = BM^2\\\\). Exprimer \\\\(f(t)\\\\) en fonction du paramètre \\\\(t\\\\)."
  ],
  "difficulty": "moyen",
  "tags": ["géométrie dans l'espace", "vecteurs", "droites", "paramétrage"]
}

Réponds UNIQUEMENT en JSON. N'oublie JAMAIS les délimiteurs \\( \\) et \\[ \\] !
"""
        
        response = model.generate_content([
            prompt,
            {
                "mime_type": f"image/{image.format.lower() if image.format else 'png'}",
                "data": base64_image
            }
        ])
        
        response_text = response.text.strip()
        
        if response_text.startswith("```json"):
            response_text = response_text.replace("```json", "").replace("```", "").strip()
        
        extracted = json.loads(response_text)
        
        if not extracted.get("success"):
            return JSONResponse(
                content={
                    "error": extracted.get("error", "Impossible d'extraire l'exercice"),
                    "warning": extracted.get("warning")
                },
                status_code=400
            )
        
        await increment_quota(user_id, "exo_assistant")
        
        new_used = quota_info["used"] + 1
        new_remaining = quota_info["limit"] - new_used
        new_percentage = round((new_used / quota_info["limit"]) * 100, 1)
        warning_level = get_quota_warning_level(new_percentage)
        
        log_success(f"Exercice extrait | Quota: {new_used}/{quota_info['limit']}")
        
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
                "warning": extracted.get("warning")
            },
            "quota": {
                "used": new_used,
                "limit": quota_info["limit"],
                "remaining": new_remaining,
                "percentage": new_percentage,
                "warning_level": warning_level
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except json.JSONDecodeError as e:
        log_error(e, "Parse JSON extraction")
        return JSONResponse(
            content={"error": "Erreur lors de l'analyse de l'image"},
            status_code=500
        )
    except Exception as e:
        log_error(e, "Extraction image")
        return JSONResponse(
            content={"error": f"Erreur: {str(e)}"},
            status_code=500
        )