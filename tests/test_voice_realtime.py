import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from app.agents import voice_realtime as live
from app.agents.models import VoiceInterview
from app.data.database import utcnow
from test_voice_interview import setup_voice, ROOT

OFFER={'sdp':'v=0\r\ns=synthetic-test-offer\r\n','consent':True}


def fake_provider(monkeypatch):
    create=Mock(return_value=('synthetic-answer','rtc_synthetic'))
    socket=Mock()
    monkeypatch.setattr(live,'create_call',create)
    monkeypatch.setattr(live,'connect',Mock(return_value=socket))
    hangup=Mock();monkeypatch.setattr(live,'hangup',hangup)
    original=live.Observer
    def observer(*args):
        obj=original(*args)
        obj.thread=SimpleNamespace(start=lambda:None,join=lambda **kwargs:None)
        return obj
    monkeypatch.setattr(live,'Observer',observer)
    return create,socket,hangup


def test_live_setup_requires_consent_one_call_and_private_config(api,monkeypatch):
    client,app,_,headers=api
    parent,_,invite,token,_=setup_voice(api)
    create,socket,hangup=fake_provider(monkeypatch)
    assert client.post(ROOT+'/public/live',json=OFFER).status_code==404
    assert client.post(ROOT+'/public/live',headers=token,json={**OFFER,'consent':False}).status_code==422
    assert not create.called
    result=client.post(ROOT+'/public/live',headers=token,json=OFFER)
    assert result.status_code==200,result.text
    assert set(result.json())=={'sdp','deadline'}
    session=create.call_args.args[2]
    assert session['audio']['input']['turn_detection']['interrupt_response']
    assert session['audio']['input']['turn_detection']['create_response']
    assert session['model']=='gpt-realtime-mini'
    assert 'synthetic' not in json.dumps(session)
    assert client.post(ROOT+'/public/live',headers=token,json=OFFER).status_code==409
    assert create.call_count==1
    assert client.post(ROOT+'/public/speech',headers=token,json={'turn':0}).status_code==409
    assert client.post(ROOT+'/public/live-ready',headers=token,json={}).status_code==200
    assert app.state.voice_observers[invite['id']].ready.is_set()
    with app.state.sessions() as db:
        row=db.get(VoiceInterview,invite['id'])
        assert row.consent_at and row.realtime_attempts==1 and row.minutes<=5
    listed=client.get(f"{ROOT}/interviews/{parent['id']}",headers=headers['recruiter']).json()
    assert 'rtc_synthetic' not in json.dumps(listed)
    # Run the observer synchronously after withdrawal: immediate hangup, no greeting.
    client.delete(f"{ROOT}/sessions/{invite['id']}",headers=headers['recruiter'])
    app.state.voice_observers[invite['id']].run()
    hangup.assert_called_once();socket.send.assert_not_called()


def test_failed_attach_hangs_up_and_consumes_attempt(api,monkeypatch):
    client,app,_,_=api
    _,_,invite,token,_=setup_voice(api)
    create,socket,hangup=fake_provider(monkeypatch)
    monkeypatch.setattr(live,'connect',Mock(side_effect=RuntimeError('private provider detail')))
    r=client.post(ROOT+'/public/live',headers=token,json=OFFER)
    assert r.status_code==502 and 'private provider detail' not in r.text
    hangup.assert_called_once()
    assert client.post(ROOT+'/public/live',headers=token,json=OFFER).status_code==409
    with app.state.sessions() as db:
        row=db.get(VoiceInterview,invite['id'])
        assert row.status=='completed' and row.realtime_attempts==1 and not row.lease


def test_observer_transcript_dedup_summary_and_deadline(api,monkeypatch):
    client,app,_,headers=api
    _,_,invite,token,_=setup_voice(api)
    create,socket,hangup=fake_provider(monkeypatch)
    assert client.post(ROOT+'/public/live',headers=token,json=OFFER).status_code==200
    with app.state.sessions() as db:
        event={'type':'conversation.item.input_audio_transcription.completed','item_id':'one','transcript':'I wrote API tests.'}
        live.transcript_event(db,invite['id'],event)
        live.transcript_event(db,invite['id'],event)
        live.transcript_event(db,invite['id'],{'type':'response.output_audio_transcript.done','item_id':'two','transcript':'Which tests did you write?'})
        assert len(db.get(VoiceInterview,invite['id']).realtime_transcript)==2
        row=db.get(VoiceInterview,invite['id']);row.started_at=utcnow()-timedelta(minutes=10);db.commit()
    app.state.voice_observers[invite['id']].run()
    hangup.assert_called_once()
    result=client.post(ROOT+'/public/state',headers=token,json={}).json()
    assert result['status']=='completed' and len(result['live_transcript'])==2
    summary=Mock(return_value={'overview':'Candidate reported API tests.','follow_up':[]})
    monkeypatch.setattr('app.agents.voice.conversation',summary)
    r=client.post(f"{ROOT}/sessions/{invite['id']}/summary",headers=headers['recruiter'],json={})
    assert r.status_code==200,r.text
    assert summary.call_args.args[2][0]['speaker']=='candidate'
    assert client.post(f"{ROOT}/sessions/{invite['id']}/summary",headers=headers['recruiter'],json={}).status_code==200
    assert summary.call_count==1


def test_observer_greets_and_saves_provider_events(api,monkeypatch):
    client,app,_,_=api
    _,_,invite,token,_=setup_voice(api)
    _,socket,hangup=fake_provider(monkeypatch)
    assert client.post(ROOT+'/public/live',headers=token,json=OFFER).status_code==200
    observer=app.state.voice_observers[invite['id']]
    observer.ready.set()
    events=iter([
        {'type':'response.created'},
        {'type':'response.output_audio_transcript.done','item_id':'question','transcript':'Tell me about your project.'},
        {'type':'conversation.item.input_audio_transcription.completed','item_id':'answer','transcript':'I built a Python API.'},
    ])
    def receive(**kwargs):
        event=next(events,None)
        if event is None:
            observer.stop.set()
            raise TimeoutError()
        return json.dumps(event)
    socket.recv.side_effect=receive
    observer.run()
    assert json.loads(socket.send.call_args.args[0])=={'type':'response.create'}
    hangup.assert_called_once()
    with app.state.sessions() as db:
        row=db.get(VoiceInterview,invite['id'])
        assert row.status=='completed' and len(row.realtime_transcript)==2
        assert row.realtime_error is None
