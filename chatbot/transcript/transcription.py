# backend/transcript/transcription.py
from fastapi import APIRouter, Query
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from typing import List, Dict, Any
import re
import os
import google.generativeai as genai
from dotenv import load_dotenv

# ✅ Charger la clé API depuis .env
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    print("⚠️ GOOGLE_API_KEY non trouvée dans .env - Le formatage MathJax sera désactivé")
else:
    genai.configure(api_key=GOOGLE_API_KEY)
    print("✅ Gemini API configurée avec succès")

router = APIRouter(prefix="/transcript", tags=["Transcription"])

def clean_latex(text: str) -> str:
    if not text:
        return text
    # Nettoyage des artefacts YouTube + espaces multiples
    text = re.sub(r"\[.?Music.?\]|\[.?Applause.?\]|\[.?Laughter.?\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text

async def format_math_transcript_for_mathjax(segments: List[Dict]) -> List[Dict]:
    """
    Formate la transcription pour être compatible MathJax
    - Entoure les variables mathématiques de $...$
    - Corrige la ponctuation
    - Retire les tics de langage
    - Préserve EXACTEMENT les timestamps
    """
    
    if not GOOGLE_API_KEY:
        print("⚠️ Formatage MathJax ignoré : clé API manquante")
        return segments
    
    # Construire le contexte avec les macros MathJax disponibles
    mathjax_macros = """
    Macros MathJax disponibles dans l'application :
    - Ensembles : \\R, \\N, \\Z, \\Q, \\C, \\K
    - Vecteurs : \\vect{AB}, \\norm{v}, \\abs{x}
    - Probabilités : \\prob{A}, \\esp{X}, \\vari{X}
    - Complexes : z, \\bar{z} (conjugué), |z| (module), arg(z)
    - Et toutes les commandes LaTeX standard
    """
    
    # Construire le texte avec timestamps
    full_text = "\n".join([f"[{seg['start']}s] {seg['text']}" for seg in segments])
    
    prompt = f"""Tu es un expert en formatage de transcriptions mathématiques pour MathJax.

{mathjax_macros}

MISSION :
Transforme cette transcription YouTube d'un cours de maths en texte formaté MathJax.

RÈGLES CRITIQUES (à respecter ABSOLUMENT) :
1. GARDE EXACTEMENT le même nombre de lignes que l'original
2. GARDE les timestamps [Xs] INTACTS sur chaque ligne
3. NE modifie QUE le texte après le timestamp
4. Utilise $...$ pour les maths inline : $z$, $iZ$, $\\mathbb{{R}}$, $\\pi/4$
5. Utilise $$...$$ pour les équations : $$|Z - 2i| = 3$$
6. Corrige la ponctuation et les tics ("et bien" → ".", "euh" → supprime)
7. Garde les termes techniques exacts ("module", "argument", "affixe")
8. NE change PAS le sens mathématique

EXEMPLES DE TRANSFORMATION :

AVANT :
[5.2s] bien je sors i si dans I Z je prends I et bien il me reste Z

APRÈS :
[5.2s] Bien, je sors $i$. Si dans $iZ$ je prends $i$, il me reste $Z$.

AVANT :
[32.0s] le module de Z - 2i est égal à 3

APRÈS :
[32.0s] Le module de $Z - 2i$ est égal à $3$.

AVANT :
[90.5s] l'argument de Z est égal à pi/ 4 modulo pi

APRÈS :
[90.5s] L'argument de $Z$ est égal à $\\pi/4$ modulo $\\pi$.

AVANT :
[120.0s] i² est égal à -1

APRÈS :
[120.0s] $i^2$ est égal à $-1$.

Transcription à formater :
{full_text}

IMPORTANT : Réponds UNIQUEMENT avec la transcription formatée, ligne par ligne, SANS aucun commentaire ou texte additionnel.
"""
    
    try:
        # ✅ Utilisation de gemini-2.5-flash
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.1,  # Faible pour plus de déterminisme
                'top_p': 0.9,
            }
        )
        
        # Parser la réponse
        improved_lines = response.text.strip().split('\n')
        
        # Validation stricte
        if len(improved_lines) != len(segments):
            print(f"⚠️ Gemini a retourné {len(improved_lines)} lignes au lieu de {len(segments)}")
            print(f"Première ligne reçue : {improved_lines[0] if improved_lines else 'vide'}")
            return segments  # Fallback sur l'original
        
        # Reconstruire les segments
        improved_segments = []
        for i, line in enumerate(improved_lines):
            # Extraire le texte après [Xs]
            match = re.match(r'\[[\d.]+s\]\s*(.+)', line.strip())
            if match:
                improved_text = match.group(1).strip()
            else:
                # Si le parsing échoue, garder l'original
                print(f"⚠️ Ligne {i} mal formatée : {line}")
                improved_text = segments[i]['text']
            
            improved_segments.append({
                'start': segments[i]['start'],
                'duration': segments[i]['duration'],
                'text': improved_text
            })
        
        return improved_segments
    
    except Exception as e:
        print(f"❌ Erreur lors du formatage MathJax : {e}")
        return segments  # Fallback sur l'original


