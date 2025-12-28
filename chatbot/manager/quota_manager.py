# manager/quota_manager.py
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Charger les variables d'environnement
load_dotenv()

# Initialisation Firebase Admin
try:
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    if not credentials_path:
        raise ValueError(
            "❌ GOOGLE_APPLICATION_CREDENTIALS manquant dans .env\n"
            "   Ajoutez: GOOGLE_APPLICATION_CREDENTIALS=config/serviceAccountKey.json"
        )
    
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"❌ Fichier credentials introuvable: {credentials_path}\n"
            f"   Téléchargez-le depuis Firebase Console → Project Settings → Service Accounts"
        )
    
    # Initialiser Firebase Admin (une seule fois)
    if not firebase_admin._apps:
        cred = credentials.Certificate(credentials_path)
        firebase_admin.initialize_app(cred)
    
    # Client Firestore
    db = firestore.client()
    print("✅ Firestore initialisé avec Firebase Admin SDK")
    
except ImportError as e:
    print("❌ ERREUR: firebase-admin n'est pas installé")
    print("   Installez-le avec: pip install firebase-admin")
    raise e
except Exception as e:
    print(f"❌ ERREUR lors de l'initialisation de Firestore: {e}")
    raise e


# ✅ Nouvelle fonction : Lire les limites depuis Firestore
def get_plan_limits_from_firestore(plan: str) -> Dict[str, int]:
    """
    Récupère les limites d'un plan depuis Firestore plan_configs
    
    Args:
        plan: Nom du plan ("gratuit", "eleve", "famille")
    
    Returns:
        Dict avec les limites (exo_assistant, video_assistant, image_upload)
    """
    try:
        plan_ref = db.collection("plan_configs").document(plan)
        plan_doc = plan_ref.get()
        
        if not plan_doc.exists:
            print(f"⚠️ Plan '{plan}' non trouvé dans plan_configs, utilisation de valeurs par défaut")
            # Valeurs par défaut de secours
            return {
                "exo_assistant": 5 if plan == "gratuit" else 150 if plan == "eleve" else 200,
                "video_assistant": 10 if plan == "gratuit" else 75 if plan == "eleve" else 100,
                "image_upload": 0 if plan == "gratuit" else 20 if plan == "eleve" else 30,
            }
        
        plan_data = plan_doc.to_dict()
        
        return {
            "exo_assistant": plan_data.get("exo_assistant", 0),
            "video_assistant": plan_data.get("video_assistant", 0),
            "image_upload": plan_data.get("image_upload", 0),
        }
        
    except Exception as e:
        print(f"❌ Erreur lecture plan_configs: {e}")
        # Retour sécurisé en cas d'erreur
        return {
            "exo_assistant": 0,
            "video_assistant": 0,
            "image_upload": 0,
        }


def _should_reset_quota(last_reset: datetime) -> bool:
    """Vérifie si le quota doit être réinitialisé (nouveau jour UTC)"""
    now = datetime.now(timezone.utc)
    
    # Gérer les timestamps Firestore
    if hasattr(last_reset, 'timestamp'):
        last_reset = datetime.fromtimestamp(last_reset.timestamp(), tz=timezone.utc)
    elif last_reset.tzinfo is None:
        last_reset = last_reset.replace(tzinfo=timezone.utc)
    
    # Nouveau jour si on a passé minuit UTC
    return now.date() > last_reset.date()


async def check_quota(user_id: str, service: str) -> Dict[str, Any]:
    """
    Vérifie si l'utilisateur a encore du quota pour le service demandé
    
    Args:
        user_id: ID de l'utilisateur
        service: "exo_assistant" | "video_assistant" | "image_upload"
    
    Returns:
        {
            "allowed": bool,
            "used": int,
            "limit": int,
            "remaining": int,
            "percentage": float,
            "plan": str
        }
    """
    try:
        # Récupérer le document quota
        quota_ref = db.collection("quotas").document(user_id)
        quota_doc = quota_ref.get()
        
        if not quota_doc.exists:
            print(f"⚠️ Quota non trouvé pour user {user_id}, création...")
            # Créer un quota par défaut si absent
            await create_default_quota(user_id)
            quota_doc = quota_ref.get()
        
        quota_data = quota_doc.to_dict()
        
        # Vérifier si besoin de reset (nouveau jour)
        if _should_reset_quota(quota_data["last_reset"]):
            print(f"🔄 Reset quota pour user {user_id}")
            await reset_quota(user_id)
            quota_doc = quota_ref.get()
            quota_data = quota_doc.to_dict()
        
        # ✅ Lire les limites depuis plan_configs (dynamique)
        plan = quota_data["plan"]
        plan_limits = get_plan_limits_from_firestore(plan)
        
        limit = plan_limits.get(service, 0)
        used = quota_data["usage_today"].get(service, 0)
        remaining = max(0, limit - used)
        percentage = (used / limit * 100) if limit > 0 else 100
        
        return {
            "allowed": used < limit,
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "percentage": round(percentage, 1),
            "plan": plan
        }
        
    except Exception as e:
        print(f"❌ Erreur check_quota: {e}")
        import traceback
        traceback.print_exc()
        # En cas d'erreur, on bloque par sécurité
        return {
            "allowed": False,
            "used": 0,
            "limit": 0,
            "remaining": 0,
            "percentage": 100,
            "plan": "unknown",
            "error": str(e)
        }


