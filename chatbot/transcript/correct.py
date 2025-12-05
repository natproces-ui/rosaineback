from fastapi import Query
from fastapi.responses import JSONResponse
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration du modèle
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("GOOGLE_API_KEY manquante dans le fichier .env")

genai.configure(api_key=api_key)
# ✅ CORRECTION : Utiliser le nom complet du modèle
model = genai.GenerativeModel("models/gemini-2.5-flash")


async def get_youtube_transcript(
    video_id: str = Query(..., description="YouTube video ID"),
    clean_math: bool = Query(True, description="Utiliser le LLM pour corriger et formater les notations mathematiques")
):
    """
    Récupère la transcription YouTube et utilise le LLM pour la mise en forme et correction si activé
    """
    try:
        ytt_api = YouTubeTranscriptApi()
        
        languages = ['fr', 'fr-FR', 'fr-CA', 'en', 'en-US']
        fetched_transcript = None
        
        for lang in languages:
            try:
                fetched_transcript = ytt_api.fetch(video_id, languages=[lang])
                break
            except (NoTranscriptFound, TranscriptsDisabled):
                continue
        
        if not fetched_transcript:
            try:
                fetched_transcript = ytt_api.fetch(video_id)
            except Exception as e:
                raise NoTranscriptFound(f"Aucune transcription disponible: {str(e)}")
        
        raw_data = fetched_transcript.to_raw_data()
        formatted_transcript = []
        
        for segment in raw_data:
            text = segment['text']
            
            if clean_math:
                # Utiliser le LLM pour corriger et formater le texte
                prompt = f"""
                Tu es un expert en transcription de videos educatives en mathematiques.
                Corrige les erreurs de transcription (orthographe, ponctuation) et remplace les notations mathematiques orales par des symboles appropries.
                Exemples :
                - "au carre" -> "²"
                - "racine carree" -> "√"
                - "egal a" -> "="
                - "plus" -> "+" (seulement si operateur)
                Conserve le sens original, ne modifie pas le contenu.
                Sois concis, retourne seulement le texte corrige.
                
                Texte brut: {text}
                """
                try:
                    response = model.generate_content(prompt)
                    text = response.text.strip()
                except Exception as e:
                    # En cas d'erreur, garder le texte brut
                    pass
            
            formatted_transcript.append({
                "start": round(segment['start'], 2),
                "duration": round(segment['duration'], 2),
                "text": text
            })
        
        return JSONResponse(content={
            "success": True,
            "videoId": video_id,
            "language": fetched_transcript.language,
            "languageCode": fetched_transcript.language_code,
            "isGenerated": fetched_transcript.is_generated,
            "transcript": formatted_transcript,
            "cleaned": clean_math
        })
        
    except TranscriptsDisabled:
        return JSONResponse(
            content={"success": False, "error": "Sous-titres desactives"},
            status_code=404
        )
    except NoTranscriptFound:
        return JSONResponse(
            content={"success": False, "error": "Aucune transcription disponible"},
            status_code=404
        )
    except VideoUnavailable:
        return JSONResponse(
            content={"success": False, "error": "Video non disponible"},
            status_code=404
        )
    except Exception as e:
        print(f"Erreur: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500
        )