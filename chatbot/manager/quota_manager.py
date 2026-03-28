# manager/quota_manager.py
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
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
except Exception as e:
    print(f"❌ ERREUR lors de l'initialisation de Firestore: {e}")
    raise e

# ── Coût Gemini 2.5 Flash ($/million tokens) ──────────────────────────────────
# Input: $0.30/M  |  Output: $2.50/M
# Estimation: 2000 tokens input + 500 tokens output par requête
COST_PER_REQUEST_USD = (2000 * 0.30 + 500 * 2.50) / 1_000_000  # ~$0.00185


# ── Helpers synchrones ────────────────────────────────────────────────────────

def _get_plan_limits_sync(plan: str) -> Dict[str, int]:
    try:
        plan_doc = db.collection("plan_configs").document(plan).get()
        if not plan_doc.exists:
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
        return {"exo_assistant": 30, "video_assistant": 20, "image_upload": 10}
    if plan == "famille":
        return {"exo_assistant": 50, "video_assistant": 30, "image_upload": 20}
    return {"exo_assistant": 5, "video_assistant": 5, "image_upload": 0}


def _should_reset_quota(last_reset: Any) -> bool:
    now = datetime.now(timezone.utc)
    if hasattr(last_reset, "timestamp"):
        last_reset = datetime.fromtimestamp(last_reset.timestamp(), tz=timezone.utc)
    elif last_reset.tzinfo is None:
        last_reset = last_reset.replace(tzinfo=timezone.utc)
    return now.date() > last_reset.date()


