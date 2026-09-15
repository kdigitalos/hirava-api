from app.data.imported import table
from app.modules.workforce.imported_parties import CHILDREN


def test_parties_nested_updates_atomic_validation_and_access(api):
    client, app, _, headers = api
    with app.state.sessions.begin() as db:
        for model in ('Party', *CHILDREN.values()):
            table(db, model).create(db.bind)
    path = '/api/parties'
    payload = {'name': 'Synthetic supplier', 'roles': [{'roleType': 'VENDOR'}],
               'contactPersons': [{'name': 'Test contact', 'isPrimary': True}]}
    assert client.post(path, json=payload, headers=headers['hr']).status_code == 403
    response = client.post(path, json=payload, headers=headers['admin'])
    assert response.status_code == 201, response.text
    record = response.json()
    url = path + '/' + record['id']
    assert record['roles'][0]['status'] == 'ACTIVE'
    assert len(client.get(path + '?roleType=VENDOR', headers=headers['admin']).json()) == 1
    assert client.get(path + '?roleType=CLIENT', headers=headers['admin']).json() == []
    response = client.put(url, json={'name': 'Renamed'}, headers=headers['admin'])
    assert response.status_code == 200, response.text
    assert len(response.json()['contactPersons']) == 1
    assert client.put(url, json={'name': 'Bad name', 'roles': [{'roleType': 'VENDOR'}, {'roleType': 'VENDOR'}]}, headers=headers['admin']).status_code == 422
    assert client.get(url, headers=headers['admin']).json()['name'] == 'Renamed'
    assert client.put(url, json={'roles': []}, headers=headers['admin']).json()['roles'] == []
    assert client.delete(url, headers=headers['admin']).status_code == 200
    assert client.get(url, headers=headers['admin']).status_code == 404
