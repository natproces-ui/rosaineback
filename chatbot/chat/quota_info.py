# backend/chat/quota_info.py
from fastapi import Query
from fastapi.responses import JSONResponse
from datetime import datetime

# Import centralisé depuis manager
from manager.quota_manager import check_quota


async def get_user_quotas(
    user_id: str = Query(..., description="ID de l'utilisateur (Firebase UID)")
):
    """
    Récupère les quotas pour tous les assistants d'un utilisateur
    
    Returns:
        {
            "video_assistant": {...},
            "exo_assistant": {...},
            "user_id": str,
            "timestamp": str
        }
    """
    try:
        # Récupérer les quotas pour les deux assistants
        video_quota = await check_quota(user_id, "video_assistant")
        exo_quota = await check_quota(user_id, "exo_assistant")
        
        return JSONResponse(content={
            "video_assistant": {
                "used": video_quota["used"],
                "limit": video_quota["limit"],
                "remaining": video_quota["remaining"],
                "percentage": video_quota["percentage"],
                "warning_level": video_quota.get("warning_level", "ok"),
            },
            "exo_assistant": {
                "used": exo_quota["used"],
                "limit": exo_quota["limit"],
                "remaining": exo_quota["remaining"],
                "percentage": exo_quota["percentage"],
                "warning_level": exo_quota.get("warning_level", "ok"),
            },
            "plan": video_quota.get("plan", "gratuit"),
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return JSONResponse(
            content={
                "error": f"Erreur lors de la récupération des quotas: {str(e)}"
            },
            status_code=500
        )