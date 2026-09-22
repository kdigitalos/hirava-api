"""Synthetic provider doubles test validation, never stand in for real app results."""
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph", reason="Install the optional ai extra to test the pilot")

from app.agents.pilot import extract_text
from app.agents.screening import (Findings, OpenAIProvider, ProviderResult, ScreeningError,
                                  ScreeningInput, build_screening_graph)
from app.core.config import Settings
from app.agents.screening import (GroqProvider, create_provider, PassageFindings,
                                  assessment_payload, resolve_passages)


def source():
    return ScreeningInput(
        resume_text="Developed Python APIs for an internal inventory project. Wrote unit tests and documented the API.",
        job_description="The role requires Python API development and SQL experience. Work with the engineering team.",
        rubric_version="synthetic-v1",
        criteria=[{"id": "python", "description": "Python API development", "jd_quote": "Python API development", "weight": 3},
                  {"id": "sql", "description": "SQL experience", "jd_quote": "SQL experience", "weight": 1}],
    )


def findings():
    return [{"criterion_id": "python", "status": "evidenced", "resume_quotes": ["Developed Python APIs"],
             "explanation": "Resume describes Python API work; human review is required."},
            {"criterion_id": "sql", "status": "not_evidenced", "resume_quotes": [],
             "explanation": "No SQL evidence in the supplied text; skill is unknown."}]


def run(items):
    class FakeProvider:
        def assess(self, _):
            return ProviderResult(assessment=Findings(findings=items), model="synthetic-test-only",
                                  response_id="test", input_tokens=10, output_tokens=20)
    return build_screening_graph(FakeProvider()).invoke({"source": source()})["result"]


def passage_findings():
    return PassageFindings(employment_history=[], profile_fields=[{"name": "skills", "value": "Python", "resume_passage_ids": ["p1"]}], findings=[
        {"criterion_id": item["criterion_id"], "status": item["status"],
         "explanation": item["explanation"],
         "resume_passage_ids": ["p1"] if item["resume_quotes"] else []}
        for item in findings()])


def test_passage_resolution_preserves_pdf_text_and_rejects_unknown_references():
    data = source().model_copy(update={"resume_text": "Built Python APIs — café\nUsed SQL\n" + "x" * 1200})
    payload, passages = assessment_payload(data)
    assert "resume_text" not in payload
    assert all(text in data.resume_text for text in passages.values())
    result = resolve_passages(passage_findings(), passages)
    assert result.findings[0].resume_quotes == ["Built Python APIs — café"]
    invalid = passage_findings()
    invalid.findings[0].resume_passage_ids = ["p999"]
    with pytest.raises(ScreeningError, match="unknown resume passage"):
        resolve_passages(invalid, passages)


def test_weighted_evidence_score_and_provenance():
    result = run(findings())
    assert result["jd_evidence_score"] == 75
    assert result["resume_score"] is None
    assert result["human_review_required"]
    assert result["status"] == "needs_review"
    assert len(result["input_sha256"]) == 64


@pytest.mark.parametrize("status", ["evidenced", "partially_evidenced", "not_evidenced"])
def test_summary_distinguishes_evidence_from_unknown_skills(status):
    items = findings()
    items[0]["status"] = status
    if status == "not_evidenced":
        items[0]["resume_quotes"] = []
    result = run(items)
    lines = result["candidate_summary"]
    assert len(lines) == 3
    index = ["evidenced", "partially_evidenced", "not_evidenced"].index(status)
    assert "python" in lines[index]["criterion_ids"]
    assert all("python" not in line["criterion_ids"] for i, line in enumerate(lines) if i != index)
    assert "sql" in lines[2]["criterion_ids"]
    assert "does not mean the candidate lacks" in lines[2]["text"]
    assert all("\n" not in line["text"] for line in lines)


def test_legacy_summary_does_not_mutate_history_and_stale_result_stays_hidden():
    from app.agents.application import serialized
    result = run(findings())
    del result["candidate_summary"]
    del result["summary_version"]
    record = SimpleNamespace(id="test", source_hash="same", status="needs_review",
        created_at=None, finished_at=None, rubric={}, provider="test", model="test",
        result=result, error=None)
    shown = serialized(record, "same")
    assert len(shown["result"]["candidate_summary"]) == 3
    assert "candidate_summary" not in record.result
    assert serialized(record, "changed")["result"] is None


def test_no_evidence_does_not_fabricate_zero_score():
    items = findings()
    items[0].update(status="not_evidenced", resume_quotes=[])
    result = run(items)
    assert result["status"] == "insufficient_evidence"
    assert result["jd_evidence_score"] is None


@pytest.mark.parametrize("bad_quote", ["Managed Kubernetes clusters", "", "API"])
def test_rejects_invented_or_empty_evidence(bad_quote):
    items = findings()
    items[0]["resume_quotes"] = [bad_quote]
    with pytest.raises(ScreeningError):
        run(items)


def test_rejects_missing_and_duplicate_criteria():
    for items in [findings()[:1], [findings()[0], findings()[0]]]:
        with pytest.raises(ScreeningError):
            run(items)


def test_rubric_must_reference_real_jd():
    data = source().model_dump()
    data["criteria"][0]["jd_quote"] = "Invented requirement"
    with pytest.raises(ValueError):
        ScreeningInput(**data)


