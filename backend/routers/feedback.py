"""User feedback endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import uuid
import logging

from database import get_db
from auth import verify_api_key
from models import Feedback, FailureEvent, APIKey
from schemas import UserFeedbackCreate, UserFeedbackResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/feedback",
    response_model=UserFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit user feedback on failure classification",
)
async def submit_feedback(
    feedback_data: UserFeedbackCreate,
    api_key: APIKey = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> UserFeedbackResponse:
    """
    Submit user validation or correction of a failure classification.

    - **event_id**: The string event ID (evt_xxx) to provide feedback on
    - **is_actual_failure**: Whether this is confirmed as an actual failure
    - **corrected_failure_type**: If different from original classification
    - **notes**: Optional user notes

    Returns feedback_id for tracking.
    """
    try:
        # Resolve event_id string to integer PK
        event_query = select(FailureEvent).where(
            FailureEvent.event_id == feedback_data.event_id
        )
        result = await db.execute(event_query)
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event {feedback_data.event_id} not found",
            )

        # Create feedback record
        feedback_id = f"fb_{uuid.uuid4().hex[:8]}"
        feedback = Feedback(
            feedback_id=feedback_id,
            event_id=event.id,  # Integer FK
            user_id=api_key.user_id,
            is_actual_failure=feedback_data.is_actual_failure,
            corrected_failure_type=feedback_data.corrected_failure_type,
            notes=feedback_data.notes,
            created_at=datetime.now(timezone.utc),
        )

        db.add(feedback)
        await db.commit()

        logger.info(
            f"Feedback submitted for event {feedback_data.event_id}",
            extra={"feedback_id": feedback_id, "event_id": feedback_data.event_id},
        )

        return UserFeedbackResponse(
            feedback_id=feedback_id,
            event_id=feedback_data.event_id,
            timestamp=datetime.now(timezone.utc),
            status="recorded",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit feedback",
        )
