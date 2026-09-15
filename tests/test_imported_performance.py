from app.data.imported import table
from app.modules.workforce.imported_assets import insert, now
from app.modules.workforce.imported_organization import update
from test_imported_leave_attendance import setup_people


def test_performance_ownership_saved_scores_and_feedback(api):
    client, app, _, headers = api
    people = setup_people(api)
    with app.state.sessions.begin() as db:
        for model in ('PerformanceGoal', 'PerformanceAppraisal', 'PerformanceFeedback'):
            # SQLite has no public/hirava_core namespaces; replace only this
            # isolated fixture's colliding native table with the imported shape.
            if db.bind.dialect.name == 'sqlite':
                table(db, model).drop(db.bind, checkfirst=True)
            table(db, model).create(db.bind)
    base = '/api/performance-hub'
    response = client.get(base, headers=headers['employee'])
    assert response.status_code == 200, response.text
    assert response.json()['appraisal'] is None
    response = client.post(base + '/goals', json={'title': 'Synthetic goal', 'weight': 50}, headers=headers['employee'])
    assert response.status_code == 201, response.text
    goal = response.json()['id']
    assert client.patch(base + '/goals/' + goal, json={'progress': 50}, headers=headers['manager']).status_code == 404
    assert client.patch(base + '/goals/' + goal, json={'progress': 101}, headers=headers['employee']).status_code == 422
    assert client.patch(base + '/goals/' + goal, json={'progress': 50}, headers=headers['employee']).status_code == 200
    assert client.get(base, headers=headers['employee']).json()['stats']['avgProgress'] == 50
    assert client.patch(base + '/appraisal', json={'keyAchievements': 'Saved evidence'}, headers=headers['employee']).status_code == 404
    with app.state.sessions.begin() as db:
        appraisal = insert(db, 'PerformanceAppraisal', {'employeeId': people['employee']['id'], 'cycleLabel': 'Synthetic cycle',
            'status': 'Not Started', 'selfAssessmentStatus': 'Pending', 'managerReviewStatus': 'Pending'})
    response = client.patch(base + '/appraisal', json={'goalRating': {'goalId': goal, 'rating': 4, 'comment': 'Evidence'}, 'keyAchievements': 'Saved evidence'}, headers=headers['employee'])
    assert response.status_code == 200, response.text
    detail = client.get(base + '/appraisal', headers=headers['employee']).json()['appraisal']
    assert detail['goals'][0]['rating'] == 4
    assert detail['completion']['completed'] == 1
    assert client.get(base, headers=headers['employee']).json()['appraisal']['selfScore'] is None
    with app.state.sessions.begin() as db:
        update(db, 'PerformanceAppraisal', appraisal['id'], {'submittedAt': now()})
    assert client.patch(base + '/appraisal', json={'keyAchievements': 'Changed'}, headers=headers['employee']).status_code == 409
    payload = {'toEmployeeId': people['manager']['id'], 'rating': 4, 'comment': 'Synthetic feedback', 'sentiment': 'Positive'}
    response = client.post('/api/performance-feedback', json=payload, headers=headers['employee'])
    assert response.status_code == 201, response.text
    assert response.json()['direction'] == 'Given'
    assert client.get('/api/performance-feedback', headers=headers['hr']).json()['items'] == []
    received = client.get('/api/performance-feedback?direction=received', headers=headers['manager']).json()['items']
    assert len(received) == 1 and received[0]['direction'] == 'Received'
    assert client.post('/api/performance-feedback', json={**payload, 'fromEmployeeId': people['hr']['id']}, headers=headers['employee']).status_code == 422
    assert client.post('/api/performance-feedback', json={**payload, 'toEmployeeId': people['employee']['id']}, headers=headers['employee']).status_code == 400
