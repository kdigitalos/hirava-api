from app.agents.models import RecruitmentActivity


def activity(db, customer_id, actor_id, kind, candidate_id, job_id, before=None, after=None):
    db.add(RecruitmentActivity(customer_id=customer_id, actor_id=actor_id, kind=kind,
        candidate_id=candidate_id, job_id=job_id, from_stage=before, to_stage=after))
