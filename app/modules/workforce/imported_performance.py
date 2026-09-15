"""Employee-owned goals, saved appraisals and attributed peer feedback."""
from datetime import timedelta
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field
from sqlalchemy import or_

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import insert, now, rows
from app.modules.workforce.imported_attendance import calendar_date
from app.modules.workforce.imported_employee_profile import full_name
from app.modules.workforce.imported_leave import Input, staff
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api', tags=['HRMS performance'])
REFLECTION = ('keyAchievements', 'challengesOvercome', 'areasForGrowth', 'supportNeed')
RATINGS = ('Not rated', 'Needs Improvement', 'Below Expectations', 'Meets', 'Exceeds', 'Outstanding')


def date_label(value):
    return f'{value.month}/{value.day}/{value.year}' if value else None


def employee_rows(db, model, employee_id):
    tbl = table(db, model)
    return rows(db, model, tbl.c.employeeId == employee_id, order=tbl.c.createdAt.desc())


def latest_appraisal(db, employee_id, lock=False):
    items = employee_rows(db, 'PerformanceAppraisal', employee_id)
    return find(db, 'PerformanceAppraisal', items[0]['id'], lock=lock) if items else None


def feedback_item(db, row, employee_id):
    received = row['toEmployeeId'] == employee_id
    person = find(db, 'Employee', row['fromEmployeeId'] if received else row['toEmployeeId'])
    name = full_name(person)
    words = name.split()
    initials = (words[0][0] + words[-1][0] if len(words) > 1 else name[:2]).upper()
    return {'id': row['id'], 'reviewer': ('From ' if received else 'To ') + name,
        'counterpartInitials': initials, 'rating': row['rating'], 'comment': row['comment'],
        'date': date_label(row['createdAt']), 'direction': 'Received' if received else 'Given', 'sentiment': row['sentiment']}


@router.get('/performance-hub')
def hub(user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=True)
    goals = employee_rows(db, 'PerformanceGoal', employee['id'])
    active = [goal for goal in goals if goal['status'] == 'ACTIVE']
    tbl = table(db, 'PerformanceFeedback')
    feedback = rows(db, 'PerformanceFeedback', tbl.c.toEmployeeId == employee['id'], order=tbl.c.createdAt.desc())
    appraisal = latest_appraisal(db, employee['id'])
    return {'employeeName': full_name(employee), 'stats': {'activeGoals': len(active),
        'avgProgress': int(sum(goal['progress'] for goal in active) / len(active) + .5) if active else 0,
        'recentFeedbackCount': sum(item['createdAt'] >= now() - timedelta(days=30) for item in feedback),
        'appraisalStatus': appraisal['status'] if appraisal else 'Not Started'},
        'goals': [{**{key: goal[key] for key in ('id', 'title', 'description', 'progress', 'weight', 'target', 'tags', 'status')},
            'weightLabel': str(goal['weight']) + '% Weight', 'dueDate': date_label(goal['dueDate']),
            'dueDateISO': goal['dueDate'].isoformat() if goal['dueDate'] else '',
            'createdDate': date_label(goal['createdAt']), 'owner': full_name(employee), 'commentCount': 0} for goal in goals],
        'appraisal': {**{key: appraisal[key] for key in ('cycleLabel', 'periodLabel', 'status', 'selfAssessmentStatus', 'selfScore', 'managerReviewStatus')},
            'submittedAt': date_label(appraisal['submittedAt']), 'managerReviewDue': date_label(appraisal['managerReviewDue'])} if appraisal else None,
        'recentFeedback': [feedback_item(db, item, employee['id']) for item in feedback[:5]]}


class GoalInput(Input):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    progress: int | None = Field(default=None, ge=0, le=100)
    weight: int | None = Field(default=None, ge=0, le=100)
    target: str | None = Field(default=None, max_length=128)
    dueDate: str | None = None
    tags: list[str] | None = Field(default=None, max_length=12)
    status: Literal['ACTIVE', 'COMPLETED', 'ARCHIVED'] | None = None


def goal_values(body):
    values = body.model_dump(exclude_unset=True)
    if any(values.get(key) is None for key in values if key not in ('target', 'dueDate')):
        raise HTTPException(422, 'Goal fields cannot be null except target and due date')
    if 'dueDate' in values:
        values['dueDate'] = calendar_date(values['dueDate']) if values['dueDate'] else None
    if any(len(tag) > 128 for tag in values.get('tags', [])):
        raise HTTPException(422, 'Goal tags must be 128 characters or fewer')
    return values


@router.post('/performance-hub/goals', status_code=201)
def add_goal(body: GoalInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=True)
    find(db, 'Employee', employee['id'], lock=True)
    values = goal_values(body)
    if not values.get('title'):
        raise HTTPException(422, 'Enter a goal title')
    goal = insert(db, 'PerformanceGoal', {'employeeId': employee['id'], 'description': '', 'progress': 0,
        'weight': 0, 'tags': [], 'status': 'ACTIVE', **values})
    return {'ok': True, 'id': goal['id']}


