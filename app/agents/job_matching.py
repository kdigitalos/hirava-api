"""Tenant-scoped talent rediscovery using saved skill evidence; no provider I/O."""
import re
from sqlalchemy import inspect, select

from app.data.database import utcnow
from app.modules.recruiting.models import JobReference, Requisition
from app.modules.recruiting.public_intake import pipeline_table


SKILLS = {
    "Python": ["python"], "Django": ["django"], "Flask": ["flask"], "FastAPI": ["fastapi"],
    "SQL": ["sql"], "PostgreSQL": ["postgresql", "postgres"], "MySQL": ["mysql"],
    "JavaScript": ["javascript"], "TypeScript": ["typescript"], "React": ["react", "reactjs", "react.js"],
    "Node.js": ["node.js", "nodejs"], "Java": ["java"], "C++": ["c++"], "C#": ["c#"],
    ".NET": [".net", "dotnet"], "Git": ["git"], "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws", "amazon web services"], "Azure": ["azure"], "GCP": ["gcp", "google cloud"],
    "REST APIs": ["rest api", "rest apis", "restful api", "restful apis"],
    "HTML": ["html"], "CSS": ["css"], "Linux": ["linux"], "MongoDB": ["mongodb"],
    "Redis": ["redis"], "Excel": ["excel"], "Power BI": ["power bi"], "Tableau": ["tableau"],
    "Salesforce": ["salesforce"], "Figma": ["figma"], "Communication": ["communication"],
    "Project management": ["project management"], "Accounting": ["accounting"],
}


def contains(text, term):
    return bool(re.search(r"(?<![\w+#])" + re.escape(term) + r"(?![\w+#])", text, re.I))


def aliases(term):
    for name, variants in SKILLS.items():
        if term.casefold() in [name.casefold(), *variants]:
            return variants
    return [term]


def fields(row):
    return {item.get("name"): item.get("value") for item in (row["object"] or [])
            if isinstance(item, dict)} if isinstance(row["object"], list) else {}


def recommendations(db, job):
    explicit = (job.job_details or {}).get("required_skills", [])
    required = list(dict.fromkeys(value.strip() for value in explicit if isinstance(value, str) and value.strip())) if isinstance(explicit, list) else []
    method = "required_skills" if required else "description_skill_mentions"
    if not required:
        required = [name for name, variants in SKILLS.items() if any(contains(job.description, term) for term in variants)]
    unique = {}
    for skill in required:
        key = tuple(aliases(skill.lower()))
        unique.setdefault(key, skill)
    required = list(unique.values())
    result = {"generated_at": utcnow().isoformat(), "method": method, "required_skills": required,
              "candidates": [], "scanned_profiles": 0, "profiles_without_skills": 0,
              "pool_truncated": False, "matching_candidates": 0,
              "notice": "Skill overlap is a discovery aid, not a hiring suitability score. Verify current skills, availability and interest."}
    if not required:
        result["notice"] = "Add Required skills to this job to get candidate recommendations."
        return result
    table = pipeline_table(db)
    if not inspect(db.connection()).has_table(table.name, schema=table.schema):
        result["notice"] = "No saved recruitment profiles are available yet."
        return result
    target_alias = db.scalar(select(JobReference.id).where(JobReference.requisition_id == job.id))
    target_emails = set()
    for row in db.execute(select(table).where(table.c.job_opening_id == target_alias)).mappings():
        email = fields(row).get("email")
        if isinstance(email, str) and email.strip():
            target_emails.add(email.strip().casefold())
    query = (select(table).join(JobReference, JobReference.id == table.c.job_opening_id)
             .join(Requisition, Requisition.id == JobReference.requisition_id)
             .where(Requisition.customer_id == job.customer_id, Requisition.id != job.id)
             .order_by(table.c.updated_at.desc(), table.c.id.desc()).limit(5001))
    pool = db.execute(query).mappings().all()
    result["pool_truncated"] = len(pool) > 5000
    by_person = {}
    for row in pool[:5000]:
        data = fields(row)
        email = data.get("email", "")
        email = email.strip().casefold() if isinstance(email, str) else ""
        if email and email in target_emails:
            continue
        result["scanned_profiles"] += 1
        skill_text = data.get("skills", "")
        if not isinstance(skill_text, str) or not skill_text.strip():
            result["profiles_without_skills"] += 1
            continue
        matched = [skill for skill in required if any(contains(skill_text, term) for term in aliases(skill))]
        if not matched:
            continue
        name = " ".join(str(data.get(key) or "").strip() for key in ("firstName", "lastName")).strip()
        candidate = {"candidate_id": row["id"], "source_job_id": row["job_opening_id"],
            "name": name or "Unnamed candidate", "matched_skills": matched,
            "missing_skills": [skill for skill in required if skill not in matched],
            "skill_evidence": skill_text, "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "source_status": row["status"] or "Unassessed"}
        key = email or f"candidate:{row['id']}"
        if key not in by_person or len(matched) > len(by_person[key]["matched_skills"]):
            by_person[key] = candidate
    ranked = sorted(by_person.values(), key=lambda item: (-len(item["matched_skills"]),
                                                         -(item["candidate_id"])))
    result["matching_candidates"] = len(ranked)
    result["candidates"] = ranked[:20]
    return result
