"""Evidence-backed recruitment operations. No external dispatch or automatic hiring decisions."""
from collections import Counter, defaultdict
from datetime import timedelta
from difflib import SequenceMatcher
import hashlib
import json
import re
from typing import Literal
from uuid import uuid4
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select
from app.agents.models import (CandidateLink, TalentPool, TalentPoolMember, RecruitmentActivity,
    RecruitmentReport, RecruitmentSignal, InterviewPanelFeedback, ScreeningJob, RecruitmentCost)
from app.agents.recruiter_tools import Strict, staff, single_run, generate, record_usage
from app.agents.interview_panel import aware, same_slot
from app.agents.job_matching import SKILLS, contains, aliases
from app.core.models import AuditEvent, User
from app.core.compatibility_routing import APIRouter
from app.data.database import get_db, utcnow
from app.modules.recruiting.pipeline_api import candidate, candidates_query, jobs_query, profile, job
from app.modules.recruiting.pipeline_interviews import interview_table, scoped, as_dict
from app.modules.recruiting.public_intake import pipeline_table
router = APIRouter(prefix="/api/recruitment-operations", tags=["Recruitment operations"])


def audit(db, user, action, resource, details=None):
    db.add(AuditEvent(customer_id=user.customer_id, actor_id=user.id, action=action,
        resource_type="recruitment_operations", resource_id=str(resource), correlation_id=str(uuid4()), details=details or {}))


def rows(db, user):
    table = pipeline_table(db)
    data = db.execute(candidates_query(table, user).order_by(table.c.id).limit(5001)).mappings().all()
    if len(data) > 5000:
        raise HTTPException(422, "This workspace currently supports up to 5000 applications. Narrowed scans are required for larger datasets.")
    return data


def person(row):
    p = profile(row)
    return {"id": row["id"], "job_id": row["job_opening_id"],
        "name": " ".join(str(p.get(k) or "") for k in ("firstName", "lastName")).strip() or "Unnamed applicant",
        "email": str(p.get("email") or ""), "skills": str(p.get("skills") or ""),
        "status": row["status"] or "Unassessed"}


def identity(row):
    p = profile(row)
    return {"email": str(p.get("email") or "").strip().casefold(),
        "phone": re.sub(r"\D", "", str(p.get("mobile") or p.get("phone") or "")),
        "name": " ".join(str(p.get(k) or "").strip().casefold() for k in ("firstName", "lastName")).strip()}


def fingerprint(left, right):
    return hashlib.sha256(json.dumps([identity(left), identity(right)], sort_keys=True).encode()).hexdigest()


@router.get("/candidates")
def candidate_options(user=Depends(staff), db=Depends(get_db)):
    return {"data": [person(row) for row in rows(db, user)]}


@router.get("/duplicates")
def duplicates(user=Depends(staff), db=Depends(get_db)):
    data = rows(db, user)
    people = {r["id"]: r for r in data}
    identities = {key: identity(row) for key, row in people.items()}
    blocks = defaultdict(list)
    for key, value in identities.items():
        for field in ("email", "phone"):
            if value[field] and (field != "phone" or len(value[field]) >= 7):
                blocks[(field, value[field])].append(key)
        if len(value['name']) >= 5:
            blocks[("name", value['name'][:3])].append(key)
    pairs = set()
    truncated = False
    for (field, _), ids in blocks.items():
        for i, left in enumerate(ids):
            for right in ids[i+1:]:
                if field == 'name' and SequenceMatcher(None, identities[left]['name'], identities[right]['name']).ratio() < .92:
                    continue
                pairs.add(tuple(sorted((left, right))))
                if len(pairs) >= 500:
                    truncated = True
                    break
            if truncated: break
        if truncated: break
    decisions = db.scalars(select(CandidateLink).where(CandidateLink.customer_id == user.customer_id)).all()
    indexed = {(r.left_id, r.right_id): r for r in decisions if r.left_id in people and r.right_id in people}
    pairs.update(indexed)
    results = []
    for left, right in sorted(pairs):
        decision = indexed.get((left, right))
        reasons = [f"Same {field}" for field in ('email', 'phone') if identities[left][field] and identities[left][field] == identities[right][field]]
        if not reasons: reasons = ["Similar name only; identity is uncertain"]
        results.append({"left": person(people[left]), "right": person(people[right]), "reasons": reasons,
            "fingerprint": fingerprint(people[left], people[right]),
            "decision": decision.decision if decision else "unreviewed", "version": decision.version if decision else 0})
    return {"data": results, "scanned": len(data), "truncated": truncated,
        "notice": "These are possible related applications. Linking preserves every application, resume and feedback; contact or name matches alone do not prove identity."}


