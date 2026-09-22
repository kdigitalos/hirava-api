"""Retained interview/stage contracts, implemented against existing SQL tables."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, select

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.modules.recruiting.models import JobReference, Requisition
from app.modules.recruiting.pipeline_api import candidate, job, profile, read, write

router = APIRouter(prefix="/api", tags=["RMS interview compatibility"])
STAGES = ("S2", "S3", "S4")


def interview_table(db, schedule=False):
    # key= preserves the Prisma response keys while name= addresses existing SQL columns.
    columns = [Column("id", Integer, primary_key=True), Column("job_id", Integer, key="jobId"),
               Column("candidate_id", Integer, key="candidateId"),
               Column("interview_date", DateTime, key="interviewDate"),
               Column("interview_time", String, key="interviewTime"), Column("duration", String),
               Column("panel_members", String, key="panelMembers"),
               Column("meeting_platform", String, key="meetingPlatform"),
               Column("interview_type", String, key="interviewType"), Column("email", String),
               Column("created_at", DateTime, key="createdAt"), Column("updated_at", DateTime, key="updatedAt")]
    if schedule:
        columns.append(Column("interview_id", Integer, key="interviewId"))
    else:
        columns += [Column("company_name", String, key="companyName"),
                    Column("candidate_name", String, key="candidateName"), Column("hiring_flow", JSON, key="hiringFlow")]
        columns += [Column(key.lower(), String, key=key) for key in (*STAGES, "F1", "F2", "F3", "F4", "F5")]
    return Table("rms_interview_schedule" if schedule else "rms_interview", MetaData(), *columns,
                 schema="public" if db.bind.dialect.name == "postgresql" else None)


def scoped(table, user):
    aliases = select(JobReference.id).join(Requisition).where(Requisition.customer_id == user.customer_id)
    return select(table).where(table.c.jobId.in_(aliases))


def as_dict(table, row):
    return {column.key: row[column] for column in table.c}


def get_record(db, user, record_id, schedule=False, lock=False):
    table = interview_table(db, schedule)
    query = scoped(table, user).where(table.c.id == record_id)
    if lock:
        query = query.with_for_update()
    row = db.execute(query).first()
    if row is None:
        raise HTTPException(404, "Interview schedule not found" if schedule else "Interview not found")
    return table, as_dict(table, row._mapping)


class SlotPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jobId: int | None = Field(None, gt=0)
    candidateId: int | None = Field(None, gt=0)
    interviewDate: datetime | None = None
    interviewTime: str | None = Field(None, max_length=50)
    duration: str | None = Field(None, max_length=100)
    panelMembers: str | list[str] | None = None
    reviewer_ids: list[str] | None = Field(None, max_length=20)
    feedback_due_at: datetime | None = None
    starts_at: datetime | None = None
    meetingPlatform: str | None = Field(None, max_length=100)
    interviewType: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=2000)


class InterviewPatch(SlotPatch):
    companyName: str | None = Field(None, max_length=255)
    candidateName: str | None = Field(None, max_length=255)
    hiringFlow: JsonValue = None


class SchedulePatch(SlotPatch):
    interviewId: int | None = Field(None, gt=0)


def values(body):
    data = body.model_dump(exclude_unset=True, exclude={"reviewer_ids", "feedback_due_at", "starts_at"})
    for key in ("jobId", "candidateId", "interviewId", "interviewDate"):
        if key in data and data[key] is None:
            raise HTTPException(422, f"{key} cannot be empty")
    if "panelMembers" in data:
        value = data["panelMembers"]
        data["panelMembers"] = ",".join(value) if isinstance(value, list) else value or ""
        if len(data["panelMembers"]) > 100:
            raise HTTPException(422, "Panel members exceed the supported length")
    if data.get("interviewDate") is not None:
        date = data["interviewDate"]
        # Existing timestamp columns store UTC without timezone.
        data["interviewDate"] = date.astimezone(timezone.utc).replace(tzinfo=None) if date.tzinfo else date
    data["updatedAt"] = datetime.now(timezone.utc).replace(tzinfo=None)
    return data


def same_owner(body, existing, keys):
    for key in keys:
        if key in body.model_fields_set and getattr(body, key) != existing[key]:
            raise HTTPException(409, "An interview or schedule cannot be moved to another job or candidate")


@router.get("/interview")
def interviews(id: int | None = Query(None, gt=0), jobId: int | None = Query(None, gt=0),
               candidateId: int | None = Query(None, gt=0), user=Depends(read), db=Depends(get_db)):
    table = interview_table(db)
    query = scoped(table, user)
    for key, value in (("id", id), ("jobId", jobId), ("candidateId", candidateId)):
        if value is not None:
            query = query.where(table.c[key] == value)
    rows = [as_dict(table, row) for row in db.execute(query.order_by(table.c.createdAt.desc())).mappings()]
    if id is None:
        return {"data": rows}
    if not rows:
        return {"data": {}}
    result = rows[0]
    parent = job(db, user, result["jobId"])
    fields = {}
    if result["candidateId"]:
        try:
            _, person = candidate(db, user, result["candidateId"])
            if person["job_opening_id"] == result["jobId"]:
                fields = profile(person)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    result.update(jobTitle=parent.title, hiringFlow=(parent.job_details or {}).get("hiring_flow", ""),
                  candidateName=" ".join(str(fields.get(k) or "") for k in ("firstName", "lastName")).strip(),
                  emailId=str(fields.get("email") or ""))
    return {"data": result}


@router.post("/interview", status_code=201)
def create_interview(body: InterviewPatch, user=Depends(write), db=Depends(get_db)):
    if not body.jobId or not body.candidateId or not body.interviewDate or not body.companyName:
        raise HTTPException(422, "Select a job and candidate, enter company name and interview date")
    job(db, user, body.jobId, lock=True)
    _, person = candidate(db, user, body.candidateId, lock=True)
    if person["job_opening_id"] != body.jobId:
        raise HTTPException(409, "Candidate does not belong to this job")
    table = interview_table(db)
    if db.execute(select(table.c.id).where(table.c.jobId == body.jobId, table.c.candidateId == body.candidateId)).first():
        raise HTTPException(409, "Interview already scheduled for this candidate and job")
    data = values(body)
    row = db.execute(table.insert().values(**data, createdAt=data["updatedAt"]).returning(table)).mappings().one()
    created = as_dict(table, row)
    sync_reviewers(db, user, created, 1, body)
    _, created = get_record(db, user, created["id"])
    from app.agents.tracking import activity
    activity(db, user.customer_id, user.id, "interview_scheduled", created["candidateId"], created["jobId"])
    return {"message": "Interview created", "data": created}


@router.put("/interview")
def update_interview(body: InterviewPatch, id: int = Query(..., gt=0), user=Depends(write), db=Depends(get_db)):
    table, existing = get_record(db, user, id, lock=True)
    same_owner(body, existing, ("jobId", "candidateId"))
    row = db.execute(table.update().where(table.c.id == id).values(**values(body)).returning(table)).mappings().one()
    updated = as_dict(table, row)
    sync_reviewers(db, user, updated, 1, body)
    _, updated = get_record(db, user, id)
    return {"message": "Updated successfully", "data": updated}


@router.get("/interviewSchedule")
def schedules(id: int | None = Query(None, gt=0), jobId: int | None = Query(None, gt=0),
              interviewId: int | None = Query(None, gt=0), user=Depends(read), db=Depends(get_db)):
    table = interview_table(db, True)
    query = scoped(table, user)
    for key, value in (("id", id), ("jobId", jobId), ("interviewId", interviewId)):
        if value is not None:
            query = query.where(table.c[key] == value)
    rows = [as_dict(table, row) for row in db.execute(query.order_by(table.c.createdAt.desc())).mappings()]
    return {"data": (rows[0] if rows else {}) if id is not None else rows}


@router.post("/interviewSchedule", status_code=201)
def create_schedule(body: SchedulePatch, user=Depends(write), db=Depends(get_db)):
    if not all((body.interviewId, body.jobId, body.candidateId, body.interviewDate)):
        raise HTTPException(422, "Select an interview, job, candidate and date")
    parent_table, parent = get_record(db, user, body.interviewId, lock=True)
    same_owner(body, parent, ("jobId", "candidateId"))
    _, person = candidate(db, user, body.candidateId)
    if person["job_opening_id"] != body.jobId:
        raise HTTPException(409, "Candidate does not belong to this job")
    stage = next((key for key in STAGES if not parent[key]), None)
    if stage is None:
        raise HTTPException(409, "All interview stage slots are occupied")
    table = interview_table(db, True)
    data = values(body)
    row = db.execute(table.insert().values(**data, createdAt=data["updatedAt"]).returning(table)).mappings().one()
    created = as_dict(table, row)
    updated = db.execute(parent_table.update().where(parent_table.c.id == parent["id"], parent_table.c[stage] == parent[stage])
                         .values(**{stage: str(created["id"]), "updatedAt": data["updatedAt"]}))
    if updated.rowcount != 1:
        raise HTTPException(409, "Interview changed; reload and retry")
    sync_reviewers(db, user, {**parent, stage: str(created["id"])}, int(stage[1:]), body)
    _, created = get_record(db, user, created["id"], schedule=True)
    from app.agents.tracking import activity
    activity(db, user.customer_id, user.id, "interview_scheduled", created["candidateId"], created["jobId"])
    return {"message": "Interview Schedule created", "data": created,
            "updatedInterview": {**parent, stage: str(created["id"])}, "result": {"count": 1}}


@router.put("/interviewSchedule")
def update_schedule(body: SchedulePatch, id: int = Query(..., gt=0), user=Depends(write), db=Depends(get_db)):
    table, existing = get_record(db, user, id, schedule=True)
    _, parent = get_record(db, user, existing["interviewId"], lock=True)
    same_owner(body, existing, ("interviewId", "jobId", "candidateId"))
    if str(id) not in [parent[key] for key in STAGES]:
        raise HTTPException(409, "Schedule has no matching interview stage; reconcile before editing")
    row = db.execute(table.update().where(table.c.id == id).values(**values(body)).returning(table)).mappings().first()
    if row is None:
        raise HTTPException(409, "Schedule changed; reload and retry")
    level = next(int(key[1:]) for key in STAGES if parent[key] == str(id))
    sync_reviewers(db, user, parent, level, body)
    _, updated = get_record(db, user, id, schedule=True)
    return {"message": "Updated successfully", "data": updated}


def parse_ids(ids):
    parts = ids.split(",")
    if len(parts) > 100 or any(not part.isascii() or not part.isdecimal() or not 0 < int(part) <= 2147483647 for part in parts):
        raise HTTPException(422, "Provide at most 100 valid IDs")
    return sorted(set(map(int, parts)))


@router.delete("/interviewSchedule")
def delete_schedules(ids: str, user=Depends(write), db=Depends(get_db)):
    table = interview_table(db, True)
    rows = [as_dict(table, row) for row in db.execute(scoped(table, user).where(table.c.id.in_(parse_ids(ids)))).mappings()]
    if not rows:
        raise HTTPException(404, "No interview schedules found")
    # Always lock parents in ID order to avoid deadlocks for multi-parent deletes.
    for parent_id in sorted({row["interviewId"] for row in rows}):
        parent_table, parent = get_record(db, user, parent_id, lock=True)
        removed = {str(row["id"]) for row in rows if row["interviewId"] == parent_id}
        patch = {key: None for key in STAGES if parent[key] in removed}
        if patch:
            from app.agents.models import InterviewPanelFeedback
            references = [f"L{key[1:]}:{parent[key]}" for key in patch]
            tasks = db.scalars(select(InterviewPanelFeedback).where(
                InterviewPanelFeedback.customer_id == user.customer_id,
                InterviewPanelFeedback.interview_id == parent_id,
                InterviewPanelFeedback.slot_ref.in_(references)).with_for_update()).all()
            from app.agents.models import InterviewReservation
            from sqlalchemy import delete
            db.execute(delete(InterviewReservation).where(InterviewReservation.customer_id == user.customer_id,
                InterviewReservation.interview_id == parent_id, InterviewReservation.slot_ref.in_(references)))
            for task in tasks:
                # Preserve history but permanently detach it, even if a database reuses IDs.
                task.slot_ref = f"removed:{task.id}"
            db.execute(parent_table.update().where(parent_table.c.id == parent_id).values(**patch))
    deleted_ids = [row["id"] for row in rows]
    db.execute(table.delete().where(table.c.id.in_(deleted_ids)))
    return {"message": "Deleted successfully", "deletedIds": deleted_ids}


@router.get("/interview/levelCounts")
def level_counts(jobId: int | None = Query(None, gt=0), priority: Literal["week", "month", "year"] | None = None,
                 user=Depends(read), db=Depends(get_db)):
    table = interview_table(db)
    query = scoped(table, user)
    parent = job(db, user, jobId) if jobId is not None else None
    if jobId is not None:
        query = query.where(table.c.jobId == jobId)
    if priority:
        query = query.where(table.c.createdAt >= datetime.now(timezone.utc) - timedelta(days={"week": 7, "month": 30, "year": 365}[priority]))
    rows = [as_dict(table, row) for row in db.execute(query).mappings()]
    counts = {"totalL1": len(rows), **{f"totalL{i}": sum(row[f"S{i}"] is not None for row in rows) for i in (2, 3, 4)}}
    return {"jobId": str(jobId), "jobTitle": parent.title, "levelCounts": counts} if parent else counts


def sync_reviewers(db, user, parent, level, body):
    from app.agents.models import InterviewReservation
    from app.agents.interview_panel import slot_ref
    reservation = db.scalar(select(InterviewReservation).where(
        InterviewReservation.customer_id == user.customer_id,
        InterviewReservation.interview_id == parent["id"],
        InterviewReservation.slot_ref == slot_ref(parent, level)).limit(1))
    if reservation and body.starts_at is None and {"interviewDate", "interviewTime", "duration"} & body.model_fields_set:
        raise HTTPException(422, "Include the timezone-aware interview start when changing a reserved interview time.")
    if body.reviewer_ids is None and body.starts_at is not None:
        from app.agents.models import InterviewPanelFeedback
        from app.agents.interview_panel import slot_ref
        from app.agents.calendar_slots import reserve
        ids = db.scalars(select(InterviewPanelFeedback.reviewer_id).where(
            InterviewPanelFeedback.customer_id == user.customer_id,
            InterviewPanelFeedback.interview_id == parent["id"],
            InterviewPanelFeedback.slot_ref == slot_ref(parent, level),
            InterviewPanelFeedback.cancelled.is_(False))).all()
        if ids: reserve(db,user,parent,level,ids,body.starts_at,body.duration)
    if body.reviewer_ids is not None:
        from app.agents.interview_panel import synchronize
        synchronize(db, user, parent, level, body.reviewer_ids, body.feedback_due_at, body.starts_at, body.duration)
