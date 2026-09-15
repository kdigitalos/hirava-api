"""RMS charts computed from saved records, without the Node service."""
import calendar
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Query

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.modules.recruiting.pipeline_api import candidates_query, profile, read
from app.modules.recruiting.pipeline_interviews import as_dict, interview_table, scoped
from app.modules.recruiting.pipeline_jobs import all_jobs, utc
from app.modules.recruiting.public_intake import pipeline_table

router = APIRouter(prefix='/api', tags=['RMS analytics compatibility'])
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
Period = Literal['week', 'month', 'year']


def candidate_rows(db, user):
    return [dict(row) for row in db.execute(candidates_query(pipeline_table(db), user)).mappings()]


def interview_rows(db, user, schedule=False):
    table = interview_table(db, schedule)
    return [as_dict(table, row) for row in db.execute(scoped(table, user)).mappings()]


def in_window(value, start=None, end=None):
    value = utc(value)
    return value is not None and (start is None or value >= start) and (end is None or value < end)


def rolling(priority):
    return datetime.now(UTC) - timedelta(days={'week': 7, 'month': 30, 'year': 365}[priority]) if priority else None


def date_window(start, end):
    try:
        first = datetime.combine(date.fromisoformat(start), datetime.min.time(), UTC)
        last = datetime.combine(date.fromisoformat(end), datetime.min.time(), UTC) + timedelta(days=1)
    except (ValueError, TypeError):
        raise HTTPException(422, 'Enter valid start and end dates (YYYY-MM-DD)') from None
    if first >= last:
        raise HTTPException(422, 'End date must be on or after start date')
    return first, last


def shift_month(value, n):
    months = value.year * 12 + value.month - 1 + n
    year, month = divmod(months, 12)
    return value.replace(year=year, month=month + 1,
                         day=min(value.day, calendar.monthrange(year, month + 1)[1]))


def period_window(priority, now=None):
    now = now or datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if priority == 'month':
        start = today.replace(day=1)
        return start, shift_month(start, 1), shift_month(start, -1)
    if priority == 'year':
        start = today.replace(month=1, day=1)
        return start, start.replace(year=start.year + 1), start.replace(year=start.year - 1)
    if priority == 'week':
        return now - timedelta(days=7), now, now - timedelta(days=14)
    start = today - timedelta(days=1 if priority == 'yesterday' else 0)
    return start, start + timedelta(days=1), start - timedelta(days=1)


def change(current, previous):
    return 100 if previous == 0 and current else 0 if previous == 0 else (current - previous) / previous * 100


@router.get('/candidate/chart')
def candidate_chart(priority: Period | None = None, user=Depends(read), db=Depends(get_db)):
    counts = Counter((row['status'] or 'Unassessed') for row in candidate_rows(db, user)
                     if in_window(row['created_at'], rolling(priority)))
    return {'data': [{'status': key, 'count': value} for key, value in sorted(counts.items())]}


@router.get('/jobOpenings/chart')
def jobs_chart(priority: Period | None = None, user=Depends(read), db=Depends(get_db)):
    counts = Counter(row['status'] for row in all_jobs(db, user) if in_window(row['createdAt'], rolling(priority)))
    return {'data': [{'name': key, 'count': value} for key, value in sorted(counts.items())]}


@router.get('/candidate/hiringChart')
def hiring_chart(id: int | None = Query(None, gt=0), priority: Period = 'week', user=Depends(read), db=Depends(get_db)):
    now = datetime.now(IST)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if priority == 'week':
        start = today - timedelta(days=(today.weekday() + 1) % 7)
        end = start + timedelta(days=7)
        labels = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    elif priority == 'month':
        start = today.replace(day=1)
        end = shift_month(start, 1)
        labels = [(start + timedelta(days=i)).date().isoformat() for i in range((end - start).days)]
    else:
        start = today.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
        labels = list(calendar.month_abbr)[1:]
    counts = [0] * len(labels)
    for row in candidate_rows(db, user):
        if (row['status'] or '').lower() != 'selected' or (id is not None and row['job_opening_id'] != id):
            continue
        if in_window(row['updated_at'], start, end):
            when = utc(row['updated_at']).astimezone(IST)
            index = (when.weekday() + 1) % 7 if priority == 'week' else when.day - 1 if priority == 'month' else when.month - 1
            counts[index] += 1
    return {'data': [{'label': label, 'count': counts[i]} for i, label in enumerate(labels)], 'period': priority}


@router.get('/dashboard/count')
def dashboard_count(startDate: str | None = None, endDate: str | None = None, user=Depends(read), db=Depends(get_db)):
    start, end, previous = None, None, None
    if startDate and startDate != 'all' and endDate:
        start, end = date_window(startDate, endDate)
        previous = start - (end - start)
    groups = ([row['createdAt'] for row in all_jobs(db, user)],
              [row['created_at'] for row in candidate_rows(db, user)],
              [row['createdAt'] for row in interview_rows(db, user)])
    totals, changes = [], []
    for dates in groups:
        current = sum(in_window(value, start, end) for value in dates)
        before = sum(in_window(value, previous, start) for value in dates) if previous else 0
        totals.append(current)
        changes.append(f'{math.floor(max(-100, min(100, change(current, before))) + .5)}%')
    return dict(zip(('totalJobsCreated', 'totalCandidatesApplied', 'totalInterviewsPending',
                     'jobsCreatedPercentIncrease', 'candidatesAppliedPercentIncrease', 'interviewsPendingPercentIncrease'), totals + changes))


