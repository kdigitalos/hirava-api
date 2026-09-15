"""Transactional feedback and guarded deletion for the retained RMS pipeline."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, select

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.modules.recruiting.pipeline_api import candidate, read, write
from app.modules.recruiting.pipeline_interviews import as_dict, get_record, interview_table, parse_ids, same_owner, scoped
from app.modules.recruiting.public_intake import pipeline_table

router = APIRouter(prefix="/api", tags=["RMS feedback compatibility"])


def feedback_table(db):
    return Table("rms_feedback", MetaData(), Column("id", Integer, primary_key=True),
        Column("interviewer_name", String, key="interviewerName"), Column("date", DateTime),
        Column("time", String), Column("interview_mode", String, key="interviewMode"),
        Column("overall_rating", Integer, key="overallRating"),
        Column("final_recommendation", String, key="finalRecommendation"), Column("description", String),
        Column("interview_id", Integer, key="interviewId"), Column("candidate_id", Integer, key="candidateId"),
        Column("level", Integer), Column("job_id", Integer, key="jobId"),
        Column("created_at", DateTime, key="createdAt"), Column("updated_at", DateTime, key="updatedAt"),
        schema="public" if db.bind.dialect.name == "postgresql" else None)


class FeedbackPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interviewerName: str | None = Field(None, max_length=255)
    date: datetime | None = None
    time: str | None = Field(None, max_length=50)
    interviewMode: str | None = Field(None, max_length=100)
    overallRating: int | None = None
    finalRecommendation: str | None = Field(None, max_length=20000)
    description: str | None = Field(None, max_length=20000)
    interviewId: int | None = Field(None, gt=0)
    candidateId: int | None = Field(None, gt=0)
    level: int | None = Field(None, ge=1, le=4)
    jobId: int | None = Field(None, gt=0)


def feedback_values(body):
    values = body.model_dump(exclude_unset=True)
    if values.get("date") and values["date"].tzinfo:
        values["date"] = values["date"].astimezone(timezone.utc).replace(tzinfo=None)
    values["updatedAt"] = datetime.now(timezone.utc).replace(tzinfo=None)
    return values


@router.get("/feedback")
def feedback(id: int | None = Query(None, gt=0), interviewId: int | None = Query(None, gt=0),
             candidateId: int | None = Query(None, gt=0), jobId: int | None = Query(None, gt=0),
             user=Depends(read), db=Depends(get_db)):
    table = feedback_table(db)
    query = scoped(table, user)
    for key, value in (("id", id), ("interviewId", interviewId), ("candidateId", candidateId), ("jobId", jobId)):
        if value is not None:
            query = query.where(table.c[key] == value)
    rows = [as_dict(table, row) for row in db.execute(query.order_by(table.c.createdAt.desc())).mappings()]
    return {"data": (rows[0] if rows else {}) if id is not None else rows}


@router.post("/feedback", status_code=201)
def create_feedback(body: FeedbackPatch, user=Depends(write), db=Depends(get_db)):
    if not all((body.interviewId, body.candidateId, body.jobId, body.level)):
        raise HTTPException(422, "Select an interview, candidate, job and interview level")
    parent_table, parent = get_record(db, user, body.interviewId, lock=True)
    same_owner(body, parent, ("candidateId", "jobId"))
    _, person = candidate(db, user, body.candidateId)
    if person["job_opening_id"] != body.jobId:
        raise HTTPException(409, "Candidate does not belong to this job")
    table = feedback_table(db)
    key = f"F{body.level}"
    exists = db.execute(select(table.c.id).where(table.c.interviewId == body.interviewId, table.c.level == body.level)).first()
    if parent[key] or exists:
        raise HTTPException(409, "Feedback already exists for this interview level")
    values = feedback_values(body)
    row = db.execute(table.insert().values(**values, createdAt=values["updatedAt"]).returning(table)).mappings().one()
    created = as_dict(table, row)
    changed = db.execute(parent_table.update().where(parent_table.c.id == body.interviewId, parent_table.c[key] == parent[key])
                         .values(**{key: str(created["id"]), "updatedAt": values["updatedAt"]}))
    if changed.rowcount != 1:
        raise HTTPException(409, "Interview changed; reload and retry")
    return {"message": "Feedback created", "data": created, "result": {"count": 1}}


@router.put("/feedback")
def update_feedback(body: FeedbackPatch, id: int = Query(..., gt=0), user=Depends(write), db=Depends(get_db)):
    table = feedback_table(db)
    row = db.execute(scoped(table, user).where(table.c.id == id)).mappings().first()
    if row is None:
        raise HTTPException(404, "Feedback not found")
    existing = as_dict(table, row)
    _, parent = get_record(db, user, existing["interviewId"], lock=True)
    same_owner(body, existing, ("interviewId", "candidateId", "jobId", "level"))
    if parent.get(f"F{existing['level']}") != str(id):
        raise HTTPException(409, "Feedback has no matching interview level; reconcile before editing")
    updated = db.execute(table.update().where(table.c.id == id).values(**feedback_values(body)).returning(table)).mappings().first()
    if updated is None:
        raise HTTPException(409, "Feedback changed; reload and retry")
    return {"message": "Updated successfully", "data": as_dict(table, updated)}


@router.delete("/feedback")
def delete_feedback(ids: str, user=Depends(write), db=Depends(get_db)):
    table = feedback_table(db)
    rows = [as_dict(table, row) for row in db.execute(scoped(table, user).where(table.c.id.in_(parse_ids(ids)))).mappings()]
    if not rows:
        raise HTTPException(404, "No feedback found")
    for parent_id in sorted({row["interviewId"] for row in rows if row["interviewId"] is not None}):
        parent_table, parent = get_record(db, user, parent_id, lock=True)
        removed = {str(row["id"]) for row in rows if row["interviewId"] == parent_id}
        patch = {f"F{i}": None for i in range(1, 6) if parent[f"F{i}"] in removed}
        if patch:
            db.execute(parent_table.update().where(parent_table.c.id == parent_id).values(**patch))
    deleted = [row["id"] for row in rows]
    db.execute(table.delete().where(table.c.id.in_(deleted)))
    return {"message": "Deleted successfully", "deletedIds": deleted}


@router.delete("/interview")
def delete_interviews(ids: str, user=Depends(write), db=Depends(get_db)):
    table = interview_table(db)
    rows = db.execute(scoped(table, user).where(table.c.id.in_(parse_ids(ids))).order_by(table.c.id).with_for_update()).mappings().all()
    deleted = [row[table.c.id] for row in rows]
    if not deleted:
        raise HTTPException(404, "No interviews found")
    for child in (interview_table(db, True), feedback_table(db)):
        if db.execute(select(child.c.id).where(child.c.interviewId.in_(deleted))).first():
            raise HTTPException(409, "Remove the interview's stages and feedback before deleting it")
    db.execute(table.delete().where(table.c.id.in_(deleted)))
    return {"message": "Deleted successfully", "deletedIds": deleted}


@router.delete("/candidate")
def delete_candidates(ids: str, user=Depends(write), db=Depends(get_db)):
    from app.modules.recruiting.pipeline_api import candidates_query
    table = pipeline_table(db)
    rows = db.execute(candidates_query(table, user).where(table.c.id.in_(parse_ids(ids))).order_by(table.c.id).with_for_update()).mappings().all()
    deleted = [row["id"] for row in rows]
    if not deleted:
        raise HTTPException(404, "No candidates found")
    for child in (interview_table(db), interview_table(db, True), feedback_table(db)):
        if db.execute(select(child.c.id).where(child.c.candidateId.in_(deleted))).first():
            raise HTTPException(409, "Remove the candidate's interviews and feedback before deleting the candidate")
    db.execute(table.delete().where(table.c.id.in_(deleted)))
    return {"message": "Deleted successfully", "deletedIds": deleted}
