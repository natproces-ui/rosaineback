# manager/gemini_client.py
import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration centralisée de Gemini
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("❌ GOOGLE_API_KEY manquante dans le fichier .env")

genai.configure(api_key=api_key)

# Modèle unique partagé par tous les assistants
model = genai.GenerativeModel("models/gemini-2.5-flash")

# Modèle JSON pour l'extraction d'exercices (réponse structurée)
model_json = genai.GenerativeModel(
    model_name="models/gemini-2.5-flash",
    generation_config=genai.types.GenerationConfig(
        response_mime_type="application/json"
    )
)

print("✅ Modèle Gemini configuré (manager/gemini_client.py)")