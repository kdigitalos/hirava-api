from decimal import Decimal
import pytest
from app.modules.payroll.engine import calculate, formula, CalculationError


COMPONENTS = [
    dict(code="BASIC", name="Basic", kind="earning", formula="GROSS * 50 / 100"),
    dict(code="HRA", name="HRA", kind="earning", formula="BASIC / 2"),
    dict(code="SPECIAL", name="Special", kind="earning", formula="GROSS - BASIC - HRA"),
]


def test_reconciliation_and_employer_separation():
    result = calculate(COMPONENTS + [dict(code="COST", name="Employer cost", kind="employer", formula="1000"),
        dict(code="RECOVERY", name="Recovery", kind="deduction", formula="500")], "42800")
    assert [r["amount"] for r in result["lines"]][:3] == ["21400.00", "10700.00", "10700.00"]
    assert result["net_before_unconfigured_deductions"] == "42300.00"
    assert result["monthly_employer_cost"] == "43800.00"
    result = calculate(COMPONENTS, "100.01")
    assert sum(Decimal(r["amount"]) for r in result["lines"]) == Decimal("100.01")


@pytest.mark.parametrize("expression", ["__import__('os')", "GROSS.__class__", "[1][0]", "2 ** 999999", "1 / 0", "UNKNOWN + 1", "1e999", "MIN()", "True", "1%2"])
def test_unsafe_or_invalid_formulas(expression):
    with pytest.raises(CalculationError):
        formula(expression, {"GROSS": Decimal(100)})


def test_calculation_rejects_invalid_totals():
    for components in [COMPONENTS[:2], [dict(code="BAD", name="Bad", kind="earning", formula="-1")],
                       COMPONENTS + [dict(code="DED", name="Deduction", kind="deduction", formula="GROSS+1")]]:
        with pytest.raises(CalculationError):
            calculate(components, "100")


def test_versions_permissions_and_effective_dates(api):
    client, app, _, headers = api
    body = dict(code="STANDARD", name="Standard", effective_from="2026-04-01", reason="Initial setup", monthly_gross="42800", components=COMPONENTS)
    base = "/api/payroll"
    assert client.get(base + "/structures").status_code == 401
    for role in ["employee", "recruiter", "manager"]:
        assert client.post(base + "/preview", json={"monthly_gross":"42800", "components": COMPONENTS}, headers=headers[role]).status_code == 403
    response = client.post(base + "/structures", json=body, headers=headers["hr"])
    assert response.status_code == 201, response.text
    original = response.json()
    assert client.post(base + "/structures", json=body, headers=headers["hr"]).status_code == 409
    second = client.post(base + "/structures", json={**body, "effective_from":"2026-10-01", "components":[dict(code="ALL", name="Gross", kind="earning", formula="GROSS")]}, headers=headers["admin"])
    assert second.status_code == 201, second.text
    for as_of, expected in [("2026-09-30", original["id"]), ("2026-10-01", second.json()["id"])]:
        result = client.post(base + f"/structures/{original['id']}/preview?monthly_gross=42800&as_of={as_of}", headers=headers["hr"])
        assert result.status_code == 200, result.text
        assert result.json()["structure_id"] == expected
    assert client.get(base + "/structures", headers=headers["outsider"]).status_code == 401
    from app.modules.payroll.models import SalaryStructure
    with app.state.sessions.begin() as db:
        other = SalaryStructure(customer_id="customer-b", created_by=original["created_by"], code="PRIVATE", name="Private", effective_from=__import__('datetime').date(2026, 1, 1), components=COMPONENTS, reason="Test")
        db.add(other)
        db.flush()
        other_id = other.id
    assert client.post(base + f"/structures/{other_id}/preview?monthly_gross=100&as_of=2026-09-01", headers=headers["hr"]).status_code == 404
    assert client.post(base + f"/structures/{original['id']}/preview?monthly_gross=-1&as_of=2026-09-01", headers=headers["hr"]).status_code == 422
    saved = client.get(base + "/structures", headers=headers["hr"]).json()
    assert len(saved) == 2
    assert next(row for row in saved if row["id"] == original["id"])["components"] == COMPONENTS
    assert client.post(base + "/preview", json={"components":COMPONENTS, "monthly_gross":"NaN"}, headers=headers["hr"]).status_code == 422
