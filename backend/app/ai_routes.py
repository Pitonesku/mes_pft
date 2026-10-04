"""
AI Analysis API Router

Provides admin-only endpoints for AI-powered production data analysis.

Integration: add to main.py —
    from production_api import ai_routes
    app.include_router(ai_routes.router, prefix="/api")
"""
import importlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

if __package__:
    models = importlib.import_module(f"{__package__}.models")
    schemas = importlib.import_module(f"{__package__}.schemas")
    database_mod = importlib.import_module(f"{__package__}.database")
    get_db = database_mod.get_db
    ai_svc = importlib.import_module(f"{__package__}.ai_service")
    auth_module = importlib.import_module(f"{__package__}.auth")
    get_current_user = auth_module.get_current_user
else:
    import models
    import schemas
    from database import get_db
    import ai_service as ai_svc
    from auth import get_current_user

router = APIRouter(prefix="/ai", tags=["AI Analysis"])


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_admin(db: Session, user_id: Optional[int]) -> models.User:
    """
    Verify the requesting user exists, is active, and has admin privileges
    (can_manage_users=True or role_name='admin').

    The user identity is taken from the bearer token issued at login and
    resolved by the shared get_current_user dependency.
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.is_inactive == False)
        .first()
    )

    if not user or not user.role:
        raise HTTPException(status_code=403, detail="Access denied")

    # Super admin always has access; other users need can_use_ai or admin role
    is_super_admin = user.role.role_name.lower() == "superadmin"
    has_admin_role = user.role.role_name.lower() == "admin"
    if not (is_super_admin or has_admin_role or user.can_use_ai):
        raise HTTPException(status_code=403, detail="AI access not granted for this user")

    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=schemas.AIAnalysisResponse)
async def analyze(
    request: schemas.AIAnalysisRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Submit a natural-language question about production data to the AI.

    The server builds an aggregated DB context, optionally loads recent
    conversation turns for multi-turn support, calls the AI API, persists
    the exchange to ai_analysis_log, and returns the answer.
    """
    user = _require_admin(db, current_user.id)

    db_context = ai_svc.build_db_context(db, days=request.context_days)

    # Load prior turns of this session for multi-turn conversation support
    conversation_history: list[dict] = []
    if request.session_id:
        prior = (
            db.query(models.AIAnalysisLog)
            .filter(models.AIAnalysisLog.session_id == request.session_id)
            .order_by(models.AIAnalysisLog.created_at)
            .limit(6)
            .all()
        )
        for entry in prior:
            conversation_history.append({"role": "user", "content": entry.question})
            if entry.answer:
                conversation_history.append(
                    {"role": "assistant", "content": entry.answer}
                )

    try:
        answer = await ai_svc.query_ai(
            question=request.question,
            db_context=db_context,
            conversation_history=conversation_history,
        )
    except ValueError as exc:
        # AI API returned an error (e.g., invalid key, rate limiting, no credits)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        # Catch httpx.TimeoutException, httpx.ConnectError, etc.
        error_type = type(exc).__name__
        error_msg = str(exc)
        print(f"[AI Routes] Unexpected error in /ai/analyze: {error_type}: {error_msg}")
        raise HTTPException(
            status_code=502,
            detail=f"AI service error ({error_type}): {error_msg}",
        )

    log_entry = models.AIAnalysisLog(
        user_id=user.id,
        username=user.username,
        session_id=request.session_id,
        question=request.question,
        answer=answer,
        context_snapshot=db_context[:2000],
        source=request.source or "web",
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)

    return schemas.AIAnalysisResponse(
        id=log_entry.id,
        question=request.question,
        answer=answer,
        session_id=request.session_id,
        created_at=log_entry.created_at,
    )


@router.get("/validate")
async def validate_ai(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Validate the configured AI API key by sending a minimal test request.
    Admin authentication required.
    """
    _require_admin(db, current_user.id)
    return await ai_svc.validate_api_key()


@router.get("/models")
async def list_ai_models(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Fetch the list of available AI models from the configured provider.
    Admin authentication required.
    """
    _require_admin(db, current_user.id)
    return await ai_svc.fetch_available_models()


@router.post("/model")
def set_ai_model(payload: dict, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Override the AI model at runtime (in-memory only, cleared on server restart).
    Accepts {"model": "claude-3-haiku-20240307"} or {"model": null} to clear.
    Admin authentication required.
    """
    _require_admin(db, current_user.id)
    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise HTTPException(status_code=422, detail="'model' must be a string or null")
    ai_svc.set_model_override(model)
    current = ai_svc.get_model_override() or "(using env AI_MODEL)"
    return {"status": "ok", "model_override": ai_svc.get_model_override(), "effective_model": current}


@router.get("/history", response_model=list[schemas.AIAnalysisHistoryItem])
def get_history(
    limit: int = 50,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Retrieve AI analysis history (admin only).

    Filter by session_id to get the turns of a specific conversation.
    """
    _require_admin(db, current_user.id)

    query = db.query(models.AIAnalysisLog)
    if session_id:
        query = query.filter(models.AIAnalysisLog.session_id == session_id)

    entries = (
        query.order_by(models.AIAnalysisLog.created_at.desc()).limit(limit).all()
    )

    return [
        schemas.AIAnalysisHistoryItem(
            id=e.id,
            username=e.username,
            question=e.question,
            answer=e.answer,
            source=e.source,
            session_id=e.session_id,
            created_at=e.created_at,
        )
        for e in entries
    ]
