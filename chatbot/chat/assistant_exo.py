from fastapi import Query
from fastapi.responses import JSONResponse
from typing import Optional, List
import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration du modèle
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("GOOGLE_API_KEY manquante dans le fichier .env")

genai.configure(api_key=api_key)
model = genai.GenerativeModel("models/gemini-2.5-flash")

print("✅ Modèle Gemini configuré pour assistant exercices")


async def ai_assistant_exo(
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
    active_exercises: Optional[str] = Query(None, description="Liste JSON des exercices actifs dans la session") # ✅ NOUVEAU
):
    """
    Assistant pédagogique pour les exercices
    - Peut répondre avec ou sans contexte d'exercice
    - Maintient une conversation contextuelle
    - Guide l'élève sans donner la solution complète
    - Gère plusieurs exercices simultanément
    """
    try:
        # ✅ NOUVEAU : Contexte multi-exercices amélioré (sans IDs)
        multi_exo_context = ""
        if active_exercises:
            try:
                import json
                exercises_list = json.loads(active_exercises)
                if exercises_list and len(exercises_list) > 0:
                    multi_exo_context = f"\n📚 EXERCICES SELECTIONNES PAR L'ELEVE ({len(exercises_list)}):\n\n"
                    for ex in exercises_list:
                        exo_number = ex.get('order', '?')  # Récupérer l'ordre réel
                        multi_exo_context += f"═══ EXERCICE {exo_number} ═══\n"
                        multi_exo_context += f"Titre: {ex.get('title', 'Sans titre')}\n"
                        if ex.get('difficulty'):
                            multi_exo_context += f"Difficulté: {ex['difficulty']}\n"
                        if ex.get('tags'):
                            multi_exo_context += f"Mots-clés: {ex['tags']}\n"
                        if ex.get('statement'):
                            # Limiter la taille de l'énoncé pour le contexte
                            statement = ex['statement'][:500] + "..." if len(ex.get('statement', '')) > 500 else ex.get('statement', '')
                            multi_exo_context += f"\nÉnoncé:\n{statement}\n"
                        multi_exo_context += "\n"
                    
                    multi_exo_context += "L'élève a sélectionné ces exercices pour que tu puisses t'y référer.\n"
            except:
                pass
        
        # Construction du contexte exercice principal (celui actuellement ouvert)
        exo_context = ""
        if exo_id and exo_title:
            exo_context = f"\n📝 EXERCICE PRINCIPAL (celui d'où l'élève a ouvert l'assistant):\n"
            exo_context += f"Titre: {exo_title}\n"
            
            if exo_difficulty:
                exo_context += f"Difficulté: {exo_difficulty}\n"
            
            if exo_tags:
                exo_context += f"Mots-clés: {exo_tags}\n"
            
            if exo_statement:
                exo_context += f"\nÉnoncé complet:\n{exo_statement}\n"
            
            # Ne pas révéler la solution complète, juste mentionner qu'elle existe
            if exo_solution:
                exo_context += f"\n✅ Une solution corrigée existe pour cet exercice.\n"
        
        # Construction du contexte conversationnel
        history_context = ""
        if conversation_history:
            history_context = f"\n💬 HISTORIQUE DE LA CONVERSATION:\n{conversation_history}\n"
        
        # Construction du prompt
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
           → Si sélectionné: aide concrètement avec son énoncé
           → Si NON sélectionné: "Coche la case 🤖 sur cet exercice pour que j'y aie accès"
        
        3. Question COMPARATIVE (ex: "ces exercices sont similaires ?")
           → Compare les exercices sélectionnés
           → Montre les points communs et différences
           → Utilise les numéros: "L'Exercice 1... tandis que l'Exercice 2..."
        
        4. Question AMBIGUE (ex: "aide-moi", "je comprends pas")
           → Si 1 seul exercice sélectionné: concentre-toi dessus
           → Si plusieurs: demande de préciser OU propose de commencer par le plus simple
           → Si aucun: réponds de façon générale et suggère de cocher des exercices
        
        REGLES D'OR:
        ✅ TOUJOURS verifier si des exercices sont selectionnes
        ✅ TOUJOURS en profiter pour faire des liens concrets
        ✅ TOUJOURS guider sans donner la reponse finale
        ✅ JAMAIS reveler la solution complete
        ✅ TOUJOURS encourager et feliciter les bonnes demarches
        
        STYLE DE REPONSE:
        - Ton bienveillant et encourageant
        - Phrases courtes et precises
        - Emojis pour structurer (📝 💡 🎯 ✅ ⚠️ 1️⃣ 2️⃣)
        - Reference aux exercices selectionnes quand pertinent
        - Maximum 5-6 phrases (sauf explication complexe)
        
        EXEMPLES CONCRETS DE BONNES REPONSES:
        
        Cas 1: Question comparative avec 2 exercices sélectionnés
        Q: "Ces exercices sont similaires ?"
        R: "🎯 Oui, tes deux exercices portent sur les vecteurs dans l'espace ! 
        L'Exercice 1 'Les bases' te fait réviser les concepts fondamentaux, 
        tandis que l'Exercice 2 'Application pyramide' te fait les appliquer 
        sur un cas concret. Ils sont complémentaires : maîtrise le 1 d'abord, 
        ça t'aidera pour le 2 ! 💡"
        
        ❌ MAUVAISE réponse (ne JAMAIS faire ça):
        "L'Exercice__2 (ID: O5GvOruAD3PuKSNBiCH6) est intitulé..."
        
        Cas 2: Question générale avec exercices sélectionnés
        Q: "C'est quoi un vecteur ?"
        R: "📚 Un vecteur, c'est une flèche avec une direction et une longueur. 
        💡 Dans ton Exercice 1 'Les bases', tu as justement des vecteurs AB, CD... 
        Regarde l'énoncé, tu vois les flèches ? Voilà ce que sont les vecteurs ! 🎯"
        
        Cas 3: Question sur exercice spécifique
        Q: "Je comprends pas l'exercice 2"
        R: "📝 Dans ton Exercice 2 sur la pyramide, l'énoncé te donne une pyramide ABCDE. 
        Qu'est-ce qu'on te DEMANDE exactement ? C'est sur le parallélisme, 
        la coplanarité ou une intersection ? 💡"
        
        Cas 4: Exercice non sélectionné
        Q: "Je comprends pas l'exercice 5"
        R: "⚠️ L'exercice 5 n'est pas dans ta sélection. Coche la case 🤖 
        sur sa carte pour que j'aie accès à son énoncé et que je puisse t'aider ! 💡"
        
        QUESTION DE L'ELEVE:
        {question}
        
        Reponds maintenant en suivant ces consignes. N'oublie pas de faire reference aux exercices selectionnes quand c'est pertinent !
        """
        
        print(f"🔍 Question reçue: {question}")
        print(f"📝 Exercice principal: {exo_id or 'Aucun'}")
        print(f"📚 Exercices actifs: {active_exercises[:50] if active_exercises else 'Aucun'}...")
        print(f"📚 Niveau: {user_level or 'Non spécifié'}")
        
        response = model.generate_content(prompt)
        response_text = response.text
        
        print(f"✅ Réponse générée avec succès")
        
        return JSONResponse(content={
            "response": response_text,
            "exo_id": exo_id,
            "timestamp": "now"
        })
        
    except AttributeError as e:
        error_msg = f"Erreur de configuration de l'API: {str(e)}"
        print(f"❌ {error_msg}")
        return JSONResponse(content={"error": error_msg}, status_code=500)
    except Exception as e:
        error_msg = f"Erreur lors de la génération: {str(e)}"
        print(f"❌ {error_msg}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": error_msg}, status_code=500)
    try:
        # Construction du contexte exercice
        exo_context = ""
        if exo_id and exo_title:
            exo_context = f"\n📝 EXERCICE EN COURS:\n"
            exo_context += f"Titre: {exo_title}\n"
            
            if exo_difficulty:
                exo_context += f"Difficulté: {exo_difficulty}\n"
            
            if exo_tags:
                exo_context += f"Tags: {exo_tags}\n"
            
            if exo_statement:
                exo_context += f"\n📘 ÉNONCÉ:\n{exo_statement}\n"
            
            # Ne pas révéler la solution complète, juste mentionner qu'elle existe
            if exo_solution:
                exo_context += f"\n✅ Une solution corrigée est disponible pour cet exercice.\n"
        
        # Construction du contexte conversationnel
        history_context = ""
        if conversation_history:
            history_context = f"\n💬 HISTORIQUE DE LA CONVERSATION:\n{conversation_history}\n"
        
        # Construction du prompt
        prompt = f"""
        Tu es un assistant pedagogique specialise dans l'aide aux exercices de mathematiques pour le secondaire (programme francais).
        
        CONTEXTE DE L'ELEVE:
        Niveau: {user_level or "Non specifie"}
        Matiere: {user_subject or "Non specifie"}
        {exo_context}
        {history_context}
        
        TON ROLE PRINCIPAL:
        🎯 Aider l'eleve a COMPRENDRE et RESOUDRE par lui-meme
        
        REGLES STRICTES:
        ✅ CE QUE TU DOIS FAIRE:
        - Analyser ou l'eleve bloque dans l'exercice
        - Poser des questions pour l'orienter ("Qu'as-tu essaye ?", "Quelle formule connais-tu ?")
        - Donner des indices progressifs (pas toute la solution d'un coup)
        - Expliquer les concepts sous-jacents si necessaire
        - Feliciter les bonnes demarches
        - Corriger les erreurs avec pedagogie
        - Donner des exemples SIMILAIRES (pas l'exercice exact)
        - Faire reference a l'enonce fourni
        
        ❌ CE QUE TU NE DOIS JAMAIS FAIRE:
        - Donner la reponse finale directement
        - Faire tous les calculs a la place de l'eleve
        - Reveler la solution complete de l'exercice
        - Etre condescendant ou impatient
        
        STRUCTURE DE TA REPONSE:
        1. Reconnaître la question/difficulte de l'eleve
        2. Donner un indice ou poser une question orientante
        3. Expliquer un concept cle si necessaire
        4. Encourager l'eleve a essayer l'etape suivante
        
        STYLE:
        - Ton bienveillant et encourageant
        - Phrases courtes et claires
        - Emojis pour structurer (📝 💡 🎯 ✅ ⚠️)
        - Adapte au niveau {user_level or "secondaire"}
        - Maximum 5-6 phrases (sauf si explication complexe)
        
        EXEMPLES DE BONNES REPONSES:
        
        Question: "Je ne sais pas par ou commencer"
        Reponse: "📝 Commencons par analyser l'enonce ensemble. Quelles sont les DONNEES que tu as ? Et qu'est-ce qu'on te DEMANDE de trouver ? Une fois que tu as identifie ca, on pourra choisir la bonne methode ! 💡"
        
        Question: "Je trouve x=5 mais je ne suis pas sur"
        Reponse: "✅ Excellente demarche ! Pour verifier ton resultat, tu peux le REMPLACER dans l'equation de depart. Si les deux cotes sont egaux, c'est bon ! Essaie et dis-moi ce que tu obtiens. 🎯"
        
        Question: "C'est quoi deja le theoreme de Pythagore ?"
        Reponse: "📚 Dans un triangle RECTANGLE, le theoreme dit que: (cote oppose)² + (cote adjacent)² = (hypotenuse)². L'hypotenuse est le cote le plus long, face a l'angle droit. Tu peux identifier ces cotes dans ton exercice ? 💡"
        
        QUESTION DE L'ELEVE:
        {question}
        
        Reponds maintenant en suivant ces consignes.
        """
        
        print(f"🔍 Question reçue: {question}")
        print(f"📝 Exercice ciblé: {exo_id or 'Aucun'}")
        print(f"📚 Niveau: {user_level or 'Non spécifié'}")
        
        response = model.generate_content(prompt)
        response_text = response.text
        
        print(f"✅ Réponse générée avec succès")
        
        return JSONResponse(content={
            "response": response_text,
            "exo_id": exo_id,
            "timestamp": "now"
        })
        
    except AttributeError as e:
        error_msg = f"Erreur de configuration de l'API: {str(e)}"
        print(f"❌ {error_msg}")
        return JSONResponse(content={"error": error_msg}, status_code=500)
    except Exception as e:
        error_msg = f"Erreur lors de la génération: {str(e)}"
        print(f"❌ {error_msg}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": error_msg}, status_code=500)