class LinkDecision(Strict):
    left_id: int = Field(gt=0)
    right_id: int = Field(gt=0)
    fingerprint: str = Field(min_length=64, max_length=64)
    version: int = Field(ge=0)
    decision: Literal['same_person', 'different_people', 'unreviewed']
    note: str = Field(default='', max_length=1000)


@router.put('/duplicates')
def decide_duplicate(body: LinkDecision, user=Depends(staff), db=Depends(get_db)):
    left, right = sorted((body.left_id, body.right_id))
    if left == right: raise HTTPException(422, "Choose two different applications.")
    _, one = candidate(db, user, left, lock=True)
    _, two = candidate(db, user, right, lock=True)
    if fingerprint(one, two) != body.fingerprint:
        raise HTTPException(409, "Candidate identity details changed; refresh before reviewing.")
    row = db.scalar(select(CandidateLink).where(CandidateLink.customer_id == user.customer_id,
        CandidateLink.left_id == left, CandidateLink.right_id == right).with_for_update())
    if (row.version if row else 0) != body.version:
        raise HTTPException(409, "Review changed; refresh before saving.")
    if row is None:
        row = CandidateLink(customer_id=user.customer_id, left_id=left, right_id=right,
            actor_id=user.id, decision=body.decision, note=body.note)
        db.add(row)
    else:
        row.decision, row.note, row.actor_id = body.decision, body.note, user.id
    db.flush(); audit(db, user, 'candidate.identity_reviewed', row.id, {'decision': body.decision, 'left_id': left, 'right_id': right})
    return {'saved': True, 'version': row.version}


def metric_snapshot(db, user, days):
    now = utcnow(); start = now - timedelta(days=days)
    candidates = rows(db, user)
    cohort = [r for r in candidates if r['created_at'] and start <= aware(r['created_at']) <= now]
    stages = dict(Counter(r['status'] or 'Unassessed' for r in cohort))
    activities = db.scalars(select(RecruitmentActivity).where(RecruitmentActivity.customer_id == user.customer_id,
        RecruitmentActivity.created_at >= start, RecruitmentActivity.created_at <= now)).all()
    users = db.scalars(select(User).where(User.customer_id == user.customer_id)).all()
    names = {u.id: u.name for u in users}
    by_actor = defaultdict(Counter)
    transitions = Counter()
    for event in activities:
        if event.actor_id: by_actor[event.actor_id][event.kind] += 1
        if event.kind == 'stage_changed': transitions[(event.from_stage or 'Unassessed', event.to_stage or 'Unassessed')] += 1
    jobs = list(db.execute(jobs_query(user)))
    overdue = db.scalars(select(InterviewPanelFeedback).where(InterviewPanelFeedback.customer_id == user.customer_id,
        InterviewPanelFeedback.cancelled.is_(False), InterviewPanelFeedback.submitted_at.is_(None), InterviewPanelFeedback.due_at < now)).all()
    table = interview_table(db)
    parents = {r['id']: r for r in [as_dict(table, item) for item in db.execute(scoped(table, user)).mappings()]}
    overdue_count = sum(bool(parents.get(r.interview_id) and same_slot(parents[r.interview_id], r)) for r in overdue)
    stale = [r for r in candidates if (r['status'] or 'Unassessed').casefold() == 'unassessed'
        and r['created_at'] and aware(r['created_at']) < now - timedelta(days=7)]
    by_candidate = {row['id']: row for row in candidates}
    hire_durations = []
    hired_ids = set()
    for event in activities:
        if event.kind == 'stage_changed' and (event.to_stage or '').casefold() == 'hired' and event.candidate_id not in hired_ids:
            application = by_candidate.get(event.candidate_id)
            if application and application['created_at'] and aware(event.created_at) >= aware(application['created_at']):
                hired_ids.add(event.candidate_id)
                hire_durations.append((aware(event.created_at)-aware(application['created_at'])).total_seconds()/86400)
    costs = Counter()
    allowed_jobs = {alias for alias,_ in jobs}
    for cost in db.scalars(select(RecruitmentCost).where(RecruitmentCost.customer_id == user.customer_id,
        RecruitmentCost.voided.is_(False), RecruitmentCost.incurred_at >= start, RecruitmentCost.incurred_at <= now)):
        if cost.job_id in allowed_jobs: costs[cost.currency] += cost.amount_minor
    return {'as_of': now.isoformat(), 'window_start': start.isoformat(), 'days': days,
        'applications_received': len(cohort), 'current_stages_of_cohort': stages,
        'open_jobs_now': sum(j.status == 'published' for _, j in jobs), 'overdue_feedback_now': overdue_count,
        'unassessed_over_7_days_now': len(stale),
        'recorded_transitions': [{'from': a, 'to': b, 'count': n} for (a,b),n in sorted(transitions.items())],
        'recruiter_activity': [{'user_id': key, 'name': names.get(key, 'Former user'), 'actions': dict(counts)} for key,counts in sorted(by_actor.items())],
         'recorded_hires': len(hired_ids),
        'application_to_hired_days': round(sum(hire_durations)/len(hire_durations),2) if hire_durations else None,
        'recorded_costs': dict(costs), 'cost_per_hire': None,
        'limitations': ['Stage counts describe the current state of applications received in this window, not funnel conversion rates.',
            'Activity history starts when tracking was enabled; older actions are not backfilled.',
            'Application-to-hired time uses recorded Hired transitions only, not Selected status or vacancy time-to-fill.',
            'Costs include only entered expenses, separated by currency in minor units. Cost-per-hire is not estimated from incomplete spending.',
            'Activity counts are operational facts, not employee performance ratings.']}


