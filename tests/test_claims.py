from conftest import get, post


def draft(api, role="employee", **changes):
    return post(api, "/hrms/claims", {"category": "Travel", "expense_type": "Train", "expense_date": "2026-01-02",
        "amount": "123.45", "currency": "INR", "description": "Client visit", **changes}, role=role)


def act(api, claim, action, role="employee", status=200):
    return post(api, f"/hrms/claims/{claim['id']}/actions", {"action": action, "expected_version": claim["version"],
        "reason": "Reviewed receipt"}, role=role, status=status)


def test_claim_review_and_ownership(api):
    claim = draft(api)
    assert claim["amount"] == "123.45" and claim["status"] == "draft"
    assert get(api, "/hrms/claims?scope=review", role="hr") == []
    get(api, "/hrms/claims?scope=review", role="employee", status=403)
    act(api, claim, "submit", role="manager", status=403)
    pending = act(api, claim, "submit")
    assert pending["status"] == "pending"
    act(api, pending, "approve", status=403)
    act(api, pending, "approve", role="outsider", status=401)
    approved = act(api, pending, "approve", role="hr")
    assert approved["reviewed_by"] == api[2]["hr"]
    act(api, pending, "reject", role="hr", status=409)
    act(api, approved, "withdraw", status=409)
    assert get(api, "/hrms/claims", role="manager") == []
    assert get(api, "/hrms/claims", role="employee")[0]["status"] == "approved"


def test_claim_withdrawal_and_no_self_approval(api):
    claim = draft(api, role="hr")
    pending = act(api, claim, "submit", role="hr")
    act(api, pending, "approve", role="hr", status=403)
    withdrawn = act(api, pending, "withdraw", role="hr")
    assert withdrawn["status"] == "draft"
    client, _, _, headers = api
    body = {"category": "Travel", "expense_type": "Cab", "expense_date": "2026-01-02", "amount": "100",
        "currency": "INR", "description": "Client visit", "expected_version": withdrawn["version"]}
    r = client.patch(f"/api/v1/hrms/claims/{claim['id']}", json=body, headers=headers["hr"])
    assert r.status_code == 200 and r.json()["amount"] == "100.00"
    assert client.patch(f"/api/v1/hrms/claims/{claim['id']}", json=body, headers=headers["hr"]).status_code == 409


def test_claim_input_and_receipt_ownership(api):
    for amount in ["-1", "0", "123.456", "NaN"]:
        post(api, "/hrms/claims", {"category": "Travel", "expense_type": "Cab", "expense_date": "2026-01-02",
            "amount": amount, "currency": "INR", "description": "Receipt"}, role="employee", status=422)
    client, _, _, headers = api
    receipt = client.post("/api/v1/documents?domain=hrms", files={"file": ("receipt.txt", b"synthetic receipt")}, headers=headers["manager"])
    assert receipt.status_code == 201
    assert client.get(f"/api/v1/documents/{receipt.json()['id']}", headers=headers["manager"]).status_code == 200
    assert client.get(f"/api/v1/documents/{receipt.json()['id']}", headers=headers["employee"]).status_code == 404
    post(api, "/hrms/claims", {"category": "Travel", "expense_type": "Cab", "expense_date": "2026-01-02",
        "amount": "10", "currency": "INR", "description": "Receipt", "receipt_id": receipt.json()["id"]}, role="employee", status=403)
