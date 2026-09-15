from conftest import post, get


def payload(api):
    return {"employee_id": api[2]["employee"], "title": "Synthetic plan", "reason": "Specific evidence for review",
        "start_date": "2026-09-01", "end_date": "2026-12-01", "milestones": [{"title": "Delivery",
        "current_performance": "Baseline evidence", "expected_performance": "Agreed measurable target",
        "action_steps": "Weekly planning", "support": "Coaching", "success_criteria": "Agreed acceptance measure",
        "due_date": "2026-11-01"}]}


def test_plan_full_lifecycle_scoped_and_immutable(api):
    body = payload(api)
    plan = post(api, "/hrms/improvement-plans", body, role="hr")
    path = "/hrms/improvement-plans/" + plan["id"]
    assert get(api, "/hrms/improvement-plans", role="employee") == []
    get(api, path, role="employee", status=404)
    post(api, path + "/publish", {"expected_version": 99}, role="hr", status=409)
    plan = post(api, path + "/publish", {"expected_version": plan["version"]}, role="hr", status=200)
    assert len(get(api, "/hrms/improvement-plans", role="employee")) == 1
    get(api, path, role="manager", status=404)
    post(api, path + "/acknowledge", {"expected_version": plan["version"]}, role="hr", status=403)
    plan = post(api, path + "/acknowledge", {"expected_version": plan["version"]}, role="employee", status=200)
    assert plan["acknowledged_at"]
    review = {"expected_version": plan["version"], "milestone_index": 0, "progress": 50, "feedback": "Reviewed work evidence"}
    post(api, path + "/reviews", review, role="employee", status=403)
    post(api, path + "/reviews", {**review, "progress": 101}, role="hr", status=422)
    plan = post(api, path + "/reviews", review, role="hr")
    assert plan["milestones"][0]["progress"] == 50
    assert plan["reviews"][0]["reviewer_id"] == api[2]["hr"]
    post(api, path + "/reviews", review, role="hr", status=409)
    plan = post(api, path + "/close", {"expected_version": plan["version"], "status": "completed", "outcome": "Human-reviewed final evaluation"}, role="hr", status=200)
    post(api, path + "/reviews", {**review, "expected_version": plan["version"]}, role="hr", status=409)
    assert get(api, path, role="employee")["outcome"] == "Human-reviewed final evaluation"


def test_plan_validation_and_identity(api):
    body = payload(api)
    post(api, "/hrms/improvement-plans", {**body, "end_date": "2026-08-01"}, role="hr", status=422)
    post(api, "/hrms/improvement-plans", {**body, "employee_id": api[2]["hr"]}, role="hr", status=403)
    post(api, "/hrms/improvement-plans", body, role="employee", status=403)
    post(api, "/hrms/improvement-plans", body, role="outsider", status=401)
    plan = post(api, "/hrms/improvement-plans", body, role="hr")
    client, _, _, headers = api
    path = "/api/v1/hrms/improvement-plans/" + plan["id"]
    changed = client.patch(path, json={**body, "title": "Revised draft", "expected_version": plan["version"]}, headers=headers["hr"])
    assert changed.status_code == 200, changed.text
    assert changed.json()["title"] == "Revised draft"
    assert client.patch(path, json={**body, "expected_version": plan["version"]}, headers=headers["hr"]).status_code == 409
