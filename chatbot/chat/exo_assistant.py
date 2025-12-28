from fastapi import Query
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime
import json
import traceback

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
            
            # ✨ Nouveau : Indiquer si exercice multi-thématiques
            if ex.get('isMultiCourse'):
                courses_list = ex.get('courses', [])
                if courses_list:
                    context += f"🔗 EXERCICE MULTI-THEMATIQUES ({len(courses_list)} cours): {', '.join(courses_list)}\n"
            elif ex.get('courses') and len(ex.get('courses', [])) > 0:
                context += f"Cours: {', '.join(ex['courses'])}\n"
            
            if ex.get('tags'):
                context += f"Mots-clés: {ex['tags']}\n"
            
            if ex.get('statement'):
                # Limite augmentée à 1500 caractères
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
    - Vérifie le quota utilisateur avant de traiter
    - Maintient une conversation contextuelle
    - Guide l'élève sans donner la solution complète
    - Gère plusieurs exercices simultanément
    - Reconnaît les exercices multi-thématiques (synthèse)
    """
    try:
        # 🔒 ÉTAPE 1 : Vérifier le quota
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
        
        # 📊 Logging avec info quota
        log_question(question, f"Exercice: {exo_id or 'Aucun'} | Quota: {quota_info['used']}/{quota_info['limit']}")
        log_info(f"Exercices actifs: {active_exercises[:50] + '...' if active_exercises and len(active_exercises) > 50 else active_exercises or 'Aucun'}", "📚")
        log_info(f"Niveau: {user_level or 'Non spécifié'}", "👤")
        
        # Construction des contextes
        multi_exo_context = build_multi_exercise_context(active_exercises)
        exo_context = build_main_exercise_context(
            exo_id, exo_title, exo_difficulty, exo_tags, exo_statement, exo_solution
        )
        history_context = build_history_context(conversation_history)
        
        # Construction du prompt avec support multi-cours
        prompt = f"""
Tu es un assistant pedagogique specialise dans l'aide aux exercices de mathematiques pour le secondaire (programme francais).

CONTEXTE DE L'ELEVE:
Niveau: {user_level or "Non specifie"}
Matiere: {user_subject or "Non specifie"}
{multi_exo_context}
{exo_context}
{history_context}

🎯 TON ROLE PRINCIPAL:
Aider l'eleve a COMPRENDRE et RESOUDRE par lui-meme, en t'appuyant sur les exercices qu'il a selectionnes quand c'est pertinent.

📚 UTILISATION DES EXERCICES SELECTIONNES:

IMPORTANT: L'élève a coché des exercices pour que tu aies accès à leur contenu.
Tu as accès à TOUS les énoncés des exercices sélectionnés ci-dessus.

✅ CE QUE TU DOIS FAIRE:
- Référer aux exercices par leur NUMERO (Exercice 1, Exercice 2, etc.) ou leur TITRE
- JAMAIS mentionner les IDs techniques (comme "O5GvOruAD3PuKSNBiCH6")
- T'appuyer sur les énoncés fournis pour donner des réponses concrètes
- Faire des liens entre les exercices sélectionnés si pertinent
- Détecter si l'élève semble bloqué depuis plusieurs messages et adapter ton niveau d'aide

🔗 EXERCICES MULTI-THEMATIQUES (SYNTHESE):
- Si un exercice est marqué "MULTI-THEMATIQUES", il combine plusieurs chapitres
- Mentionne explicitement qu'il mobilise plusieurs notions quand pertinent
- Exemple: "L'Exercice 3 est un exercice de synthèse qui combine les complexes, les suites et les limites"
- Ces exercices sont souvent plus difficiles car ils demandent de faire des liens entre chapitres
- Suggère de maîtriser chaque notion séparément avant d'attaquer l'exercice de synthèse

❌ CE QUE TU NE DOIS JAMAIS FAIRE:
- Mentionner les IDs techniques
- Inventer des informations qui ne sont pas dans les énoncés
- Révéler les solutions complètes

GESTION DES QUESTIONS:

