from app.core.routing import APIRouter
from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.security import require
from app.data.database import get_db
from app.modules.recruiting.models import Application, Requisition
from app.modules.offers.models import Offer
from app.modules.workforce.models import Employment
from app.modules.hr_service.models import HRCase

router = APIRouter(prefix="/reports", tags=["reports"])


def counts(db, model, customer_id):
    return dict(db.execute(select(model.status, func.count(model.id)).where(model.customer_id == customer_id).group_by(model.status)).all())


@router.get("/rms")
def rms_report(user=Depends(require("recruiter", module="rms")), db: Session = Depends(get_db)):
    return {"requisitions": counts(db, Requisition, user.customer_id),
            "applications": counts(db, Application, user.customer_id), "offers": counts(db, Offer, user.customer_id)}


@router.get("/hrms")
def hrms_report(user=Depends(require("hr", module="hrms")), db: Session = Depends(get_db)):
    return {"employments": counts(db, Employment, user.customer_id), "hr_cases": counts(db, HRCase, user.customer_id)}