@router.get('/metrics')
def metrics(days: int = Query(30, ge=1, le=365), user=Depends(staff), db=Depends(get_db)):
    return metric_snapshot(db, user, days)


class ReportRequest(Strict):
    days: int = Field(default=30, ge=1, le=365)
    use_ai: bool = False
    allow_provider_processing: bool = False


@router.post('/reports')
def create_report(body: ReportRequest, request: Request, user=Depends(single_run), db=Depends(get_db)):
    snapshot = metric_snapshot(db, user, body.days)
    sections = [
        {'title': 'Hiring snapshot', 'text': f"{snapshot['applications_received']} applications were received in the last {body.days} days. There are {snapshot['open_jobs_now']} published jobs now."},
        {'title': 'Follow-up priorities', 'text': f"{snapshot['overdue_feedback_now']} interviewer responses are overdue. {snapshot['unassessed_over_7_days_now']} applications more than seven days old remain Unassessed. Review their context before taking action."},
        {'title': 'Measurement limits', 'text': ' '.join(snapshot['limitations'])}]
    if body.use_ai:
        if not body.allow_provider_processing: raise HTTPException(422, 'Confirm AI processing first.')
        # Only aggregate numbers, never candidate identities or individual employee activity.
        source = {k:v for k,v in snapshot.items() if k != 'recruiter_activity'}
        draft = generate(request.app.state.settings, 'executive-report', {'metrics': json.dumps(source)}, {})
        db.expire_all()
        if not user.active or user.role not in {'admin', 'hr', 'recruiter'}: raise HTTPException(403, 'Account access changed.')
        sections = draft['sections']
        record_usage(db, user, draft, None)
    row = RecruitmentReport(customer_id=user.customer_id, actor_id=user.id,
        title=f"Recruitment report - {body.days} days", metrics=snapshot, sections=sections)
    db.add(row); db.flush(); audit(db, user, 'recruitment.report_created', row.id, {'ai': body.use_ai})
    return report_view(row)


def report_view(row):
    return {'id': row.id, 'title': row.title, 'created_at': row.created_at, 'metrics': row.metrics, 'sections': row.sections}


@router.get('/reports')
def reports(user=Depends(staff), db=Depends(get_db)):
    return {'data': [report_view(r) for r in db.scalars(select(RecruitmentReport).where(
        RecruitmentReport.customer_id == user.customer_id).order_by(RecruitmentReport.created_at.desc()).limit(20))]}


class PoolRequest(Strict):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default='', max_length=1000)