@router.get("/get_youtube_transcript")
async def get_youtube_transcript(
    video_id: str = Query(..., description="ID YouTube"),
    clean_math: bool = True,
    format_for_mathjax: bool = True
) -> Dict[str, Any]:
    """
    Récupère la transcription YouTube avec formatage MathJax optionnel
    """
    try:
        # Récupération de la transcription
        raw_segments = YouTubeTranscriptApi().fetch(
            video_id,
            languages=['fr', 'en'],
            preserve_formatting=False
        )

        segments: List[Dict[str, Any]] = []
        total_duration = 0.0

        for seg in raw_segments:
            text = seg.text
            if clean_math:
                text = clean_latex(text)

            segments.append({
                "text": text,
                "start": round(seg.start, 2),
                "duration": round(seg.duration, 2)
            })
            total_duration += seg.duration

        # ✅ Formatage MathJax si demandé
        if format_for_mathjax and GOOGLE_API_KEY:
            try:
                print(f"🔄 Formatage MathJax de {len(segments)} segments...")
                segments = await format_math_transcript_for_mathjax(segments)
                print(f"✅ Formatage MathJax terminé")
            except Exception as e:
                print(f"⚠️ Formatage MathJax échoué : {e}")
                # Continue avec la version non formatée

        return {
            "success": True,
            "video_id": video_id,
            "language": raw_segments.language_code,
            "is_generated": raw_segments.is_generated,
            "is_mathjax_formatted": format_for_mathjax and GOOGLE_API_KEY is not None,
            "segments": segments,
            "total_segments": len(segments),
            "estimated_duration_sec": round(total_duration, 2)
        }

    except NoTranscriptFound:
        return {
            "success": False,
            "error": "Aucune transcription disponible (vérifiez que les sous-titres auto sont activés sur YouTube)"
        }
    except TranscriptsDisabled:
        return {
            "success": False,
            "error": "Les sous-titres sont désactivés pour cette vidéo"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Erreur inattendue : {str(e)}"
        }


@router.get("/refresh_transcript")
async def refresh_transcript(
    video_id: str = Query(...),
    current_segments_count: int = Query(0),
    current_duration: float = Query(0)
) -> Dict[str, Any]:
    """
    Vérifie si une meilleure transcription est disponible
    """
    try:
        raw_segments = YouTubeTranscriptApi().fetch(
            video_id,
            languages=['fr', 'en'],
            preserve_formatting=False
        )

        segments = []
        total_duration = 0.0

        for seg in raw_segments:
            text = clean_latex(seg.text)
            start = round(seg.start, 2)
            duration = round(seg.duration, 2)
            segments.append({
                "text": text,
                "start": start,
                "duration": duration
            })
            total_duration += duration

        new_count = len(segments)
        
        # Décider si on met à jour
        should_update = (
            new_count > current_segments_count * 1.1 or
            abs(total_duration - current_duration) > 60
        )

        if should_update:
            return {
                "should_update": True,
                "reason": f"Nouvelle version : {new_count} segments (+{new_count - current_segments_count})",
                "new_transcript": {
                    "segments": segments,
                    "language": raw_segments.language_code if raw_segments else "unknown",
                    "is_generated": raw_segments.is_generated if raw_segments else False,
                    "total_segments": new_count,
                    "estimated_duration_sec": round(total_duration, 2)
                }
            }
        else:
            return {
                "should_update": False,
                "reason": "Transcription déjà à jour"
            }

    except Exception as e:
        return {
            "should_update": False,
            "reason": f"Erreur : {str(e)}"
        }