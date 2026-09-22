from datetime import timedelta
from sqlalchemy import select, update
from app.agents.models import RecruitmentActivity, RecruitmentSignal, TalentPoolMember
from app.modules.recruiting.public_intake import pipeline_table
from app.data.database import utcnow
from test_interview_panel import setup_interview


def test_identity_pools_metrics_reports_and_tenant_scope(api):
    client, app, users, headers = api
    interview, person = setup_interview(api)
    auth = headers['recruiter']; root='/api/recruitment-operations'
    fields=[{'name':'firstName','value':'Synthetic Person'}, {'name':'email','value':'same@example.com'}, {'name':'skills','value':'Python SQL'}]
    assert client.put(f'/api/candidate?id={person}',headers=auth,json={'object':fields}).status_code==200
    second=client.post('/api/candidate',headers=auth,json={'jobOpeningId':interview['jobId'],'object':fields}).json()['data']['id']
    assert client.get(root+'/duplicates').status_code==401
    assert client.get(root+'/duplicates',headers=headers['employee']).status_code==403
    result=client.get(root+'/duplicates',headers=auth)
    assert result.status_code==200,result.text
    pair=result.json()['data'][0]
    payload={'left_id':person,'right_id':second,'fingerprint':pair['fingerprint'],'version':0,'decision':'same_person'}
    saved=client.put(root+'/duplicates',headers=auth,json=payload)
    assert saved.status_code==200,saved.text
    assert client.put(root+'/duplicates',headers=auth,json=payload).status_code==409
    payload.update(version=saved.json()['version'],decision='unreviewed')
    assert client.put(root+'/duplicates',headers=auth,json=payload).status_code==200
    assert len(client.get('/api/candidate',headers=auth).json()['data'])==2
    assert client.put(root+'/duplicates',headers=headers['outsider'],json=payload).status_code in (401,404)
    pool=client.post(root+'/pools',headers=auth,json={'name':'Python talent'}).json()
    member={'candidate_id':person,'contact_preference':'do_not_contact','review_in_days':30}
    assert client.put(root+f"/pools/{pool['id']}/members",headers=auth,json=member).status_code==200
    assert client.put(root+f"/pools/{pool['id']}/members",headers=auth,json=member).status_code==200
    assert len(client.get(root+'/pools',headers=auth).json()['data'][0]['members'])==1
    assert client.put(root+f"/pools/{pool['id']}/members",headers=headers['outsider'],json=member).status_code in (401,404)
    assert client.put(f'/api/candidate?id={person}',headers=auth,json={'status':'Shortlisted'}).status_code==200
    metrics=client.get(root+'/metrics?days=30',headers=auth)
    assert metrics.status_code==200,metrics.text
    data=metrics.json()
    assert data['applications_received']==2
    assert data['current_stages_of_cohort']=={'Shortlisted':1,'Unassessed':1}
    assert data['recorded_transitions']==[{'from':'Unassessed','to':'Shortlisted','count':1}]
    assert data['cost_per_hire'] is None
    report=client.post(root+'/reports',headers=auth,json={'days':30})
    assert report.status_code==200,report.text
    assert report.json()['metrics']['applications_received']==2
    assert len(client.get(root+'/reports',headers=auth).json()['data'])==1
    assert client.post(root+'/reports',headers=auth,json={'days':30,'use_ai':True}).status_code==422


def test_work_queue_idempotent_and_resolves(api):
    client,app,users,headers=api
    _,person=setup_interview(api)
    auth=headers['recruiter'];root='/api/recruitment-operations'
    with app.state.sessions.begin() as db:
        table=pipeline_table(db)
        db.execute(table.update().where(table.c.id==person).values(created_at=utcnow()-timedelta(days=9)))
    for _ in range(2):
        result=client.post(root+'/signals/scan',headers=auth)
        assert result.status_code==200,result.text
    items=client.get(root+'/signals',headers=auth).json()['data']
    assert len(items)==1 and items[0]['status']=='open'
    assert client.put(f'/api/candidate?id={person}',headers=auth,json={'status':'Shortlisted'}).status_code==200
    assert client.post(root+'/signals/scan',headers=auth).status_code==200
    assert client.get(root+'/signals',headers=auth).json()['data'][0]['status']=='resolved'


