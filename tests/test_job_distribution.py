from sqlalchemy import select
from conftest import position, post
from app.agents.models import JobDistribution
from app.modules.recruiting.models import Requisition


def job(api):
    return post(api, '/rms/requisitions', {'position_id':position(api)['id'], 'title':'Python developer',
        'description':'Build Python services.', 'job_details':{'company_name':'Test employer','location':'Hyderabad',
        'budget':'90000','currency':'INR','extra_fields':{'private':'internal'}}}, role='recruiter')


def approve(api, record):
    post(api,f"/rms/requisitions/{record['id']}/submit",role='recruiter',status=200)
    post(api,f"/rms/requisitions/{record['id']}/approve",{'reason':'Approved'},role='hr',status=200)


def test_preparation_manual_lifecycle_and_idempotence(api):
    client,app,_,headers=api; record=job(api); base=f"/api/job-distribution/jobs/{record['id']}"
    send=lambda path,body:client.post(base+path,json=body,headers=headers['recruiter'])
    assert send('/prepare',{'destinations':['linkedin']}).status_code==409
    approve(api,record)
    r=send('/prepare',{'destinations':['linkedin','indeed','linkedin']}); assert r.status_code==200,r.text
    linked=r.json()['destinations'][0]; assert linked['record']['status']=='prepared' and not linked['connected']
    assert 'budget' not in linked['record']['snapshot'] and 'extra_fields' not in linked['record']['snapshot']
    assert not r.json()['careers']['path']
    first=linked['record']['version']
    assert send('/prepare',{'destinations':['linkedin']}).json()['destinations'][0]['record']['version']==first
    body={'expected_version':first,'status':'reported_live','external_url':'https://www.linkedin.com/jobs/view/123'}
    assert send('/linkedin/manual-status',body).status_code==409
    post(api,f"/rms/requisitions/{record['id']}/publish",role='recruiter',status=200)
    r=send('/linkedin/manual-status',body); assert r.status_code==200,r.text
    assert r.json()['careers']['path'].startswith('/careers/apply/')
    version=r.json()['destinations'][0]['record']['version']
    assert send('/linkedin/manual-status',body).status_code==409
    assert send('/prepare',{'destinations':['linkedin']}).status_code==409
    post(api,f"/rms/requisitions/{record['id']}/close",{'reason':'Filled'},role='recruiter',status=200)
    state=client.get(base,headers=headers['hr']).json()
    assert state['destinations'][0]['closure_needed'] and not state['careers']['path']
    r=send('/linkedin/manual-status',{'expected_version':version,'status':'reported_closed'})
    assert r.status_code==200 and not r.json()['destinations'][0]['closure_needed']
    with app.state.sessions() as db:
        assert len(db.scalars(select(JobDistribution)).all())==2


def test_permissions_url_validation_and_tenant_isolation(api):
    client,app,_,headers=api; record=job(api); approve(api,record)
    post(api,f"/rms/requisitions/{record['id']}/publish",role='recruiter',status=200)
    base=f"/api/job-distribution/jobs/{record['id']}"
    assert client.get(base).status_code==401
    for role in ('employee','manager','interviewer'):
        assert client.get(base,headers=headers[role]).status_code==403
    assert client.post(base+'/prepare',headers=headers['hr'],json={'destinations':['linkedin']}).status_code==403
    r=client.post(base+'/prepare',headers=headers['recruiter'],json={'destinations':['linkedin']}); assert r.status_code==200
    version=r.json()['destinations'][0]['record']['version']
    for url in ('javascript:alert(1)','http://linkedin.com/jobs/1','https://linkedin.com.evil.test/jobs/1',
                'https://secret@linkedin.com/jobs/1','https://indeed.com/jobs/1','https://linkedin.com:bad/jobs/1'):
        r=client.post(base+'/linkedin/manual-status',headers=headers['recruiter'],json={
            'expected_version':version,'status':'reported_live','external_url':url})
        assert r.status_code==422,r.text
    with app.state.sessions.begin() as db:
        db.get(Requisition,record['id']).customer_id='customer-b'
    assert client.get(base,headers=headers['recruiter']).status_code==404
    assert client.post(base+'/prepare',headers=headers['recruiter'],json={'destinations':['linkedin']}).status_code==404