async def increment_quota(user_id: str, service: str) -> bool:
    """
    Incrémente le compteur d'usage pour un service
    
    Args:
        user_id: ID de l'utilisateur
        service: Service utilisé
    
    Returns:
        True si succès, False sinon
    """
    try:
        quota_ref = db.collection("quotas").document(user_id)
        
        # Incrémenter atomiquement avec Firebase Admin
        quota_ref.update({
            f"usage_today.{service}": firestore.Increment(1),
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        
        print(f"✅ Quota incrémenté pour {user_id} - {service}")
        return True
        
    except Exception as e:
        print(f"❌ Erreur increment_quota: {e}")
        return False


async def reset_quota(user_id: str) -> bool:
    """
    Réinitialise les quotas quotidiens d'un utilisateur
    
    Args:
        user_id: ID de l'utilisateur
    
    Returns:
        True si succès, False sinon
    """
    try:
        quota_ref = db.collection("quotas").document(user_id)
        
        quota_ref.update({
            "usage_today": {
                "exo_assistant": 0,
                "video_assistant": 0,
                "image_upload": 0,
            },
            "last_reset": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        
        print(f"✅ Quota réinitialisé pour {user_id}")
        return True
        
    except Exception as e:
        print(f"❌ Erreur reset_quota: {e}")
        return False


async def create_default_quota(user_id: str, plan: str = "gratuit") -> bool:
    """
    Crée un quota par défaut pour un utilisateur (fallback)
    
    Args:
        user_id: ID de l'utilisateur
        plan: Plan initial (par défaut "gratuit")
    
    Returns:
        True si succès, False sinon
    """
    try:
        # ✅ Lire les limites depuis plan_configs
        plan_limits = get_plan_limits_from_firestore(plan)
        
        quota_ref = db.collection("quotas").document(user_id)
        
        quota_data = {
            "user_id": user_id,
            "plan": plan,
            "daily_limits": plan_limits,
            "usage_today": {
                "exo_assistant": 0,
                "video_assistant": 0,
                "image_upload": 0,
            },
            "last_reset": firestore.SERVER_TIMESTAMP,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        
        quota_ref.set(quota_data)
        print(f"✅ Quota par défaut créé pour {user_id}")
        return True
        
    except Exception as e:
        print(f"❌ Erreur create_default_quota: {e}")
        return False


async def update_plan(user_id: str, new_plan: str) -> bool:
    """
    Met à jour le plan d'un utilisateur et ses limites
    
    Args:
        user_id: ID de l'utilisateur
        new_plan: Nouveau plan ("gratuit", "eleve", "famille")
    
    Returns:
        True si succès, False sinon
    """
    try:
        # ✅ Lire les nouvelles limites depuis plan_configs
        plan_limits = get_plan_limits_from_firestore(new_plan)
        
        if not plan_limits or all(v == 0 for v in plan_limits.values()):
            print(f"❌ Plan invalide ou limites à 0: {new_plan}")
            return False
        
        quota_ref = db.collection("quotas").document(user_id)
        
        quota_ref.update({
            "plan": new_plan,
            "daily_limits": plan_limits,
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        
        print(f"✅ Plan mis à jour pour {user_id}: {new_plan}")
        return True
        
    except Exception as e:
        print(f"❌ Erreur update_plan: {e}")
        return False


def get_quota_warning_level(percentage: float) -> str:
    """
    Retourne le niveau d'alerte selon le pourcentage de quota utilisé
    
    Args:
        percentage: Pourcentage d'utilisation (0-100)
    
    Returns:
        "ok" | "warning" | "critical" | "blocked"
    """
    if percentage < 60:
        return "ok"
    elif percentage < 90:
        return "warning"
    elif percentage < 100:
        return "critical"
    else:
        return "blocked"