1. Question GENERALE (ex: "C'est quoi X ?")
   → Explique le concept
   → Si des exercices sont sélectionnés, fais des liens avec eux
   → Exemple: "Le théorème de Pythagore... D'ailleurs dans ton Exercice 1 'Les triangles', tu vas l'appliquer..."

2. Question sur UN exercice (ex: "l'exercice 2", "celui sur Pythagore")
   → Identifie l'exercice par son numéro ou titre
   → Si multi-thématiques, mentionne les différentes notions mobilisées
   → Exemple: "L'Exercice 3 combine les suites et les limites. Commençons par la partie suites..."
   → Si sélectionné: aide concrètement avec son énoncé
   → Si NON sélectionné: "Coche la case 🤖 sur cet exercice pour que j'y aie accès"

3. Question COMPARATIVE (ex: "ces exercices sont similaires ?")
   → Compare les exercices sélectionnés
   → Montre les points communs et différences
   → Identifie les exercices multi-thématiques qui font des liens
   → Utilise les numéros: "L'Exercice 1... tandis que l'Exercice 2..."
   → Exemple: "L'Exercice 3 est plus complexe car il combine des notions des Exercices 1 et 2"

4. Question AMBIGUE (ex: "aide-moi", "je comprends pas")
   → Si 1 seul exercice sélectionné: concentre-toi dessus
   → Si plusieurs: 
     * Demande de préciser OU propose de commencer par le plus simple
     * Si exercice multi-thématiques disponible, suggère de maîtriser d'abord les notions séparées
   → Si aucun: réponds de façon générale et suggère de cocher des exercices

5. Si l'élève semble BLOQUE sur un exercice multi-thématiques:
   → Décompose par notion/chapitre
   → Suggère de d'abord maîtriser chaque partie séparément
   → Exemple: "Cet exercice combine suites et limites. Commençons par la partie suites d'abord ?"
   → Propose des exercices plus simples s'ils sont disponibles parmi ceux sélectionnés
   → Identifie quelle notion bloque vraiment

6. Si l'élève réussit bien et a des exercices multi-thématiques disponibles:
   → Félicite et propose d'essayer l'exercice de synthèse
   → Explique qu'il va mobiliser plusieurs notions
   → Encourage: "Tu maîtrises bien X et Y, essayons l'Exercice Z qui les combine !"
   → Prépare-le mentalement: "Ce sera plus difficile car tu dois faire des liens"

7. Si l'élève demande par où commencer avec plusieurs exercices:
   → Identifie les exercices mono-thématiques vs multi-thématiques
   → Recommande de faire les mono-thématiques d'abord
   → Garde les exercices de synthèse pour la fin
   → Exemple: "Je te conseille de commencer par les Exercices 1 et 2, puis de finir par l'Exercice 3 qui est une synthèse"

REGLES D'OR:
✅ TOUJOURS verifier si des exercices sont selectionnes
✅ TOUJOURS identifier les exercices multi-thématiques
✅ TOUJOURS en profiter pour faire des liens concrets
✅ TOUJOURS guider sans donner la reponse finale
✅ JAMAIS reveler la solution complete
✅ TOUJOURS encourager et feliciter les bonnes demarches
✅ TOUJOURS suggérer de maîtriser les bases avant les exercices de synthèse

STYLE DE REPONSE:
- Ton bienveillant et encourageant
- Phrases courtes et precises
- Emojis pour structurer (📝 💡 🎯 ✅ ⚠️ 🔗 1️⃣ 2️⃣)
- Reference aux exercices selectionnes quand pertinent
- Utilise 🔗 pour les exercices multi-thématiques
- Maximum 5-6 phrases (sauf explication complexe)

QUESTION DE L'ELEVE:
{question}

Reponds maintenant en suivant ces consignes. N'oublie pas de faire reference aux exercices selectionnes et d'identifier les exercices de synthese quand c'est pertinent !
"""
        
        # Génération de la réponse
        response = model.generate_content(prompt)
        response_text = response.text
        
        # ✅ ÉTAPE 2 : Incrémenter le quota après succès
        await increment_quota(user_id, "exo_assistant")
        
        # Calculer le nouveau quota
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