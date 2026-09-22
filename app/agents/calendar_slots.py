"""Internal busy-time protection. No external calendar availability is inferred."""
from datetime import datetime,timedelta
from fastapi import HTTPException
from sqlalchemy import select,delete
from app.core.models import User
from app.agents.models import InterviewReservation,InterviewPanelFeedback
from app.agents.interview_panel import aware,slot_ref


def reserve(db,user,parent,level,reviewers,starts_at,duration):
    reference=slot_ref(parent,level)
    existing=db.scalars(select(InterviewReservation).where(InterviewReservation.customer_id==user.customer_id,
        InterviewReservation.interview_id==parent['id'],InterviewReservation.slot_ref==reference)).all()
    if starts_at is None:
        if not existing: return
        starts_at=aware(existing[0].starts_at)
        duration=(aware(existing[0].ends_at)-aware(starts_at)).total_seconds()/60
    if starts_at.tzinfo is None: raise HTTPException(422,'Interview start must include a timezone.')
    try: minutes=float(duration)
    except (ValueError,TypeError): raise HTTPException(422,'Enter interview duration in minutes.') from None
    if not 1<=minutes<=480: raise HTTPException(422,'Interview duration must be 1 to 480 minutes.')
    starts_at=aware(starts_at);ends_at=starts_at+timedelta(minutes=minutes)
    # Stable user locks prevent simultaneous bookings for the same panel member.
    list(db.scalars(select(User).where(User.customer_id==user.customer_id,User.id.in_(reviewers)).order_by(User.id).with_for_update()))
    conflicts=db.scalar(select(InterviewReservation).where(InterviewReservation.customer_id==user.customer_id,
        InterviewReservation.reviewer_id.in_(reviewers),InterviewReservation.starts_at<ends_at,
        InterviewReservation.ends_at>starts_at,
        ~((InterviewReservation.interview_id==parent['id'])&(InterviewReservation.slot_ref==reference))).limit(1))
    if conflicts: raise HTTPException(409,'A selected interviewer already has an overlapping Hirava interview. Choose another time or interviewer.')
    db.execute(delete(InterviewReservation).where(InterviewReservation.customer_id==user.customer_id,
        InterviewReservation.interview_id==parent['id'],InterviewReservation.slot_ref==reference))
    for reviewer_id in set(reviewers):
        db.add(InterviewReservation(customer_id=user.customer_id,interview_id=parent['id'],slot_ref=reference,
            reviewer_id=reviewer_id,starts_at=starts_at,ends_at=ends_at))
