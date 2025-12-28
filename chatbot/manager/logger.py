# manager/logger.py
import traceback
from typing import Optional

def log_question(question: str, context: Optional[str] = None):
    """Log une question reçue"""
    print(f"🔍 Question: {question}")
    if context:
        print(f"📝 Contexte: {context}")

def log_success(message: str = "Réponse générée avec succès"):
    """Log un succès"""
    print(f"✅ {message}")

def log_error(error: Exception, context: str = ""):
    """Log une erreur avec traceback"""
    error_msg = str(error)
    if context:
        print(f"❌ {context}: {error_msg}")
    else:
        print(f"❌ Erreur: {error_msg}")
    traceback.print_exc()

def log_info(message: str, emoji: str = "ℹ️"):
    """Log une information générale"""
    print(f"{emoji} {message}")