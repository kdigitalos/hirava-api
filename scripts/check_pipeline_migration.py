"""Read-only RDS compatibility check. Prints counts/statuses, never profile data.

Run from hirava-api: .venv/Scripts/python scripts/check_pipeline_migration.py
Uses an in-process app with Node fallback disabled and an existing admin identity.
This verifies SQL/response contracts, not the external Auth0 sign-in flow.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import select
from app.core.config import Settings
from app.core.models import User
from app.core.security import current_user
from app.main import create_app


def main():
    settings = Settings()
    settings.legacy_api_url = ""
    settings.imported_storage_cleanup_enabled = False
    app = create_app(settings)
    with app.state.sessions() as db:
        user = db.scalar(select(User).where(User.customer_id == settings.customer_id,
                                           User.role == 'admin', User.active.is_(True)))
        if user is None:
            raise RuntimeError('No active administrator is available for the read-only check')
        db.expunge(user)
    app.dependency_overrides[current_user] = lambda: user
    with TestClient(app) as client:
        for path in ('/api/candidate', '/api/candidate/jobOpenings', '/api/candidate/count',
                     '/api/jobOpenings/candidate', '/api/jobOpenings/interview', '/api/jobOpenings/drops',
                     '/api/candidate/candidateNames', '/api/candidate/recent', '/api/interview',
                     '/api/interviewSchedule', '/api/feedback'):
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError(f'{path}: HTTP {response.status_code}')
            print(f'{path}: HTTP 200, records={len(response.json()["data"])}')
        response = client.get('/api/jobOpenings/interview')
        counts = {row['id']: row['noOfInterviewApp'] for row in response.json()['data']}
        candidates = client.get('/api/jobOpenings/candidate').json()['data']
        assert all(counts[row['id']] == len(row['candidates']) for row in candidates)
        print('Applicant counts match saved pipeline rows; Node fallback disabled.')
        for path in ('/api/jobOpenings', '/api/jobOpenings/active', '/api/jobOpenings/chart',
                     '/api/candidate/chart', '/api/candidate/hiringChart', '/api/dashboard/count',
                     '/api/dashboard/metrics', '/api/dashboard/chart', '/api/dashboard/detailPerformanceMetrics',
                     '/api/interview/upcomming', '/api/hiringFlow', '/api/secttionValue', '/api/template',
                     '/api/question', '/api/candidateFormDetails', '/api/asset-categories', '/api/vendors',
                     '/api/assets', '/api/assets/available', '/api/asset-assignments',
                     '/api/asset-return-requests', '/api/asset-assignments/timeline',
                     '/api/departments', '/api/job-titles', '/api/branches', '/api/employees',
                     '/api/documents', '/api/documents/stats', '/api/documents/deadlines', '/api/documents/recent-activity',
                     '/api/lost-damage-incidents', '/api/lost-damage-policy', '/api/leave-types',
                     '/api/leave-requests', '/api/leave-balances', '/api/attendance-records',
                     '/api/attendance-policies?category=LEAVE_TYPE', '/api/attendance-policy-stats',
                     '/api/attendance-tracker', '/api/attendance-tracker/reports', '/api/leave-manager',
                     '/api/admin/attendance-records', '/api/leave-attendance/logs',
                     '/api/admin/self-service-requests', '/api/onboarding-groups', '/api/onboarding-templates',
                     '/api/onboarding-candidates', '/api/probation-records', '/api/probation-records/filter-options',
                     '/api/probation-settings', '/api/employee-tasks', '/api/admin/schedule-items', '/api/privacy-policies',
                     '/api/exit-requests', '/api/exit-offboarding-templates', '/api/fnf-settlements',
                     '/api/job-openings', '/api/admin/job-openings', '/api/admin/job-applications', '/api/admin/job-referrals',
                     '/api/performance-hub/appraisal', '/api/admin/dashboard', '/api/admin/exit-dashboard', '/api/admin/onboarding-dashboard',
                     '/api/admin/support-tickets', '/api/admin/support-tickets/stats', '/api/ask-me/tickets/agents', '/api/ask-me/tickets/employees',
                     '/api/ask-me/faqs', '/api/ask-me/knowledge-base', '/api/ask-me/settings', '/api/ask-me/reports',
                     '/api/manager-mapping', '/api/reporting-hierarchy', '/api/admin/employees-pending-access', '/api/users',
                     '/api/organization/company-profile', '/api/organization/roles', '/api/organization/setup-dashboard',
                     '/api/parties', '/api/search?q=synthetic-nonexistent', '/api/health', '/api/admin/payroll-activities',
                     '/api/views/policy-stats', '/api/views/organization-roles', '/api/views/onboarding-groups', '/api/views/employee-dashboard',
                     '/api/views/employee-profile', '/api/views/ess-profile', '/api/views/my-tasks'):
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError(f'{path}: HTTP {response.status_code}')
            print(f'{path}: HTTP 200')
        employees = client.get('/api/employees').json()
        if employees:
            employee_id = employees[0]['id']
            for suffix in ('job-details', 'payroll', 'lifecycle', 'documents', 'assets', 'attendance'):
                response = client.get(f'/api/employees/{employee_id}/{suffix}')
                if response.status_code != 200:
                    raise RuntimeError(f'Employee {suffix}: HTTP {response.status_code}')
                print(f'Employee {suffix}: HTTP 200 (content withheld)')


if __name__ == '__main__':
    main()
