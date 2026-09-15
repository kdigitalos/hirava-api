from conftest import position, post


def test_public_job_detail_hides_private_and_unpublished_data(api):
    client, app, _, _ = api
    job = post(api, '/rms/requisitions', {'position_id': position(api)['id'],
        'title': 'Public vacancy', 'description': 'Role description',
        'job_details': {'company_name': 'Company', 'location': 'Hyderabad', 'budget': '5000', 'currency': 'INR'}}, role='recruiter')
    path = f"/api/v1/careers/jobs/{job['legacy_id']}"
    assert client.get(path).status_code == 404
    post(api, f"/rms/requisitions/{job['id']}/submit", role='recruiter', status=200)
    post(api, f"/rms/requisitions/{job['id']}/approve", {'reason': 'Approved'}, role='hr', status=200)
    assert client.get(path).status_code == 404
    post(api, f"/rms/requisitions/{job['id']}/publish", role='recruiter', status=200)
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {'id': job['id'], 'title': 'Public vacancy', 'description': 'Role description', 'company': 'Company', 'location': 'Hyderabad'}
    app.state.settings.customer_id = 'customer-b'
    assert client.get(path).status_code == 404
    app.state.settings.customer_id = 'customer-a'
    app.state.settings.rms_enabled = False
    assert client.get(path).status_code == 404
    app.state.settings.rms_enabled = True
    post(api, f"/rms/requisitions/{job['id']}/close", {'reason': 'Closed'}, role='recruiter', status=200)
    assert client.get(path).status_code == 404
    assert client.post('/api/v1/careers/applications', json={'requisition_id': job['id']}).status_code == 401