def pool_owner(db, user, pool_id, lock=False):
    query = select(TalentPool).where(TalentPool.id == pool_id, TalentPool.customer_id == user.customer_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if not row: raise HTTPException(404, 'Talent pool not found.')
    return row


@router.post('/pools')
def create_pool(body: PoolRequest, user=Depends(staff), db=Depends(get_db)):
    row = TalentPool(customer_id=user.customer_id, actor_id=user.id, **body.model_dump())
    db.add(row); db.flush(); audit(db, user, 'talent.pool_created', row.id)
    return {'id': row.id, 'name': row.name}


@router.get('/pools')
def pools(user=Depends(staff), db=Depends(get_db)):
    candidates = {r['id']: r for r in rows(db, user)}
    result = []
    for pool in db.scalars(select(TalentPool).where(TalentPool.customer_id == user.customer_id).order_by(TalentPool.name)):
        members = []
        for member in db.scalars(select(TalentPoolMember).where(TalentPoolMember.pool_id == pool.id, TalentPoolMember.customer_id == user.customer_id)):
            if member.candidate_id in candidates:
                members.append({'id': member.id, 'candidate': person(candidates[member.candidate_id]),
                    'contact_preference': member.contact_preference, 'review_at': aware(member.review_at).isoformat(),
                    'review_due': aware(member.review_at) <= utcnow()})
        result.append({'id': pool.id, 'name': pool.name, 'description': pool.description, 'members': members})
    return {'data': result}


class MemberRequest(Strict):
    candidate_id: int = Field(gt=0)
    contact_preference: Literal['unknown', 'permitted', 'do_not_contact'] = 'unknown'
    review_in_days: int = Field(default=90, ge=1, le=365)


@router.put('/pools/{pool_id}/members')
def save_member(pool_id: str, body: MemberRequest, user=Depends(staff), db=Depends(get_db)):
    pool_owner(db, user, pool_id, True)
    candidate(db, user, body.candidate_id)
    row = db.scalar(select(TalentPoolMember).where(TalentPoolMember.pool_id == pool_id,
        TalentPoolMember.customer_id == user.customer_id, TalentPoolMember.candidate_id == body.candidate_id))
    if row is None:
        row = TalentPoolMember(customer_id=user.customer_id, pool_id=pool_id, candidate_id=body.candidate_id, actor_id=user.id)
        db.add(row)
    row.contact_preference, row.review_at = body.contact_preference, utcnow() + timedelta(days=body.review_in_days)
    db.flush(); audit(db, user, 'talent.member_reviewed', row.id, {'candidate_id': body.candidate_id, 'preference': body.contact_preference})
    return {'saved': True}


@router.delete('/pools/{pool_id}/members/{member_id}')
def remove_member(pool_id: str, member_id: str, user=Depends(staff), db=Depends(get_db)):
    pool_owner(db, user, pool_id, True)
    row = db.scalar(select(TalentPoolMember).where(TalentPoolMember.id == member_id, TalentPoolMember.pool_id == pool_id,
        TalentPoolMember.customer_id == user.customer_id))
    if not row: raise HTTPException(404, 'Membership not found.')
    db.delete(row); audit(db, user, 'talent.member_removed', member_id)
    return {'removed': True}


@router.get('/candidates/{candidate_id}/roles')
def matching_roles(candidate_id: int, user=Depends(staff), db=Depends(get_db)):
    _, row = candidate(db, user, candidate_id)
    p = profile(row)
    text = str(p.get('skills') or '')
    results = []
    for alias, role in db.execute(jobs_query(user)):
        if role.status != 'published' or alias == row['job_opening_id']: continue
        skills = (role.job_details or {}).get('required_skills') or [name for name, variants in SKILLS.items() if any(contains(role.description, term) for term in variants)]
        if not isinstance(skills, list): continue
        skills = list(dict.fromkeys(s for s in skills if isinstance(s,str) and s.strip()))
        found = [s for s in skills if any(contains(text, term) for term in aliases(s))]
        if found: results.append({'job_id': alias, 'title': role.title, 'matched': found, 'missing': [s for s in skills if s not in found]})
    return {'data': sorted(results, key=lambda r: -len(r['matched'])),
        'notice': 'Saved-skill matches to other published roles. These are evidence overlaps, not semantic suitability scores. Verify availability and preferences.'}


def scan_signals(db, user):
    # Serialize each organization's scan across workers and manual refreshes.
    db.scalar(select(User).where(User.customer_id == user.customer_id).order_by(User.id).limit(1).with_for_update())
    now = utcnow()
    expected = {}
    for row in rows(db, user):
        if (row['status'] or 'Unassessed').casefold() == 'unassessed' and row['created_at'] and aware(row['created_at']) < now - timedelta(days=7):
            expected[f"unassessed:{row['id']}"] = ('unassessed', str(row['id']),
                'Application has remained Unassessed for more than seven days. Review its context.',
                f"/RMS/candidates/{row['job_opening_id']}/{row['id']}")
    table = interview_table(db)
    parents = {row['id']: row for row in [as_dict(table, r) for r in db.execute(scoped(table,user)).mappings()]}
    for row in db.scalars(select(InterviewPanelFeedback).where(InterviewPanelFeedback.customer_id == user.customer_id,
        InterviewPanelFeedback.cancelled.is_(False), InterviewPanelFeedback.submitted_at.is_(None), InterviewPanelFeedback.due_at <= now)):
        parent = parents.get(row.interview_id)
        if parent and same_slot(parent,row):
            key = f"feedback:{row.id}:{aware(row.due_at).isoformat()}"
            expected[key] = ('feedback_due', row.id, 'An assigned interviewer response is overdue.', f"/RMS/interviews/{parent['jobId']}/{parent['id']}")
    for row in db.scalars(select(ScreeningJob).where(ScreeningJob.customer_id == user.customer_id, ScreeningJob.status == 'failed')):
        try: _, application = candidate(db, user, row.candidate_id)
        except HTTPException: continue
        expected[f"screening:{row.id}"] = ('screening_failed', row.id, 'Screening failed. Review the error before choosing whether to retry.', f"/RMS/candidates/{application['job_opening_id']}/{row.candidate_id}")
    existing = {r.signal_key:r for r in db.scalars(select(RecruitmentSignal).where(RecruitmentSignal.customer_id == user.customer_id))}
    for key, (kind, resource, message, href) in expected.items():
        if key not in existing:
            db.add(RecruitmentSignal(customer_id=user.customer_id, signal_key=key, kind=kind,
                resource_id=resource, message=message, href=href, status='open'))
        elif existing[key].status == 'resolved': existing[key].status = 'open'
    for key, row in existing.items():
        if key not in expected and row.status == 'open': row.status = 'resolved'
    db.flush()
    return len(expected)


@router.post('/signals/scan')
def scan(user=Depends(staff), db=Depends(get_db)):
    count = scan_signals(db,user)
    audit(db,user,'recruitment.signals_scanned','workspace',{'current_conditions':count})
    return {'conditions':count}


@router.get('/signals')
def signals(user=Depends(staff), db=Depends(get_db)):
    # Recheck current access to the linked application/interview before disclosure.
    data = []
    for row in db.scalars(select(RecruitmentSignal).where(RecruitmentSignal.customer_id == user.customer_id).order_by(RecruitmentSignal.created_at.desc()).limit(300)):
        try:
            parts = row.href.strip('/').split('/')
            if len(parts) != 4:
                continue
            if parts[1] == 'candidates':
                _, linked = candidate(db, user, int(parts[3]))
                if linked['job_opening_id'] != int(parts[2]):
                    continue
            elif parts[1] == 'interviews':
                from app.modules.recruiting.pipeline_interviews import get_record
                _, linked = get_record(db, user, int(parts[3]))
                if linked['jobId'] != int(parts[2]):
                    continue
            else:
                continue
        except (HTTPException, ValueError):
            continue
        data.append({'id':row.id, 'version':row.version, 'kind':row.kind, 'message':row.message,
            'href':row.href, 'status':row.status, 'created_at':row.created_at})
    return {'data':data}


class SignalDecision(Strict):
    version: int = Field(ge=1)
    status: Literal['open','dismissed']


@router.patch('/signals/{signal_id}')
def update_signal(signal_id: str, body: SignalDecision, user=Depends(staff), db=Depends(get_db)):
    row = db.scalar(select(RecruitmentSignal).where(RecruitmentSignal.id==signal_id,
        RecruitmentSignal.customer_id==user.customer_id).with_for_update())
    if not row: raise HTTPException(404,'Work item not found.')
    if row.version != body.version: raise HTTPException(409,'Work item changed; refresh first.')
    row.status=body.status
    audit(db,user,'recruitment.signal_reviewed',row.id,{'status':body.status})
    return {'saved':True}


class RoleAnalysis(Strict):
    job_ids: list[int] = Field(min_length=1, max_length=5)
    allow_provider_processing: bool = False


def role_sources(db, user, candidate_id, job_ids):
    _, row = candidate(db,user,candidate_id)
    p=profile(row)
    evidence = {key:p.get(key) for key in ('skills','workExperience','education','location','workMode') if p.get(key)}
    if not evidence: raise HTTPException(422,'Save candidate skills or experience before analysing roles.')
    sources={'candidate-profile':json.dumps(evidence,ensure_ascii=False)}
    for alias in sorted(set(job_ids)):
        role=job(db,user,alias)
        if role.status!='published': raise HTTPException(409,'Choose published roles only.')
        sources[f'job-{alias}']=json.dumps({'title':role.title,'description':role.description,'requirements':(role.job_details or {}).get('required_skills',[])},ensure_ascii=False)
    if sum(len(value) for value in sources.values())>40000: raise HTTPException(422,'Select fewer roles or shorten the source profiles.')
    return sources


@router.post('/candidates/{candidate_id}/role-analysis')
def analyse_roles(candidate_id:int, body:RoleAnalysis, request:Request, user=Depends(single_run), db=Depends(get_db)):
    if not body.allow_provider_processing: raise HTTPException(422,'Confirm AI processing first.')
    sources=role_sources(db,user,candidate_id,body.job_ids)
    result=generate(request.app.state.settings,'role-analysis',sources,{})
    db.expire_all()
    if not user.active or user.role not in {'admin','hr','recruiter'}: raise HTTPException(403,'Account access changed.')
    if role_sources(db,user,candidate_id,body.job_ids)!=sources: raise HTTPException(409,'Job or candidate changed; reload before analysis.')
    for section in result['sections']:
        if 'candidate-profile' not in section['source_ids'] or not any(k.startswith('job-') for k in section['source_ids']):
            raise HTTPException(502,'Role analysis did not cite both candidate and job evidence.')
    record_usage(db,user,result,candidate_id)
    return result


@router.get('/jobs')
def published_roles(user=Depends(staff),db=Depends(get_db)):
    return {'data':[{'id':alias,'title':role.title} for alias,role in db.execute(jobs_query(user)) if role.status=='published']}


class CostRequest(Strict):
    job_id: int = Field(gt=0)
    amount_minor: int = Field(gt=0, le=1000000000)
    currency: Literal['INR','USD','EUR','GBP']
    category: Literal['job_board','agency','assessment','other']
    note: str = Field(min_length=5,max_length=500)


@router.post('/costs')
def add_cost(body:CostRequest,user=Depends(staff),db=Depends(get_db)):
    job(db,user,body.job_id)
    row=RecruitmentCost(customer_id=user.customer_id,actor_id=user.id,incurred_at=utcnow(),**body.model_dump())
    db.add(row);db.flush();audit(db,user,'recruitment.cost_recorded',row.id,{'job_id':body.job_id})
    return {'saved':True,'id':row.id}


@router.get('/costs')
def costs(user=Depends(staff),db=Depends(get_db)):
    allowed={alias:role.title for alias,role in db.execute(jobs_query(user))}
    return {'data':[{'id':r.id,'job_id':r.job_id,'job_title':allowed[r.job_id],'amount_minor':r.amount_minor,
        'currency':r.currency,'category':r.category,'note':r.note,'incurred_at':r.incurred_at,'voided':r.voided} for r in db.scalars(
        select(RecruitmentCost).where(RecruitmentCost.customer_id==user.customer_id).order_by(RecruitmentCost.created_at.desc()).limit(200)) if r.job_id in allowed]}


@router.delete('/costs/{cost_id}')
def void_cost(cost_id:str,user=Depends(staff),db=Depends(get_db)):
    row=db.scalar(select(RecruitmentCost).where(RecruitmentCost.customer_id==user.customer_id,RecruitmentCost.id==cost_id).with_for_update())
    if not row: raise HTTPException(404,'Cost record not found.')
    job(db,user,row.job_id)
    row.voided=True
    audit(db,user,'recruitment.cost_voided',row.id)
    return {'voided':True}
