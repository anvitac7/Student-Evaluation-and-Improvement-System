"""
Application router — unified application endpoints including explanation.
"""
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.deps import CurrentUser, get_current_user
from app.services.application_explanation_service import (
    ApplicationExplanationResult,
    ApplicationExplanationService,
)

router = APIRouter()


@router.get("/{application_id}/explanation", response_model=ApplicationExplanationResult)
async def get_application_explanation(
    application_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Returns unified decision explainability for an application.
    Authorized for the student owner, the drive's TPO, or an admin.
    """
    service = ApplicationExplanationService(db)
    try:
        return await service.explain_application(
            user_id=current_user.id,
            user_role=current_user.role,
            application_id=application_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