@router.patch('/performance-hub/goals/{id}')
def edit_goal(id: str, body: GoalInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=True)
    find(db, 'Employee', employee['id'], lock=True)
    goal = find(db, 'PerformanceGoal', id, lock=True)
    if goal['employeeId'] != employee['id']:
        raise HTTPException(404, 'Goal not found')
    values = goal_values(body)
    if not values:
        raise HTTPException(422, 'Provide a goal change')
    if values.get('progress') == 100 and 'status' not in values:
        values['status'] = 'COMPLETED'
    update(db, 'PerformanceGoal', id, values)
    return {'ok': True}


def saved_ratings(appraisal):
    value = appraisal.get('goalRatingsJson')
    return {row['goalId']: row for row in value if isinstance(row, dict) and isinstance(row.get('goalId'), str)} if isinstance(value, list) else {}


@router.get('/performance-hub/appraisal')
def appraisal_detail(user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=False)
    appraisal = latest_appraisal(db, employee['id']) if employee else None
    if not appraisal:
        return {'appraisal': None}
    ratings = saved_ratings(appraisal)
    goals = []
    for goal in employee_rows(db, 'PerformanceGoal', employee['id']):
        if goal['status'] != 'ACTIVE':
            continue
        saved = ratings.get(goal['id'], {})
        rating = saved.get('rating', 0)
        rating = rating if isinstance(rating, int) and 0 <= rating <= 5 else 0
        goals.append({**{key: goal[key] for key in ('id', 'title', 'description', 'target', 'progress')},
            'rating': rating, 'ratingLabel': RATINGS[rating], 'comment': saved.get('comment', '')})
    reflection = {key: appraisal[key] or '' for key in REFLECTION}
    goals_done = bool(goals) and all(goal['rating'] > 0 for goal in goals)
    reflection_done = all(value.strip() for value in reflection.values())
    return {'appraisal': {**{key: appraisal[key] for key in ('cycleLabel', 'periodLabel', 'status', 'managerReviewStatus')},
        'underManagerReview': 'review' in (appraisal['status'] + appraisal['managerReviewStatus']).lower(),
        'goals': goals, 'reflection': reflection, 'completion': {'completed': int(goals_done) + int(reflection_done),
            'total': 2, 'goalsDone': goals_done, 'reflectionDone': reflection_done}}}


class GoalRating(Input):
    goalId: str = Field(min_length=1, max_length=255)
    rating: int | None = Field(default=None, ge=0, le=5)
    comment: str | None = Field(default=None, max_length=20000)


class AppraisalInput(Input):
    goalRating: GoalRating | None = None
    keyAchievements: str | None = Field(default=None, max_length=20000)
    challengesOvercome: str | None = Field(default=None, max_length=20000)
    areasForGrowth: str | None = Field(default=None, max_length=20000)
    supportNeed: str | None = Field(default=None, max_length=20000)


@router.patch('/performance-hub/appraisal')
def edit_appraisal(body: AppraisalInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=True)
    find(db, 'Employee', employee['id'], lock=True)
    appraisal = latest_appraisal(db, employee['id'], lock=True)
    if not appraisal:
        raise HTTPException(404, 'No appraisal cycle is open for you')
    if appraisal['submittedAt'] or appraisal['status'].strip().lower() in ('completed', 'approved', 'closed'):
        raise HTTPException(409, 'This appraisal has been submitted or closed and cannot be edited')
    values = {key: getattr(body, key) for key in REFLECTION if key in body.model_fields_set and getattr(body, key) is not None}
    if body.goalRating:
        goal = find(db, 'PerformanceGoal', body.goalRating.goalId)
        if goal['employeeId'] != employee['id']:
            raise HTTPException(404, 'Goal not found')
        ratings = saved_ratings(appraisal)
        rating = ratings.get(goal['id'], {'goalId': goal['id'], 'rating': 0, 'comment': ''})
        rating.update(body.goalRating.model_dump(exclude_none=True))
        ratings[goal['id']] = rating
        values['goalRatingsJson'] = list(ratings.values())
    if not values:
        raise HTTPException(422, 'Provide an appraisal change')
    update(db, 'PerformanceAppraisal', appraisal['id'], values)
    return {'ok': True}


@router.get('/performance-feedback')
def feedback(direction: str = '', user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=True)
    tbl = table(db, 'PerformanceFeedback')
    given, received = tbl.c.fromEmployeeId == employee['id'], tbl.c.toEmployeeId == employee['id']
    items = rows(db, 'PerformanceFeedback', given if direction == 'given' else received if direction == 'received' else or_(given, received), order=tbl.c.createdAt.desc())
    return {'items': [feedback_item(db, row, employee['id']) for row in items]}


class FeedbackInput(Input):
    toEmployeeId: str = Field(min_length=1, max_length=255)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=1, max_length=20000)
    sentiment: Literal['Positive', 'Negative'] | None = None


@router.post('/performance-feedback', status_code=201)
def add_feedback(body: FeedbackInput, user=Depends(staff), db=Depends(get_db)):
    employee = linked_employee(db, user, required=True)
    if employee['id'] == body.toEmployeeId:
        raise HTTPException(400, 'You cannot give feedback to yourself')
    find(db, 'Employee', body.toEmployeeId)
    row = insert(db, 'PerformanceFeedback', {**body.model_dump(), 'fromEmployeeId': employee['id']})
    return feedback_item(db, row, employee['id'])
