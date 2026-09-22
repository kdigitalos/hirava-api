import io
import wave
from datetime import timedelta
from uuid import uuid4
from pydantic import SecretStr
from sqlalchemy import select
from app.agents.models import VoiceInterview
from app.data.database import utcnow
from test_interview_panel import setup_interview

ROOT='/api/voice-interview'


def setup_voice(api,followups=False):
    client,app,_,headers=api
    parent,person=setup_interview(api)
    app.state.settings.ai_voice_interviews_enabled=True
    app.state.settings.openai_api_key=SecretStr('synthetic')
    app.state.settings.openai_model='synthetic'
    body={'questions':['Describe how you tested your Python project.'],'minutes':5,
          'allow_followups':followups,'allow_provider_processing':True}
    r=client.post(f"{ROOT}/interviews/{parent['id']}",headers=headers['recruiter'],json=body)
    assert r.status_code==200,r.text
    data=r.json()
    return parent,person,data,{'x-interview-token':data['token']},body


def test_consent_scoping_transcript_idempotency_and_revoke(api,monkeypatch):
    client,app,_,headers=api
    parent,person,invite,token,body=setup_voice(api,True)
    assert client.get(f"{ROOT}/interviews/{parent['id']}").status_code==401
    assert client.get(f"{ROOT}/interviews/{parent['id']}",headers=headers['employee']).status_code==403
    assert client.get(f"{ROOT}/interviews/{parent['id']}",headers=headers['outsider']).status_code in (401,404)
    assert client.post(ROOT+'/public/state',json={}).status_code==404
    initial=client.post(ROOT+'/public/state',headers=token,json={}).json()
    assert initial['question']=='' and initial['answers']==[]
    answer={'turn':0,'text':'I wrote unit tests for the API.','request_id':str(uuid4())}
    assert client.post(ROOT+'/public/answer',headers=token,json=answer).status_code==409
    assert client.post(ROOT+'/public/start',headers=token,json={'consent':False}).status_code==422
    started=client.post(ROOT+'/public/start',headers=token,json={'consent':True}).json()
    assert client.post(ROOT+'/public/start',headers=token,json={'consent':True}).json()['deadline']==started['deadline']
    calls=[]
    monkeypatch.setattr('app.agents.voice.followup',lambda *args:calls.append(args) or 'Which failure did those tests catch?')
    r=client.post(ROOT+'/public/answer',headers=token,json=answer)
    assert r.status_code==200,r.text
    assert r.json()['followup'] and r.json()['turn']==1
    assert client.post(ROOT+'/public/answer',headers=token,json=answer).json()['turn']==1
    assert len(calls)==1
    assert client.post(ROOT+'/public/answer',headers=token,json={**answer,'request_id':str(uuid4())}).status_code==409
    r=client.post(ROOT+'/public/answer',headers=token,json={'turn':1,'text':'A validation bug.','request_id':str(uuid4())})
    assert r.json()['status']=='completed' and len(r.json()['answers'])==2
    assert len(calls)==1
    with app.state.sessions() as db:
        row=db.get(VoiceInterview,invite['id'])
        assert row.token_hash!=invite['token'] and row.consent_at
    listed=client.get(f"{ROOT}/interviews/{parent['id']}",headers=headers['recruiter']).json()['data'][0]
    assert len(listed['answers'])==2 and 'token_hash' not in listed and 'token' not in listed
    assert client.delete(f"{ROOT}/sessions/{invite['id']}",headers=headers['recruiter']).status_code==200
    assert client.post(ROOT+'/public/state',headers=token,json={}).status_code==410


