from datetime import date
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.employment import EmploymentEntry, employment_review, month_number, refined_review
from app.agents.application import process_one, serialized
from app.agents.models import ScreeningJob
from app.modules.recruiting.public_intake import pipeline_table
from test_screening_application import screening, BODY  # noqa: F401


def review(rows):
    entries, passages = [], {}
    for i, (company, start, end) in enumerate(rows):
        key = f"p{i}"
        passages[key] = f"{company}: Developer {start or ''} - {end or ''}"
        entries.append(EmploymentEntry(employer=company, role="Developer", start_date=start,
                                       end_date=end, resume_passage_ids=[key]))
    return employment_review(entries, passages, date(2026, 9, 20))


def test_gap_and_short_tenure_boundaries():
    result = review([("Alpha", "Jan 2020", "Jun 2020"), ("Beta", "Jan 2021", "May 2021")])
    assert [flag["kind"] for flag in result["flags"]] == ["short_tenure", "possible_gap"]
    assert "6 complete months" in result["flags"][1]["message"]
    assert result["entries"][0]["duration_months"] == 6
    assert result["entries"][1]["duration_months"] == 5
    result = review([("Alpha", "Jan 2020", "Jun 2020"), ("Beta", "Dec 2020", "May 2021")])
    assert result["flags"] == []


@pytest.mark.parametrize("start,end", [("2020", "2021"), (None, "Jan 2021"),
    ("May 2021", "Jan 2021"), ("Jan 2027", "Feb 2027"), ("01/02/2020", "Jun 2020")])
def test_uncertain_dates_do_not_create_durations_or_gaps(start, end):
    result = review([("Alpha", start, end), ("Beta", "Jan 2025", "Dec 2025")])
    assert result["entries"][0]["duration_months"] is None
    assert not result["gap_analysis_complete"]
    assert all(flag["kind"] == "unclear_dates" for flag in result["flags"])


def test_promotions_overlaps_and_current_roles():
    result = review([("Alpha", "Jan 2020", "Mar 2020"), ("Alpha", "Apr 2020", "Dec 2020"),
                     ("Beta", "Feb 2020", "Present"), ("Gamma", "Aug 2026", "Present")])
    assert result["flags"] == []
    assert result["entries"][-1]["ongoing"]
    result = review([("Alpha", "Jan 2020", "Mar 2020"), ("Alpha", "2020", "2021")])
    assert not any(flag["kind"] == "short_tenure" for flag in result["flags"])


def test_rejects_unsupported_history_and_handles_no_history():
    item = EmploymentEntry(employer="Invented", role="Developer", start_date="Jan 2020",
                           end_date="Jun 2020", resume_passage_ids=["p1"])
    result = employment_review([item], {"p1": "Developer Jan 2020 - Jun 2020"})
    assert result["rejected_count"] == 1 and result["entries"] == []
    assert not result["gap_analysis_complete"]
    assert employment_review([], {})["flags"] == []
    assert month_number("2024-02-30") is None
    assert month_number("2024-02-29") == month_number("Feb 2024")


def test_history_is_saved_without_changing_score_or_stage(screening):
    client, app, _, headers, path, calls = screening
    app.state.test_employment_history = review([("Alpha", "Jan 2020", "Feb 2020"),
                                              ("Beta", "Jan 2021", "Dec 2021")])
    queued = client.post(path, json=BODY, headers=headers["hr"]).json()
    assert process_one(app)
    saved = client.get(path, headers=headers["hr"]).json()["assessment"]
    assert saved["result"]["jd_evidence_score"] == 75
    assert len(saved["result"]["employment_history"]["flags"]) == 2
    assert len(calls) == 1
    with app.state.sessions() as db:
        assert db.get(ScreeningJob, queued["id"]).result["employment_history"] == app.state.test_employment_history
        assert db.execute(select(pipeline_table(db).c.status)).scalar_one() == ""


@pytest.mark.parametrize("role,warning", [
    ("Software Intern", False), ("Python Internship", False),
    ("Developer (fixed-term contract)", False), ("Fixed term Developer", False),
    ("Internal Systems Developer", True), ("Contract Developer", True),
    ("Developer", True),
])
def test_explicit_planned_titles_have_neutral_duration(role, warning):
    quote = f"Alpha {role} Jan 2020 - Mar 2020. Mentored an intern."
    item = EmploymentEntry(employer="Alpha", role=role, start_date="Jan 2020",
                           end_date="Mar 2020", resume_passage_ids=["p1"])
    result = employment_review([item], {"p1": quote}, date(2026, 9, 20))
    assert result["entries"][0]["duration_months"] == 3
    assert bool(result["flags"]) == warning


def test_saved_review_refresh_preserves_evidence_and_history():
    old = review([("Alpha", "Jan 2020", "Mar 2020"), ("Beta", "Jan 2021", "Feb 2021")])
    old["version"] = "employment-review-v1"
    for row in old["entries"]:
        row["role"] = "Intern"
        row["resume_quotes"] = [quote.replace("Developer", "Intern") for quote in row["resume_quotes"]]
    original = deepcopy(old)
    record = SimpleNamespace(id="test", source_hash="same", status="succeeded",
        created_at=None, finished_at=None, rubric={}, provider="test", model="test",
        error=None, result={"employment_history": old, "jd_evidence_score": 75})
    result = serialized(record, "same")["result"]
    updated = result["employment_history"]
    assert [flag["kind"] for flag in updated["flags"]] == ["possible_gap"]
    assert "not proof of unemployment" in updated["flags"][0]["message"]
    assert updated["entries"] == original["entries"]
    assert old == original and result["jd_evidence_score"] == 75
    assert serialized(record, "changed")["result"] is None
    assert refined_review(updated) == updated


def test_mixed_roles_and_ungrounded_labels_keep_warning():
    result = review([("Alpha", "Jan 2020", "Feb 2020"), ("Alpha", "Mar 2020", "Apr 2020")])
    result["entries"][0]["role"] = "Intern"
    result["entries"][0]["resume_quotes"] = ["Alpha Intern Jan 2020 Feb 2020"]
    assert refined_review(result)["flags"][0]["kind"] == "short_tenure"
    result["entries"][1]["role"] = "Intern"  # unsupported by its own source
    assert refined_review(result)["flags"][0]["kind"] == "short_tenure"