def test_internal_calendar_conflicts_and_cancellation(api):
    client,app,users,headers=api
    parent,person=setup_interview(api)
    auth=headers['recruiter']
    start=utcnow()+timedelta(days=2)
    first=client.put(f"/api/interview?id={parent['id']}",headers=auth,json={
        'reviewer_ids':[users['interviewer']], 'starts_at':start.isoformat(),'duration':'30'})
    assert first.status_code==200,first.text
    slot={'interviewId':parent['id'],'candidateId':person,'jobId':parent['jobId'],
        'interviewDate':start.isoformat(),'starts_at':(start+timedelta(minutes=10)).isoformat(),
        'duration':'30','reviewer_ids':[users['interviewer']]}
    conflict=client.post('/api/interviewSchedule',headers=auth,json=slot)
    assert conflict.status_code==409,conflict.text
    stale=client.put(f"/api/interview?id={parent['id']}",headers=auth,json={'interviewTime':'09:00'})
    assert stale.status_code==422,stale.text
    assert client.get(f"/api/interview?id={parent['id']}",headers=auth).json()['data']['S2'] is None
    # Adjacent interviews do not overlap; removing a round releases its reservation.
    slot['starts_at']=(start+timedelta(minutes=30)).isoformat()
    created=client.post('/api/interviewSchedule',headers=auth,json=slot)
    assert created.status_code==201,created.text
    assert client.delete(f"/api/interviewSchedule?ids={created.json()['data']['id']}",headers=auth).status_code==200
    assert client.post('/api/interviewSchedule',headers=auth,json=slot).status_code==201


def test_ai_role_comparison_sources_and_access(api,monkeypatch):
    client,app,users,headers=api
    parent,person=setup_interview(api)
    auth=headers['recruiter']
    client.put(f'/api/candidate?id={person}',headers=auth,json={'object':[{'name':'skills','value':'Python SQL'},{'name':'workExperience','value':'Built a database API'}]})
    captured=[]
    def fake(settings,kind,sources,options):
        captured.append(sources)
        return {'sections':[{'title':'Job comparison','text':'Discuss the API project.', 'source_ids':['candidate-profile',f"job-{parent['jobId']}"]}], 'limitations':[], 'sources':sources,'kind':kind,'provider':'test','model':'test','tokens':{}}
    monkeypatch.setattr('app.agents.operations.generate',fake)
    endpoint=f'/api/recruitment-operations/candidates/{person}/role-analysis'
    body={'job_ids':[parent['jobId']],'allow_provider_processing':True}
    assert client.post(endpoint,headers=headers['employee'],json=body).status_code==403
    response=client.post(endpoint,headers=auth,json=body)
    assert response.status_code==200,response.text
    assert len(captured)==1 and 'Built a database API' in captured[0]['candidate-profile']
    assert 'email' not in captured[0]['candidate-profile']


def test_recorded_costs_and_hire_times_do_not_invent_missing_history(api):
    client,app,users,headers=api
    parent,person=setup_interview(api)
    auth=headers['recruiter'];root='/api/recruitment-operations'
    with app.state.sessions.begin() as db:
        table=pipeline_table(db)
        db.execute(table.update().where(table.c.id==person).values(created_at=utcnow()-timedelta(days=5)))
    assert client.put(f'/api/candidate?id={person}',headers=auth,json={'status':'Hired'}).status_code==200
    cost={'job_id':parent['jobId'],'amount_minor':12345,'currency':'INR','category':'job_board','note':'Synthetic invoice 001'}
    response=client.post(root+'/costs',headers=auth,json=cost)
    assert response.status_code==200,response.text
    assert client.post(root+'/costs',headers=auth,json={**cost,'currency':'USD','amount_minor':500}).status_code==200
    data=client.get(root+'/metrics',headers=auth).json()
    assert data['recorded_costs']=={'INR':12345,'USD':500}
    assert data['application_to_hired_days']==5 and data['recorded_hires']==1
    assert data['cost_per_hire'] is None
    assert client.delete(root+f"/costs/{response.json()['id']}",headers=auth).status_code==200
    assert client.get(root+'/metrics',headers=auth).json()['recorded_costs']=={'USD':500}