def _save_daily_snapshot_sync(user_id: str, plan: str, usage: Dict[str, int]) -> bool:
    """
    Sauvegarde l'usage du jour dans usage_logs avant le reset.
    Structure : usage_logs/{YYYY-MM-DD}/users/{user_id}
    Et agrégat : usage_logs/{YYYY-MM-DD} (totaux par plan)
    """
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        total_requests = sum(usage.values())

        # 1. Log individuel
        db.collection("usage_logs").document(today)\
          .collection("users").document(user_id).set({
            "user_id": user_id,
            "plan": plan,
            "usage": usage,
            "total_requests": total_requests,
            "estimated_cost_usd": round(total_requests * COST_PER_REQUEST_USD, 6),
            "saved_at": firestore.SERVER_TIMESTAMP,
        })

        # 2. Agrégat du jour (increment atomique)
        day_ref = db.collection("usage_logs").document(today)
        day_ref.set({
            "date": today,
            f"plans.{plan}.total_requests": firestore.Increment(total_requests),
            f"plans.{plan}.user_count": firestore.Increment(1),
            "total_requests": firestore.Increment(total_requests),
            "total_cost_usd": firestore.Increment(
                round(total_requests * COST_PER_REQUEST_USD, 6)
            ),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)

        print(f"✅ Snapshot sauvegardé pour {user_id} - {today}")
        return True
    except Exception as e:
        print(f"❌ Erreur save_daily_snapshot: {e}")
        return False


def _check_quota_sync(user_id: str, service: str) -> Dict[str, Any]:
    try:
        quota_ref = db.collection("quotas").document(user_id)
        quota_doc = quota_ref.get()

        if not quota_doc.exists:
            print(f"⚠️ Quota non trouvé pour {user_id}, création...")
            _create_default_quota_sync(user_id)
            quota_doc = quota_ref.get()

        quota_data = quota_doc.to_dict()

        # Reset si nouveau jour UTC → sauvegarder snapshot avant
        if _should_reset_quota(quota_data["last_reset"]):
            print(f"🔄 Reset quota pour {user_id}")
            _save_daily_snapshot_sync(
                user_id,
                quota_data.get("plan", "gratuit"),
                quota_data.get("usage_today", {}),
            )
            _reset_quota_sync(user_id)
            quota_doc = quota_ref.get()
            quota_data = quota_doc.to_dict()

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
        # Fallback permissif — ne bloque pas les users en cas d'erreur Firestore
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
    try:
        db.collection("quotas").document(user_id).update({
            f"usage_today.{service}": firestore.Increment(1),
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
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
        return True
    except Exception as e:
        print(f"❌ Erreur create_default_quota_sync: {e}")
        return False


def _get_analytics_sync() -> Dict[str, Any]:
    """
    Agrège les données pour le dashboard admin :
    - Usage aujourd'hui par service et par plan
    - Top 10 users les plus consommateurs
    - Graphique 7 derniers jours
    - Coût estimé
    """
    try:
        today = datetime.now(timezone.utc).date().isoformat()

        # ── 1. Usage d'aujourd'hui depuis les quotas actifs ──
        quotas_snap = db.collection("quotas").stream()
        today_stats = {
            "exo_assistant": 0,
            "video_assistant": 0,
            "image_upload": 0,
            "total": 0,
        }
        plan_counts = {"gratuit": 0, "eleve": 0, "famille": 0}
        top_users: List[Dict] = []

        for q in quotas_snap:
            data = q.to_dict()
            usage = data.get("usage_today", {})
            plan = data.get("plan", "gratuit")
            total_req = sum(usage.values())

            today_stats["exo_assistant"] += usage.get("exo_assistant", 0)
            today_stats["video_assistant"] += usage.get("video_assistant", 0)
            today_stats["image_upload"] += usage.get("image_upload", 0)
            today_stats["total"] += total_req

            if plan in plan_counts:
                plan_counts[plan] += 1

            if total_req > 0:
                top_users.append({
                    "user_id": q.id,
                    "plan": plan,
                    "total_requests": total_req,
                    "exo_assistant": usage.get("exo_assistant", 0),
                    "video_assistant": usage.get("video_assistant", 0),
                    "image_upload": usage.get("image_upload", 0),
                    "estimated_cost_usd": round(total_req * COST_PER_REQUEST_USD, 4),
                })

        top_users.sort(key=lambda x: x["total_requests"], reverse=True)
        top_users = top_users[:10]

        # ── 2. Graphique 7 jours depuis usage_logs ──
        seven_days: List[Dict] = []
        for i in range(6, -1, -1):
            date = (datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat()
            if date == today:
                # Aujourd'hui : données en temps réel depuis quotas
                seven_days.append({
                    "date": date,
                    "total_requests": today_stats["total"],
                    "total_cost_usd": round(today_stats["total"] * COST_PER_REQUEST_USD, 4),
                    "is_today": True,
                })
            else:
                # Jours passés : depuis usage_logs
                log_doc = db.collection("usage_logs").document(date).get()
                if log_doc.exists:
                    log_data = log_doc.to_dict()
                    seven_days.append({
                        "date": date,
                        "total_requests": log_data.get("total_requests", 0),
                        "total_cost_usd": round(log_data.get("total_cost_usd", 0), 4),
                        "is_today": False,
                    })
                else:
                    seven_days.append({
                        "date": date,
                        "total_requests": 0,
                        "total_cost_usd": 0,
                        "is_today": False,
                    })

        # ── 3. Coût estimé ──
        total_cost_today = round(today_stats["total"] * COST_PER_REQUEST_USD, 4)
        # Estimation mensuelle basée sur la moyenne des 7 jours
        avg_daily = sum(d["total_requests"] for d in seven_days) / max(len(seven_days), 1)
        estimated_monthly_cost = round(avg_daily * 30 * COST_PER_REQUEST_USD, 2)

        return {
            "today": today_stats,
            "today_cost_usd": total_cost_today,
            "estimated_monthly_cost_usd": estimated_monthly_cost,
            "plan_counts": plan_counts,
            "total_users": sum(plan_counts.values()),
            "top_users": top_users,
            "seven_days": seven_days,
            "cost_per_request_usd": COST_PER_REQUEST_USD,
        }

    except Exception as e:
        print(f"❌ Erreur get_analytics_sync: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


def _update_user_plan_sync(user_id: str, new_plan: str) -> bool:
    try:
        plan_limits = _get_plan_limits_sync(new_plan)
        db.collection("quotas").document(user_id).update({
            "plan": new_plan,
            "daily_limits": plan_limits,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        # Mettre à jour aussi le doc users
        db.collection("users").document(user_id).update({
            "plan": new_plan,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        print(f"✅ Plan mis à jour pour {user_id}: {new_plan}")
        return True
    except Exception as e:
        print(f"❌ Erreur update_user_plan: {e}")
        return False


def _block_user_sync(user_id: str, blocked: bool) -> bool:
    """Bloque un user en mettant sa limite à 0 (ou la restaure)."""
    try:
        if blocked:
            db.collection("quotas").document(user_id).update({
                "daily_limits": {"exo_assistant": 0, "video_assistant": 0, "image_upload": 0},
                "blocked": True,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        else:
            # Restaurer les limites selon le plan
            quota_doc = db.collection("quotas").document(user_id).get()
            plan = quota_doc.to_dict().get("plan", "gratuit") if quota_doc.exists else "gratuit"
            plan_limits = _get_plan_limits_sync(plan)
            db.collection("quotas").document(user_id).update({
                "daily_limits": plan_limits,
                "blocked": False,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
        print(f"✅ User {user_id} {'bloqué' if blocked else 'débloqué'}")
        return True
    except Exception as e:
        print(f"❌ Erreur block_user: {e}")
        return False


# ── API publique async ────────────────────────────────────────────────────────

async def check_quota(user_id: str, service: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_check_quota_sync, user_id, service)

async def increment_quota(user_id: str, service: str) -> bool:
    return await asyncio.to_thread(_increment_quota_sync, user_id, service)

async def reset_quota(user_id: str) -> bool:
    return await asyncio.to_thread(_reset_quota_sync, user_id)

async def create_default_quota(user_id: str, plan: str = "gratuit") -> bool:
    return await asyncio.to_thread(_create_default_quota_sync, user_id, plan)

async def update_plan(user_id: str, new_plan: str) -> bool:
    return await asyncio.to_thread(_update_user_plan_sync, user_id, new_plan)

async def get_analytics() -> Dict[str, Any]:
    return await asyncio.to_thread(_get_analytics_sync)

async def block_user(user_id: str, blocked: bool = True) -> bool:
    return await asyncio.to_thread(_block_user_sync, user_id, blocked)

# Compatibilité
def get_plan_limits_from_firestore(plan: str) -> Dict[str, int]:
    return _get_plan_limits_sync(plan)

def get_quota_warning_level(percentage: float) -> str:
    if percentage < 60: return "ok"
    elif percentage < 90: return "warning"
    elif percentage < 100: return "critical"
    else: return "blocked"