def test_disabled_or_unconfigured_provider_never_calls_network():
    with pytest.raises(ScreeningError, match="disabled"):
        OpenAIProvider(Settings(_env_file=None, environment="test", jwt_secret="synthetic-test-secret-" * 3,
                                ai_screening_enabled=False, openai_api_key="", openai_screening_model=""))
    with pytest.raises(ScreeningError, match="Configure"):
        OpenAIProvider(Settings(_env_file=None, environment="test", jwt_secret="synthetic-test-secret-" * 3,
                                ai_screening_enabled=True, openai_api_key="", openai_screening_model=""))


def test_extraction_rejects_empty_and_unsupported_files(tmp_path):
    empty = tmp_path / "scan.txt"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ScreeningError, match="Insufficient"):
        extract_text(empty)
    unsupported = tmp_path / "resume.html"
    unsupported.write_text("x" * 100, encoding="utf-8")
    with pytest.raises(ScreeningError, match="Supported"):
        extract_text(unsupported)


def test_provider_uses_structured_output_without_remote_storage():
    captured = {}
    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed", output_parsed=passage_findings(),
                               model="test", id="test", usage=None)
    provider = object.__new__(OpenAIProvider)
    provider.model = "configured-model"
    provider.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    response = provider.assess(source())
    assert response.model == "test"
    assert response.profile_extraction["fields"][0]["value"] == "Python"
    assert response.employment_history["version"] == "employment-review-v2"
    assert captured["store"] is False
    assert captured["model"] == "configured-model"
    assert captured["text_format"] is PassageFindings


def test_provider_errors_do_not_leak_payloads():
    def parse(**kwargs):
        raise RuntimeError("secret-token and private resume")
    provider = object.__new__(OpenAIProvider)
    provider.model = "test"
    provider.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(ScreeningError) as exc:
        provider.assess(source())
    assert "secret-token" not in str(exc.value)


@pytest.mark.parametrize("finish,content,refusal,valid", [
    ("stop", passage_findings().model_dump_json(), None, True),
    ("length", "{}", None, False),
    ("stop", "not json", None, False),
    ("stop", "{}", "refused", False),
])
def test_groq_structured_output_and_failure_handling(finish, content, refusal, valid):
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content=content, refusal=refusal)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=message)],
                               model="groq-test-model", id="test", usage=None)
    provider = object.__new__(GroqProvider)
    provider.model = "groq-test-model"
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    if valid:
        result = provider.assess(source())
        assert result.provider == "groq"
        assert result.profile_extraction["fields"][0]["value"] == "Python"
        assert result.employment_history["entries"] == []
    else:
        with pytest.raises(ScreeningError):
            provider.assess(source())
    assert captured["response_format"]["json_schema"]["strict"] is True


def test_groq_selection_uses_only_groq_credentials(monkeypatch):
    captured = {}
    import openai
    def client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(openai, "OpenAI", client)
    settings = Settings(_env_file=None, environment="test", jwt_secret="synthetic-test-" * 4,
                        ai_screening_enabled=True, ai_screening_provider="groq",
                        groq_api_key="synthetic-groq", groq_screening_model="openai/gpt-oss-120b",
                        openai_api_key="synthetic-openai")
    provider = create_provider(settings)
    assert isinstance(provider, GroqProvider)
    assert captured["api_key"] == "synthetic-groq"
    assert captured["base_url"] == "https://api.groq.com/openai/v1"
    assert captured["max_retries"] == 0
    provider.close()


def test_missing_groq_key_does_not_fall_back():
    settings = Settings(_env_file=None, environment="test", jwt_secret="synthetic-test-" * 4,
                        ai_screening_enabled=True, ai_screening_provider="groq",
                        groq_api_key="", groq_screening_model="openai/gpt-oss-120b",
                        openai_api_key="synthetic-openai")
    with pytest.raises(ScreeningError, match="GROQ_API_KEY"):
        create_provider(settings)


@pytest.mark.parametrize("provider_class", [OpenAIProvider, GroqProvider])
def test_generated_criteria_provider_contract(provider_class):
    from app.agents.screening import GeneratedCriteria
    captured = {}
    criteria = GeneratedCriteria(criteria=source().criteria)
    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed", output_parsed=criteria, model="test", id="gen", usage=None)
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            refusal=None, content=criteria.model_dump_json()))], model="test", id="gen", usage=None)
    provider = object.__new__(provider_class)
    provider.model = "test"
    provider.client = SimpleNamespace(responses=SimpleNamespace(parse=parse),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = provider.generate_criteria(source().job_description)
    assert all(item["weight"] == 1 for item in result["criteria"])
    assert result["response_id"] == "gen"
    import json
    assert source().resume_text not in json.dumps(captured, default=str)
    if provider_class is OpenAIProvider:
        assert captured["store"] is False


@pytest.mark.parametrize("kind", ["empty", "invented", "duplicate"])
def test_invalid_automatic_criteria_are_rejected(kind):
    from app.agents.screening import validated_criteria
    items = [c.model_dump() for c in source().criteria]
    if kind == "empty":
        items = []
    elif kind == "invented":
        items[0]["jd_quote"] = "Invented requirement"
    else:
        items[1]["jd_quote"] = items[0]["jd_quote"]
    with pytest.raises(ValueError):
        validated_criteria(source().job_description, {"criteria": items})
