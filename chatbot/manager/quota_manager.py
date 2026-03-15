# manager/quota_manager.py
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import os
import asyncio
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

# ── Initialisation Firebase Admin ──────────────────────────────────────────────
try:
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if not credentials_path:
        raise ValueError("❌ GOOGLE_APPLICATION_CREDENTIALS manquant dans .env")

    if not os.path.exists(credentials_path):
        raise FileNotFoundError(f"❌ Fichier credentials introuvable: {credentials_path}")

    if not firebase_admin._apps:
        cred = credentials.Certificate(credentials_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    print("✅ Firestore initialisé avec Firebase Admin SDK")

except ImportError as e:
    print("❌ ERREUR: firebase-admin n'est pas installé")
    raise e
except Exception as e:
    print(f"❌ ERREUR lors de l'initialisation de Firestore: {e}")
    raise e


# ── Helpers synchrones (appelés via asyncio.to_thread) ────────────────────────

def _get_plan_limits_sync(plan: str) -> Dict[str, int]:
    """Synchrone — à appeler via asyncio.to_thread uniquement."""
    try:
        plan_doc = db.collection("plan_configs").document(plan).get()
        if not plan_doc.exists:
            print(f"⚠️ Plan '{plan}' non trouvé, valeurs par défaut")
            return _default_limits(plan)
        data = plan_doc.to_dict()
        return {
            "exo_assistant": data.get("exo_assistant", 0),
            "video_assistant": data.get("video_assistant", 0),
            "image_upload": data.get("image_upload", 0),
        }
    except Exception as e:
        print(f"❌ Erreur lecture plan_configs: {e}")
        return _default_limits(plan)


def _default_limits(plan: str) -> Dict[str, int]:
    if plan == "eleve":
        return {"exo_assistant": 150, "video_assistant": 75, "image_upload": 20}
    if plan == "famille":
        return {"exo_assistant": 200, "video_assistant": 100, "image_upload": 30}
    return {"exo_assistant": 5, "video_assistant": 10, "image_upload": 0}


def _check_quota_sync(user_id: str, service: str) -> Dict[str, Any]:
    """Synchrone — à appeler via asyncio.to_thread uniquement."""
    try:
        quota_ref = db.collection("quotas").document(user_id)
        quota_doc = quota_ref.get()

        if not quota_doc.exists:
            print(f"⚠️ Quota non trouvé pour {user_id}, création...")
            _create_default_quota_sync(user_id)
            quota_doc = quota_ref.get()

        quota_data = quota_doc.to_dict()

        # Reset si nouveau jour UTC
        if _should_reset_quota(quota_data["last_reset"]):
            print(f"🔄 Reset quota pour {user_id}")
            _reset_quota_sync(user_id)
            quota_doc = quota_ref.get()
            quota_data = quota_doc.to_dict()

        # ⚡ Lire plan_limits dans le même thread (pas de to_thread imbriqué)
        plan = quota_data.get("plan", "gratuit")
        plan_limits = _get_plan_limits_sync(plan)

        limit = plan_limits.get(service, 0)
        used = quota_data.get("usage_today", {}).get(service, 0)
        remaining = max(0, limit - used)
        percentage = (used / limit * 100) if limit > 0 else 100

        return {
            "allowed": used < limit,
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "percentage": round(percentage, 1),
            "plan": plan,
        }

    except Exception as e:
        print(f"❌ Erreur check_quota_sync: {e}")
        import traceback
        traceback.print_exc()
        # ⚡ Fallback permissif : en cas d'erreur Firestore on laisse passer
        # plutôt que de bloquer tous les utilisateurs
        return {
            "allowed": True,
            "used": 0,
            "limit": 999,
            "remaining": 999,
            "percentage": 0,
            "plan": "unknown",
            "error": str(e),
        }


def _increment_quota_sync(user_id: str, service: str) -> bool:
    """Synchrone — à appeler via asyncio.to_thread uniquement."""
    try:
        quota_ref = db.collection("quotas").document(user_id)
        quota_ref.update({
            f"usage_today.{service}": firestore.Increment(1),
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        print(f"✅ Quota incrémenté pour {user_id} - {service}")
        return True
    except Exception as e:
        print(f"❌ Erreur increment_quota_sync: {e}")
        return False


def _reset_quota_sync(user_id: str) -> bool:
    try:
        db.collection("quotas").document(user_id).update({
            "usage_today": {"exo_assistant": 0, "video_assistant": 0, "image_upload": 0},
            "last_reset": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        print(f"✅ Quota réinitialisé pour {user_id}")
        return True
    except Exception as e:
        print(f"❌ Erreur reset_quota_sync: {e}")
        return False


def _create_default_quota_sync(user_id: str, plan: str = "gratuit") -> bool:
    try:
        plan_limits = _get_plan_limits_sync(plan)
        db.collection("quotas").document(user_id).set({
            "user_id": user_id,
            "plan": plan,
            "daily_limits": plan_limits,
            "usage_today": {"exo_assistant": 0, "video_assistant": 0, "image_upload": 0},
            "last_reset": firestore.SERVER_TIMESTAMP,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        print(f"✅ Quota par défaut créé pour {user_id}")
        return True
    except Exception as e:
        print(f"❌ Erreur create_default_quota_sync: {e}")
        return False


# ── API publique async ─────────────────────────────────────────────────────────

def _should_reset_quota(last_reset: datetime) -> bool:
    now = datetime.now(timezone.utc)
    if hasattr(last_reset, "timestamp"):
        last_reset = datetime.fromtimestamp(last_reset.timestamp(), tz=timezone.utc)
    elif last_reset.tzinfo is None:
        last_reset = last_reset.replace(tzinfo=timezone.utc)
    return now.date() > last_reset.date()


async def check_quota(user_id: str, service: str) -> Dict[str, Any]:
    """⚡ Async — Firestore appelé dans un thread séparé pour ne pas bloquer."""
    return await asyncio.to_thread(_check_quota_sync, user_id, service)


async def increment_quota(user_id: str, service: str) -> bool:
    """⚡ Async — Firestore appelé dans un thread séparé."""
    return await asyncio.to_thread(_increment_quota_sync, user_id, service)


async def reset_quota(user_id: str) -> bool:
    return await asyncio.to_thread(_reset_quota_sync, user_id)


async def create_default_quota(user_id: str, plan: str = "gratuit") -> bool:
    return await asyncio.to_thread(_create_default_quota_sync, user_id, plan)


async def update_plan(user_id: str, new_plan: str) -> bool:
    def _update():
        try:
            plan_limits = _get_plan_limits_sync(new_plan)
            if not plan_limits or all(v == 0 for v in plan_limits.values()):
                print(f"❌ Plan invalide ou limites à 0: {new_plan}")
                return False
            db.collection("quotas").document(user_id).update({
                "plan": new_plan,
                "daily_limits": plan_limits,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
            print(f"✅ Plan mis à jour pour {user_id}: {new_plan}")
            return True
        except Exception as e:
            print(f"❌ Erreur update_plan: {e}")
            return False

    return await asyncio.to_thread(_update)


# Gardé pour compatibilité (utilisé dans exo_assistant.py)
def get_plan_limits_from_firestore(plan: str) -> Dict[str, int]:
    return _get_plan_limits_sync(plan)


def get_quota_warning_level(percentage: float) -> str:
    if percentage < 60:
        return "ok"
    elif percentage < 90:
        return "warning"
    elif percentage < 100:
        return "critical"
    else:
        return "blocked"