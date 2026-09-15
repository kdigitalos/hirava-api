from datetime import datetime, timedelta, timezone

from conftest import position, post, get
from app.modules.recruiting.models import Application, Candidate, Requisition


def test_conflicts_reschedule_and_cancel_release(api):
    pos = position(api)
    with api[1].state.sessions.begin() as db:
        job = Requisition(customer_id='customer-a', position_id=pos['id'], title='Test role', description='Test', requested_by=api[2]['recruiter'], status='published')
        candidate = Candidate(customer_id='customer-a', name='Test candidate', email='slot@example.com', consent_at=datetime.now(timezone.utc), consent_notice='test')
        db.add_all([job, candidate]); db.flush()
        application = Application(customer_id='customer-a', candidate_id=candidate.id, requisition_id=job.id, status='interviewing')
        db.add(application); db.flush(); application_id = application.id
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=3)
    def booking(at, interviewer='interviewer', status=201):
        return post(api, '/rms/interviews', {'application_id': application_id, 'interviewer_id': api[2][interviewer], 'scheduled_at': at.isoformat(), 'duration_minutes': 60}, role='recruiter', status=status)
    first = booking(start)
    booking(start + timedelta(minutes=30), status=409)
    booking(start + timedelta(minutes=30), interviewer='manager', status=409)
    second = booking(start + timedelta(hours=1))
    path = f"/rms/interviews/{second['id']}/reschedule"
    body = {'scheduled_at': (start + timedelta(minutes=30)).isoformat(), 'duration_minutes': 60, 'expected_version': second['version'], 'reason': 'Candidate requested a new time'}
    post(api, path, body, role='interviewer', status=403)
    post(api, path, body, role='recruiter', status=409)
    body['scheduled_at'] = (start + timedelta(hours=2)).isoformat()
    moved = post(api, path, body, role='recruiter', status=200)
    assert moved['scheduled_at'].startswith((start + timedelta(hours=2)).isoformat()[:19])
    post(api, path, body, role='recruiter', status=409)
    audit = next(e for e in get(api, '/audit') if e['action'] == 'interview.rescheduled')
    assert audit['details']['previous_start'].startswith((start + timedelta(hours=1)).isoformat()[:19])
    post(api, f"/rms/interviews/{first['id']}/cancel", {'reason': 'Candidate requested cancellation'}, role='recruiter', status=200)
    booking(start)
