"""Source-backed employment timeline; review prompts never affect scores."""
import re
from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class EmploymentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    employer: str | None = Field(max_length=200)
    role: str | None = Field(max_length=200)
    start_date: str | None = Field(max_length=60)
    end_date: str | None = Field(max_length=60)
    resume_passage_ids: list[str] = Field(min_length=1, max_length=10)


EMPLOYMENT_INSTRUCTIONS = (
    "Also return employment_history with one entry per explicitly listed job, internship or contract. "
    "Do not include academic projects or education as employment. Copy employer, role, start_date "
    "and end_date exactly from cited resume passages, or use null when absent. Preserve date "
    "precision: never invent a month or expand a two-digit year. Copy Present/Current only if "
    "explicitly stated. Return [] when no work history is present. Do not infer reasons for gaps, "
    "calculate durations, judge reliability or recommend hiring/rejection."
)

MONTHS = {name: i + 1 for i, names in enumerate([
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
    ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
    ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december")]) for name in names}


def month_number(value):
    """Month precision only; year-only and ambiguous dates remain unknown."""
    if not value:
        return None
    value = value.strip().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            parsed = date.fromisoformat(value)
            return parsed.year * 12 + parsed.month - 1
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})", value)
    if match:
        year, month = map(int, match.groups())
    else:
        match = re.fullmatch(r"(\d{1,2})/(\d{4})", value)
        if match:
            month, year = map(int, match.groups())
        else:
            match = re.fullmatch(r"([a-z]+)\.?[ ,]+(\d{4})", value)
            if not match or match[1] not in MONTHS:
                return None
            year, month = int(match[2]), MONTHS[match[1]]
    return year * 12 + month - 1 if 1900 <= year <= 2200 and 1 <= month <= 12 else None


def month_label(value):
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def refined_review(review):
    """Apply current display rules to saved evidence without inference or mutation."""
    if not isinstance(review, dict) or not isinstance(review.get("entries"), list):
        return review
    entries = review["entries"]

    def planned(index):
        if not isinstance(index, int) or not 0 <= index < len(entries):
            return False
        entry = entries[index]
        role = entry.get("role") or ""
        # Only classify the cited role, never unrelated words elsewhere in a passage.
        grounded = any(" ".join(role.split()) in " ".join(quote.split())
                       for quote in entry.get("resume_quotes", []))
        return bool(grounded and re.search(
            r"\b(?:intern|internship)\b|\bfixed[\s\-–‑]+term\b", role, re.IGNORECASE))

    flags = []
    for flag in review.get("flags", []):
        indices = flag.get("entry_indices", [])
        if flag.get("kind") == "short_tenure" and indices and all(planned(i) for i in indices):
            continue
        if flag.get("kind") == "possible_gap":
            flag = {**flag, "message": flag["message"].replace(
                "Ask for context; other work or activities may be omitted from the resume.",
                "This is time between listed roles, not proof of unemployment. Education, other work or activities may be omitted from the resume.")}
        flags.append(flag)
    return {**review, "version": "employment-review-v2", "flags": flags,
            "notice": "Review prompts only; scores and hiring status are unchanged. Roles explicitly labelled as internships or fixed-term in the cited title show their duration without short-tenure warnings. Other short roles may also be planned; ask for context."}


def employment_review(items, passages, as_of=None):
    as_of = as_of or datetime.now(timezone.utc).date()
    current = as_of.year * 12 + as_of.month - 1
    entries, flags, intervals, rejected = [], [], [], 0
    for item in items:
        refs = list(dict.fromkeys(item.resume_passage_ids))
        quotes = [passages[ref] for ref in refs if ref in passages]
        texts = [" ".join(quote.split()) for quote in quotes]
        values = [item.employer, item.role, item.start_date, item.end_date]
        if len(quotes) != len(refs) or not any(values) or any(
            value is not None and (not value.strip() or not any(" ".join(value.split()) in text for text in texts))
            for value in values
        ):
            rejected += 1
            continue
        row = {key: getattr(item, key) for key in ("employer", "role", "start_date", "end_date")}
        # Duplicate extraction must not create duplicate flags.
        if any(all(previous[key] == row[key] for key in row) for previous in entries):
            continue
        index = len(entries)
        ongoing = (item.end_date or "").casefold() in ("present", "current", "ongoing", "now")
        start = month_number(item.start_date)
        end = current if ongoing else month_number(item.end_date)
        known = start is not None and end is not None and start <= end <= current
        row.update(resume_quotes=quotes, ongoing=ongoing,
                   duration_months=end - start + 1 if known else None)
        entries.append(row)
        if known:
            intervals.append((start, end, index))
        else:
            flags.append({"kind": "unclear_dates", "entry_indices": [index],
                "message": "Dates are missing, imprecise, conflicting or future-dated. Confirm the timeline before interpreting its duration."})

    # Merge overlapping/adjacent roles at the same employer before flagging short tenure.
    companies = {}
    for start, end, index in intervals:
        employer = entries[index]["employer"]
        key = " ".join(employer.casefold().split()) if employer else f"unknown:{index}"
        companies.setdefault(key, []).append((start, end, index))
    for company, spans in companies.items():
        if any(row["employer"] and " ".join(row["employer"].casefold().split()) == company
               and row["duration_months"] is None for row in entries):
            continue
        merged = []
        for start, end, index in sorted(spans):
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
                merged[-1][2].append(index)
            else:
                merged.append([start, end, [index]])
        for start, end, indices in merged:
            if end - start + 1 < 6 and not any(entries[i]["ongoing"] for i in indices):
                flags.append({"kind": "short_tenure", "entry_indices": indices,
                    "message": f"A completed employment period spans {end - start + 1} calendar months (under 6). Confirm whether this was an internship, contract or another planned short role."})

    # Unknown entries could cover apparent gaps; never call those gaps established.
    complete = len(intervals) == len(entries) and rejected == 0
    if complete:
        covered_end, covered_index = None, None
        for start, end, index in sorted(intervals):
            if covered_end is not None and start - covered_end - 1 >= 6:
                flags.append({"kind": "possible_gap", "entry_indices": [covered_index, index],
                    "message": f"The listed roles do not cover {month_label(covered_end + 1)} to {month_label(start - 1)} ({start - covered_end - 1} complete months). Ask for context; other work or activities may be omitted from the resume."})
            if covered_end is None or end > covered_end:
                covered_end, covered_index = end, index
    return refined_review({"version": "employment-review-v1", "as_of": as_of.isoformat(), "entries": entries,
            "flags": flags, "rejected_count": rejected, "gap_analysis_complete": complete and bool(entries),
            "thresholds": {"gap_months_at_least": 6, "completed_tenure_months_under": 6},
            "notice": "Review prompts only. These flags do not affect the evidence score or hiring status."})
