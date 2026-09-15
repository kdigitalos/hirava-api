from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from app.core import invitations as service
from app.core.models import AccountInvitation, User
from conftest import get


def test_invitation_permissions_failure_retry_and_duplicate(api, monkeypatch):
    client, app, users, headers = api
    payload = {'name': 'Invite Test', 'email': 'invite@example.com', 'role': 'employee'}
    assert client.post('/api/v1/account-invitations', json=payload, headers=headers['admin']).status_code == 503
    for role in ['employee', 'manager', 'hr', 'recruiter', 'interviewer']:
        assert client.post('/api/v1/account-invitations', json=payload, headers=headers[role]).status_code == 403
        assert client.get('/api/v1/account-invitations', headers=headers[role]).status_code == 403
    monkeypatch.setattr(service, 'configured', lambda _: True)
    calls = []
    class Provider:
        def __init__(self, _): pass
        def identity(self, account, invitation):
            calls.append('identity'); return 'auth0|synthetic-invite'
        def send(self, account):
            calls.append('send')
            if calls.count('send') == 1: raise service.ProviderError('provider_unavailable')
    monkeypatch.setattr(service, 'Auth0Provider', Provider)
    response = client.post('/api/v1/account-invitations', json=payload, headers=headers['admin'])
    assert response.status_code == 200, response.text
    data = response.json(); invitation = data['invitation']; uid = data['account']['id']
    assert invitation['status'] == 'failed'
    with app.state.sessions() as db:
        assert db.get(User, uid).auth_subject == 'auth0|synthetic-invite'
        assert db.get(User, uid).active
    path = '/api/v1/account-invitations/' + invitation['id'] + '/retry'
    assert client.post(path, headers=headers['employee']).status_code == 403
    assert client.post(path, headers=headers['outsider']).status_code == 401
    result = client.post(path, headers=headers['admin'])
    assert result.status_code == 200 and result.json()['invitation']['status'] == 'accepted_by_provider'
    assert calls == ['identity', 'send', 'send']
    assert client.post(path, headers=headers['admin']).status_code == 200
    assert calls == ['identity', 'send', 'send'], 'completed request is idempotent'
    assert client.post('/api/v1/account-invitations', json=payload, headers=headers['admin']).status_code == 409
    assert any(e['action'] == 'user.invitation_email_requested' for e in get(api, '/audit'))


def test_provider_failure_keeps_account_inactive_and_can_recover(api, monkeypatch):
    client, app, _, headers = api
    monkeypatch.setattr(service, 'configured', lambda _: True)
    class Provider:
        def __init__(self, _): pass
        def identity(self, *args): raise service.ProviderError('provider_unavailable')
        def send(self, *args): pytest.fail('No email before identity persistence')
    monkeypatch.setattr(service, 'Auth0Provider', Provider)
    response = client.post('/api/v1/account-invitations', json={'name':'Failure', 'email':'failed@example.com','role':'hr'}, headers=headers['admin'])
    data=response.json(); assert data['invitation']['status']=='failed'
    with app.state.sessions() as db:
        user=db.get(User,data['account']['id']);assert not user.active and user.auth_subject is None
        inv=db.get(AccountInvitation,data['invitation']['id']);inv.status='processing';db.commit()
    assert client.post('/api/v1/account-invitations/'+data['invitation']['id']+'/retry',headers=headers['admin']).status_code==409


def test_provider_existing_identity_verification_and_recovery(monkeypatch):
    settings=SimpleNamespace(auth0_domain='test.auth0.com',auth0_connection='Username-Password-Authentication',
        auth0_mgmt_client_id='id',auth0_mgmt_client_secret=SimpleNamespace(get_secret_value=lambda:'secret'))
    provider=service.Auth0Provider(settings)
    person={'user_id':'auth0|existing','email':'person@example.com','email_verified':False,
            'identities':[{'connection':settings.auth0_connection,'provider':'auth0'}]}
    def call(method,path,**kwargs):
        return httpx.Response(200,json={'access_token':'test-token'} if path=='/oauth/token' else [person])
    monkeypatch.setattr(provider,'call',call)
    account=SimpleNamespace(email='person@example.com'); invitation=SimpleNamespace(id='invitation-id')
    with pytest.raises(service.ProviderError,match='existing_identity_requires_review'): provider.identity(account,invitation)
    person['email_verified']=True
    assert provider.identity(account,invitation)=='auth0|existing'
    person['email_verified']=False;person['app_metadata']={'hirava_invitation_id':invitation.id}
    assert provider.identity(account,invitation)=='auth0|existing'
    person['blocked']=True
    with pytest.raises(service.ProviderError,match='provider_identity_blocked'):provider.identity(account,invitation)


def test_employee_link_failure_does_not_send(api, monkeypatch):
    from fastapi import HTTPException
    client,app,_,headers=api
    monkeypatch.setattr(service,'configured',lambda _:True)
    app.state.settings.legacy_api_url='http://private.test'
    def fail(*args):raise HTTPException(409,'Already linked')
    monkeypatch.setattr(service,'set_employee_link',fail)
    response=client.post('/api/v1/account-invitations',json={'name':'Test','email':'linkfail@example.com','role':'employee','employee_id':'e1'},headers=headers['admin'])
    assert response.status_code==409
    with app.state.sessions() as db:
        assert db.scalar(select(User).where(User.email=='linkfail@example.com')) is None


def test_employee_invitation_links_before_email(api, monkeypatch):
    client,app,_,headers=api
    monkeypatch.setattr(service,'configured',lambda _:True)
    app.state.settings.legacy_api_url='http://private.test'
    linked=[]
    def link(db,account,employee_id):
        assert account.active
        linked.append((account.auth_subject,employee_id))
    monkeypatch.setattr(service,'set_employee_link',link)
    class Provider:
        def __init__(self,_):pass
        def identity(self,account,invitation):
            assert not account.active
            return 'auth0|linkedtest'
        def send(self,account):
            assert linked[-1]==('auth0|linkedtest','test-employee')
            with app.state.sessions() as db:
                assert db.get(User,account.id).auth_subject=='auth0|linkedtest'
    monkeypatch.setattr(service,'Auth0Provider',Provider)
    result=client.post('/api/v1/account-invitations',json={'name':'Linked','email':'linked@example.com','role':'employee','employee_id':'test-employee'},headers=headers['admin'])
    assert result.status_code==200,result.text
    assert result.json()['invitation']['status']=='accepted_by_provider'
