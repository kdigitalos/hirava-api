"""FastAPI replacements for the retained candidate screens.

URLs and JSON keys remain compatible. Data stays in public.rms_candidate;
ownership comes from the canonical requisition, never from a supplied customer ID.
No tables or compatibility views are created or changed here.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select

from app.core.compatibility_routing import APIRouter
from app.core.models import User
from app.core.security import require
from app.data.database import get_db
from app.modules.recruiting.models import JobReference, Requisition
from app.modules.recruiting.public_intake import pipeline_table

router = APIRouter(prefix="/api", tags=["RMS pipeline compatibility"])
read = require("hr", "recruiter", module="rms")
write = require("recruiter", module="rms")


def jobs_query(user):
    return select(JobReference.id, Requisition).join(
        Requisition, Requisition.id == JobReference.requisition_id
    ).where(Requisition.customer_id == user.customer_id)


def job(db, user, alias, lock=False):
    query = jobs_query(user).where(JobReference.id == alias)
    if lock:
        query = query.with_for_update()
    result = db.execute(query).first()
    if result is None:
        raise HTTPException(404, "Job not found")
    return result[1]


def candidates_query(table, user):
    aliases = select(JobReference.id).join(Requisition).where(
        Requisition.customer_id == user.customer_id)
    return select(table).where(table.c.job_opening_id.in_(aliases))


def candidate(db, user, candidate_id, lock=False):
    table = pipeline_table(db)
    query = candidates_query(table, user).where(table.c.id == candidate_id)
    if lock:
        query = query.with_for_update()
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, "Candidate not found")
    return table, row


def serialize(row):
    aliases = {"job_opening_id": "jobOpeningId", "updated_by": "updatedBy",
               "created_at": "createdAt", "updated_at": "updatedAt"}
    return {aliases.get(key, key): value for key, value in row.items()}


def profile(row):
    fields = row["object"] if isinstance(row["object"], list) else []
    return {f.get("name"): f.get("value") for f in fields if isinstance(f, dict)}


@router.get("/candidate")
def list_candidates(id: int | None = Query(None, gt=0), user=Depends(read), db=Depends(get_db)):
    if id is not None:
        _, row = candidate(db, user, id)
        parent = job(db, user, row["job_opening_id"])
        return {"data": {**serialize(row), "hiringFlow": (parent.job_details or {}).get("hiring_flow", "")}}
    table = pipeline_table(db)
    rows = db.execute(candidates_query(table, user).order_by(table.c.created_at.desc())).mappings()
    return {"data": [serialize(row) for row in rows]}


class CandidatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jobOpeningId: int | None = Field(None, gt=0)
    object: JsonValue = None
    questions: JsonValue = None
    status: str | None = Field(None, max_length=50)
    contacted: str | None = Field(None, max_length=50)
    # Accepted for old clients; the authenticated actor is always recorded instead.
    updatedBy: str | None = None


def patch_values(body):
    names = {"jobOpeningId": "job_opening_id"}
    values = {names.get(k, k): v for k, v in body.model_dump(exclude_unset=True).items()
              if k != "updatedBy"}
    if "job_opening_id" in values and values["job_opening_id"] is None:
        raise HTTPException(422, "Select a job for this candidate")
    if values.get("contacted", "") is None:
        raise HTTPException(422, "Contact status cannot be empty")
    return values


@router.post("/candidate", status_code=201)
def create_candidate(body: CandidatePatch, user=Depends(write), db=Depends(get_db)):
    if body.jobOpeningId is None:
        raise HTTPException(422, "Select a job for this candidate")
    parent = job(db, user, body.jobOpeningId, lock=True)
    if parent.status != "published":
        raise HTTPException(409, "This job is not accepting applications")
    now = datetime.now(timezone.utc)
    values = {"object": {}, "questions": {}, "status": "", "contacted": "Not contacted",
              **patch_values(body), "updated_by": user.id, "created_at": now, "updated_at": now}
    table = pipeline_table(db)
    row = db.execute(table.insert().values(**values).returning(table)).mappings().one()
    from app.agents.tracking import activity
    activity(db, user.customer_id, user.id, "application_created", row["id"], body.jobOpeningId, after=row["status"] or "Unassessed")
    return {"message": "Candidate created", "data": serialize(row)}


@router.put("/candidate")
def update_candidate(body: CandidatePatch, id: int = Query(..., gt=0), user=Depends(write), db=Depends(get_db)):
    table, existing = candidate(db, user, id, lock=True)
    if body.jobOpeningId is not None and body.jobOpeningId != existing["job_opening_id"]:
        # Moving just the candidate would orphan interview/stage relationships.
        raise HTTPException(409, "Create an application for the other job instead of moving this candidate")
    values = {**patch_values(body), "updated_by": user.id, "updated_at": datetime.now(timezone.utc)}
    row = db.execute(table.update().where(table.c.id == id).values(**values).returning(table)).mappings().one()
    if "status" in values and (existing["status"] or "Unassessed") != (row["status"] or "Unassessed"):
        from app.agents.tracking import activity
        activity(db, user.customer_id, user.id, "stage_changed", id, row["job_opening_id"], existing["status"] or "Unassessed", row["status"] or "Unassessed")
    return {"message": "Updated successfully", "data": serialize(row)}


@router.get("/jobOpenings/candidate")
def candidates_by_job(id: int | None = Query(None, gt=0), interviewStatus: str | None = None,
                      user=Depends(read), db=Depends(get_db)):
    query = jobs_query(user).order_by(Requisition.created_at.desc())
    if id is not None:
        job(db, user, id)
        query = query.where(JobReference.id == id)
    parents = db.execute(query).all()
    table = pipeline_table(db)
    grouped = {alias: [] for alias, _ in parents}
    statuses = {s.strip().lower() for s in interviewStatus.split(",")} if interviewStatus else None
    rows = db.execute(candidates_query(table, user).where(table.c.job_opening_id.in_(grouped))
                      .order_by(table.c.created_at.desc())).mappings()
    for row in rows:
        if statuses is None or (row["status"] or "unassessed").lower() in statuses:
            grouped[row["job_opening_id"]].append(serialize(row))
    data = [{"id": alias, "jobTitle": parent.title, "location": (parent.job_details or {}).get("location", ""),
             "candidates": grouped[alias]} for alias, parent in parents]
    return {"data": data[0] if id is not None else data}


def job_summaries(db, user):
    table = pipeline_table(db)
    rows = db.execute(candidates_query(table, user).with_only_columns(table.c.job_opening_id, table.c.status)).mappings()
    counts, stages = Counter(), {}
    for row in rows:
        alias = row["job_opening_id"]
        counts[alias] += 1
        stages.setdefault(alias, Counter())[(row["status"] or "Unassessed")] += 1
    names = dict(db.execute(select(User.id, User.name).where(User.customer_id == user.customer_id)).all())
    result = []
    for alias, parent in db.execute(jobs_query(user).order_by(Requisition.created_at.desc())):
        details = parent.job_details or {}
        result.append({"id": alias, "jobId": f"job{alias:03d}", "jobTitle": parent.title,
                       "companyName": details.get("company_name", ""), "location": details.get("location", ""),
                       "recruiter": names.get(details.get("recruiter_id"), ""), "hiringFlow": details.get("hiring_flow", ""),
                       "noOfApp": counts[alias], "stages": stages.get(alias, {})})
    return result


@router.get("/candidate/jobOpenings")
def candidate_jobs(user=Depends(read), db=Depends(get_db)):
    keys = ("id", "jobId", "jobTitle", "location", "recruiter", "noOfApp")
    return {"data": [{key: row[key] for key in keys} for row in job_summaries(db, user)]}


@router.get("/jobOpenings/interview")
def interview_jobs(user=Depends(read), db=Depends(get_db)):
    keys = ("id", "jobId", "jobTitle", "companyName", "hiringFlow")
    return {"data": [{**{key: row[key] for key in keys}, "noOfInterviewApp": row["noOfApp"]}
                     for row in sorted(job_summaries(db, user), key=lambda row: row["id"])]}


@router.get("/jobOpenings/drops")
def job_dropdown(user=Depends(read), db=Depends(get_db)):
    keys = ("id", "jobId", "jobTitle", "companyName")
    return {"data": [{key: row[key] for key in keys}
                     for row in sorted(job_summaries(db, user), key=lambda row: row["id"])]}


@router.get("/candidate/count")
def candidate_counts(id: int | None = Query(None, gt=0), user=Depends(read), db=Depends(get_db)):
    if id is not None:
        job(db, user, id)
    data = [{**{k: v for k, v in row["stages"].items() if k not in {"id", "noOfApp", "extraFields"}},
             "id": row["id"], "noOfApp": row["noOfApp"]}
            for row in job_summaries(db, user) if id is None or row["id"] == id]
    return {"data": data[0] if id is not None else data}


@router.get("/candidate/candidateNames")
def candidate_names(id: int | None = Query(None, gt=0), jobOpeningId: int | None = Query(None, gt=0),
                    user=Depends(read), db=Depends(get_db)):
    table = pipeline_table(db)
    query = candidates_query(table, user)
    if id is not None:
        query = query.where(table.c.id == id)
    if jobOpeningId is not None:
        query = query.where(table.c.job_opening_id == jobOpeningId)
    data = []
    for row in db.execute(query.order_by(table.c.created_at.desc())).mappings():
        fields = profile(row)
        name = " ".join(str(fields.get(k) or "").strip() for k in ("firstName", "lastName")).strip()
        if name:
            data.append({"id": row["id"], "candidateName": name, "email": fields.get("email")})
        if len(data) == 3:
            break
    return {"data": (data[0] if data else None) if id is not None else data}


@router.get("/candidate/recent")
def recent_candidates(priority: Literal["week", "month"] | None = None, user=Depends(read), db=Depends(get_db)):
    table = pipeline_table(db)
    query = candidates_query(table, user)
    if priority:
        query = query.where(table.c.created_at >= datetime.now(timezone.utc) - timedelta(days=7 if priority == "week" else 30))
    titles = {alias: parent.title for alias, parent in db.execute(jobs_query(user))}
    data = []
    for row in db.execute(query.order_by(table.c.created_at.desc())).mappings():
        fields = profile(row)
        name = " ".join(str(fields.get(k) or "").strip() for k in ("firstName", "lastName")).strip()
        data.append({"jobTitle": titles[row["job_opening_id"]], "candidateName": name, "createdAt": row["created_at"]})
    return {"data": data}