@router.get('/dashboard/metrics')
def metrics(priority: Literal['today', 'yesterday', 'week', 'month', 'year'] = 'today', user=Depends(read), db=Depends(get_db)):
    start, end, previous = period_window(priority)
    people = candidate_rows(db, user)
    slots = interview_rows(db, user) + interview_rows(db, user, True)
    groups = {'totalApplications': [row['created_at'] for row in people],
              'totalHiredCandidates': [row['created_at'] for row in people if row['status'] == 'Selected'],
              'totalInterviews': [row['createdAt'] for row in slots]}
    result = {}
    for key, dates in groups.items():
        value = sum(in_window(item, start, end) for item in dates)
        before = sum(in_window(item, previous, start) for item in dates)
        result[key] = {'value': value, 'change': change(value, before)}
    return result


@router.get('/dashboard/chart')
def dashboard_chart(status: Literal['created', 'applied', 'completed'] | None = None,
                    startDate: str | None = None, endDate: str | None = None, user=Depends(read), db=Depends(get_db)):
    now = datetime.now(UTC)
    try:
        year = date.fromisoformat(startDate).year if startDate and startDate != 'all' else now.year
    except ValueError:
        raise HTTPException(422, 'Enter a valid start date') from None
    counts = [0] * 12
    for row in all_jobs(db, user):
        due = row['hiringDueDate']
        if status == 'completed' and (due is None or due > now):
            continue
        if status in {'created', 'applied'} and (due is None or due < now or bool(row['candidateIds']) != (status == 'applied')):
            continue
        if row['createdAt'].year == year:
            counts[row['createdAt'].month - 1] += 1
    return {'data': [{'name': name, 'value': counts[i]} for i, name in enumerate(list(calendar.month_name)[1:])]}


@router.get('/dashboard/detailPerformanceMetrics')
def recruiter_metrics(startDate: str | None = None, endDate: str | None = None,
                      priority: Literal['today', 'yesterday', 'weekly', 'monthly', 'yearly'] | None = None,
                      user=Depends(read), db=Depends(get_db)):
    now = datetime.now(UTC)
    if startDate and endDate:
        start, end = date_window(startDate, endDate)
    elif priority in {'today', 'yesterday'}:
        start, end, _ = period_window(priority, now)
    else:
        start = now - timedelta(days=7) if priority == 'weekly' else shift_month(now, -12 if priority == 'yearly' else -1 if priority == 'monthly' else -3)
        if priority:
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    recruiters = defaultdict(set)
    for row in all_jobs(db, user):
        if row['recruiter'] and in_window(row['createdAt'], start, end):
            recruiters[row['recruiter']].add(row['id'])
    people, interviews = candidate_rows(db, user), interview_rows(db, user)
    result = []
    for name, aliases in recruiters.items():
        candidates = [row for row in people if row['job_opening_id'] in aliases and in_window(row['created_at'], start, end)]
        hired = sum(row['status'] == 'Selected' for row in candidates)
        result.append({'name': name, 'jobs': len(aliases), 'candidates': len(candidates),
                       'interviews': sum(row['jobId'] in aliases and in_window(row['createdAt'], start, end) for row in interviews),
                       'successRate': str(math.floor(hired / len(aliases) * 100 + .5))})
    return result


@router.get('/interview/upcomming')
def upcoming(priority: Literal['day', 'week', 'month'] | None = None, user=Depends(read), db=Depends(get_db)):
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) if priority == 'day' else now
    end = start + timedelta(days=1) if priority == 'day' else start + timedelta(days=7) if priority == 'week' else shift_month(start, 1) if priority == 'month' else None
    people = {row['id']: row for row in candidate_rows(db, user)}
    titles = {row['id']: row['jobTitle'] for row in all_jobs(db, user)}
    result = []
    for row in interview_rows(db, user) + interview_rows(db, user, True):
        if not in_window(row['interviewDate'], start, end):
            continue
        person = people.get(row['candidateId'])
        fields = profile(person) if person and person['job_opening_id'] == row['jobId'] else {}
        result.append({'candidateName': ' '.join(str(fields.get(key) or '') for key in ('firstName', 'lastName')).strip(),
                       'jobTitle': titles.get(row['jobId']), 'interviewDate': row['interviewDate'],
                       'interviewTime': row['interviewTime'], 'panelMembers': row['panelMembers']})
    return {'data': sorted(result, key=lambda row: (utc(row['interviewDate']), row['interviewTime'] or ''))}
