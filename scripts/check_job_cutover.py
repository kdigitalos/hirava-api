"""Read-only job migration preflight; prints counts, never candidate payloads."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from app.core.config import Settings


QUERIES = {
    'rms_jobs': 'SELECT count(*) FROM public.rms_job_openings',
    'employee_board_jobs': 'SELECT count(*) FROM public.job_openings',
    'native_requisitions': 'SELECT count(*) FROM hirava_core.requisitions',
    'rms_candidates': 'SELECT count(*) FROM public.rms_candidate',
    'rms_forms': 'SELECT count(*) FROM public.rms_candidate_form_details',
    'rms_interviews': 'SELECT count(*) FROM public.rms_interview',
    'rms_schedules': 'SELECT count(*) FROM public.rms_interview_schedule',
    'employee_applications': 'SELECT count(*) FROM public.job_applications',
    'employee_referrals': 'SELECT count(*) FROM public.job_referrals',
    'candidate_job_orphans': 'SELECT count(*) FROM public.rms_candidate c LEFT JOIN public.rms_job_openings j ON j.id=c.job_opening_id WHERE j.id IS NULL',
    'form_job_orphans': 'SELECT count(*) FROM public.rms_candidate_form_details c LEFT JOIN public.rms_job_openings j ON j.id=c.job_opening_id WHERE j.id IS NULL',
    'interview_job_orphans': 'SELECT count(*) FROM public.rms_interview i LEFT JOIN public.rms_job_openings j ON j.id=i.job_id WHERE j.id IS NULL',
    'schedule_job_orphans': 'SELECT count(*) FROM public.rms_interview_schedule i LEFT JOIN public.rms_job_openings j ON j.id=i.job_id WHERE j.id IS NULL',
}


def main():
    url = Settings().database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
    with psycopg.connect(url, connect_timeout=15) as connection:
        connection.read_only = True
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '20s'")
            counts = {}
            for name, query in QUERIES.items():
                cursor.execute(query)
                counts[name] = cursor.fetchone()[0]
            cursor.execute("SELECT relkind='v' FROM pg_class WHERE oid='public.rms_job_openings'::regclass")
            installed = cursor.fetchone()[0]
    print(json.dumps({'counts': counts, 'inspection_only': True, 'compatibility_views_installed': installed,
                      'note': 'Read-only counts; this command performs no migration.'}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Preflight failed:', type(exc).__name__, getattr(exc, 'sqlstate', None))
        sys.exit(1)
