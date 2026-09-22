"""Source-backed profile suggestions and conservative blank-field filling."""
from copy import deepcopy
import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, ValidationError
from typing import Literal


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: Literal["firstName", "lastName", "email", "mobile", "skills", "workExperience", "education"]
    value: str = Field(min_length=1, max_length=2000)
    resume_passage_ids: list[str] = Field(min_length=1, max_length=10)


PROFILE_INSTRUCTIONS = (
    "Also extract profile_fields from the resume only, independently of the job requirements: "
    "firstName, lastName, email, mobile, skills, workExperience, education. "
    "Return an empty list for missing details; never invent or infer them. "
    "Each value must be an exact contiguous excerpt of a cited resume passage, not a paraphrase. "
    "Use separate entries for different skills, jobs or qualifications. Select passages about "
    "the applicant, not referees or employer contact details. Do not treat academic projects "
    "as employment. Do not extract protected characteristics, age, health or unrelated personal data. "
    "Do not calculate tenure, complete missing dates or infer a surname."
)

LABELS = {"firstName": "First name", "lastName": "Last name", "email": "Email",
          "mobile": "Phone", "skills": "Skills", "workExperience": "Work experience", "education": "Education"}


def grounded_fields(items, passages):
    """Discard unsupported profile fields without losing a valid screening result."""
    accepted, rejected, seen = [], 0, set()
    for item in items:
        quotes = [passages[ref] for ref in dict.fromkeys(item.resume_passage_ids) if ref in passages]
        value = " ".join(item.value.split())
        valid = (len(quotes) == len(set(item.resume_passage_ids)) and
                 any(value in " ".join(quote.split()) for quote in quotes))
        if item.name in ("firstName", "lastName", "email", "mobile") and len(value) > 320:
            valid = False
        if item.name == "email":
            try:
                TypeAdapter(EmailStr).validate_python(value)
            except ValidationError:
                valid = False
        if item.name == "mobile" and (not re.fullmatch(r"[0-9+() .-]{7,30}", value) or
                                      not 7 <= len(re.sub(r"\D", "", value)) <= 15):
            valid = False
        if not valid:
            rejected += 1
            continue
        key = (item.name, value)
        if key not in seen:
            accepted.append({"name": item.name, "label": LABELS[item.name], "value": value,
                             "resume_quotes": quotes})
            seen.add(key)
    return {"fields": accepted, "rejected_count": rejected, "version": "profile-extraction-v1"}


def fill_blank_fields(existing, extracted, assessment_id):
    """Return a new compatible profile; never replace a populated field."""
    if not isinstance(existing, list):
        return existing, [], [item["name"] for item in extracted]
    updated = deepcopy(existing)
    filled, preserved = [], []
    for name in dict.fromkeys(item["name"] for item in extracted):
        entries = [item for item in extracted if item["name"] == name]
        matches = [item for item in updated if isinstance(item, dict) and item.get("name") == name]
        if any(item.get("value") is not None and str(item["value"]).strip() != "" for item in matches):
            preserved.append(name)
            continue
        values = list(dict.fromkeys(item["value"] for item in entries))
        # Conflicting identity values need human review, not an arbitrary choice.
        if name in ("firstName", "lastName", "email", "mobile") and len(values) != 1:
            preserved.append(name)
            continue
        value = (", " if name == "skills" else "\n").join(values)
        if len(value) > 10000:
            preserved.append(name)
            continue
        metadata = {"source": "resume_ai", "assessment_id": assessment_id,
                    "review_required": True}
        if matches:
            for target in matches:
                target.update(value=value, aiExtraction=metadata)
        else:
            updated.append({"name": name, "label": LABELS[name], "value": value,
                "type": "email" if name == "email" else "tel" if name == "mobile" else "text",
                "isChecked": True, "mandator": False, "aiExtraction": metadata})
        filled.append(name)
    return updated, filled, preserved