def test_speech_limits_and_failures_persist_allowance(api,monkeypatch):
    client,app,_,_=api
    parent,person,invite,token,body=setup_voice(api)
    client.post(ROOT+'/public/start',headers=token,json={'consent':True})
    def unavailable(*args):raise RuntimeError('sensitive provider error')
    monkeypatch.setattr('app.agents.voice.speak',unavailable)
    for _ in range(4):
        r=client.post(ROOT+'/public/speech',headers=token,json={'turn':0})
        assert r.status_code==502 and 'sensitive' not in r.text
    assert client.post(ROOT+'/public/speech',headers=token,json={'turn':0}).status_code==429
    with app.state.sessions() as db:
        row=db.get(VoiceInterview,invite['id']);assert row.speech_calls==4 and not row.lease
    calls=[]
    monkeypatch.setattr('app.agents.voice.transcribe',lambda settings,audio:calls.append(audio) or 'Recognised answer')
    assert client.post(ROOT+'/public/transcribe',headers={**token,'x-interview-turn':'0'},content=b'not audio').status_code==422
    assert calls==[]
    audio=io.BytesIO()
    with wave.open(audio,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x00\x00'*16000)
    r=client.post(ROOT+'/public/transcribe',headers={**token,'x-interview-turn':'0'},content=audio.getvalue())
    assert r.status_code==200,r.text
    assert r.json()['text']=='Recognised answer' and len(calls)==1
    # Recognition is a draft; no candidate answer is stored before confirmation.
    with app.state.sessions() as db:assert db.get(VoiceInterview,invite['id']).answers==[]
    assert client.post(ROOT+'/public/transcribe',headers={**token,'x-interview-turn':'0'},content=b'x'*(3*1024*1024+1)).status_code==413


def test_time_limit_summary_and_replacement(api,monkeypatch):
    client,app,_,headers=api
    parent,person,invite,token,body=setup_voice(api)
    replacement=client.post(f"{ROOT}/interviews/{parent['id']}",headers=headers['recruiter'],json=body).json()
    assert client.post(ROOT+'/public/state',headers=token,json={}).status_code==410
    token={'x-interview-token':replacement['token']}
    client.post(ROOT+'/public/start',headers=token,json={'consent':True})
    client.post(ROOT+'/public/answer',headers=token,json={'turn':0,'text':'I wrote a test.','request_id':str(uuid4())})
    calls=[]
    monkeypatch.setattr('app.agents.voice.conversation',lambda *args:calls.append(args) or {'overview':'The candidate reported writing a test.','follow_up':['Ask for a specific example.']})
    path=f"{ROOT}/sessions/{replacement['id']}/summary"
    assert client.post(path,headers=headers['recruiter']).status_code==200
    assert client.post(path,headers=headers['recruiter']).status_code==200 and len(calls)==1
    with app.state.sessions.begin() as db:
        row=db.get(VoiceInterview,replacement['id']);row.status='active';row.started_at=utcnow()-timedelta(minutes=6)
    assert client.post(ROOT+'/public/state',headers=token,json={}).json()['status']=='completed'
    assert client.post(ROOT+'/public/speech',headers=token,json={'turn':1}).status_code==409
    with app.state.sessions.begin() as db:
        row=db.get(VoiceInterview,replacement['id']);row.expires_at=utcnow()-timedelta(seconds=1)
    assert client.post(ROOT+'/public/state',headers=token,json={}).status_code==410


def test_busy_lease_blocks_duplicate_paid_work_and_parent_removal(api,monkeypatch):
    client,app,_,headers=api
    parent,person,invite,token,body=setup_voice(api)
    client.post(ROOT+'/public/start',headers=token,json={'consent':True})
    with app.state.sessions.begin() as db:
        row=db.get(VoiceInterview,invite['id']);row.lease=str(uuid4());row.lease_until=utcnow()+timedelta(minutes=2)
    called=[];monkeypatch.setattr('app.agents.voice.speak',lambda *args:called.append(1) or b'audio')
    assert client.post(ROOT+'/public/speech',headers=token,json={'turn':0}).status_code==409
    assert called==[]
    assert client.delete(f"/api/interview?ids={parent['id']}",headers=headers['recruiter']).status_code==200
    assert client.post(ROOT+'/public/state',headers=token,json={}).status_code==404
