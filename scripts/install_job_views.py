"""Replace empty imported job stores with read-only canonical views.

Runs transactionally; refuses nonempty sources. Original empty tables are
renamed, not deleted. No person/job match is inferred by this operation.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
from app.core.config import Settings


def install(connection, customer_id):
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(428720)')
        cur.execute("SELECT relkind FROM pg_class WHERE oid='public.rms_job_openings'::regclass")
        if cur.fetchone()[0] == 'v':
            cur.execute("SELECT relkind FROM pg_class WHERE oid='public.job_openings'::regclass")
            if cur.fetchone()[0] != 'v':
                raise ValueError('Partial compatibility installation requires review')
            print('Job compatibility views already installed')
            return
        # Lock writers through the emptiness check and the complete cutover.
        cur.execute('LOCK TABLE public.rms_job_openings, public.job_openings, public.job_applications, public.job_referrals, public.rms_candidate, public.rms_candidate_form_details, public.rms_interview, public.rms_interview_schedule, public.rms_feedback IN ACCESS EXCLUSIVE MODE')
        for table in ('rms_job_openings','job_openings','job_applications','job_referrals','rms_candidate','rms_candidate_form_details','rms_interview','rms_interview_schedule','rms_feedback'):
            cur.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM public.{})').format(sql.Identifier(table)))
            if cur.fetchone()[0]:
                raise ValueError('Source data requires explicit import mapping before cutover')
        cur.execute("SELECT conname, conrelid::regclass::text FROM pg_constraint WHERE confrelid='public.job_openings'::regclass AND contype='f'")
        for constraint, table in cur.fetchall():
            if table not in ('job_applications', 'job_referrals', 'public.job_applications', 'public.job_referrals'):
                raise ValueError('Unexpected job foreign key')
            name = table.split('.')[-1]
            cur.execute(sql.SQL('ALTER TABLE public.{} DROP CONSTRAINT {}').format(sql.Identifier(name), sql.Identifier(constraint)))
            cur.execute(sql.SQL('ALTER TABLE public.{} ADD CONSTRAINT {} FOREIGN KEY (job_opening_id) REFERENCES hirava_core.requisitions(id) ON DELETE RESTRICT').format(sql.Identifier(name), sql.Identifier(constraint)))
        for table in ('rms_job_openings','job_openings'):
            cur.execute(sql.SQL('ALTER TABLE public.{} RENAME TO {}').format(sql.Identifier(table), sql.Identifier(table+'_pre_unification')))
        # Every imported read is scoped to the configured isolated customer.
        cur.execute(sql.SQL('''CREATE VIEW public.rms_job_openings AS
          SELECT a.id, r.title AS job_title,
            COALESCE(r.job_details->>'company_name','') AS company_name,
            COALESCE(u.name,'') AS recruiter,
            CASE r.status WHEN 'published' THEN 'Open' WHEN 'closed' THEN 'Close' ELSE initcap(r.status) END AS status,
            (r.job_details->>'hiring_due_date')::timestamp AS hiring_due_date,
            'job' || lpad(a.id::text, greatest(3,length(a.id::text)), '0') AS job_id,
            COALESCE(r.job_details->>'job_type','') AS job_type,
            COALESCE(r.job_details->>'work_mode','') AS work_mode,
            r.description AS job_description, COALESCE(r.job_details->>'job_link','') AS job_link,
            (r.job_details->>'budget')::double precision AS budget,
            COALESCE((r.job_details->>'no_of_openings')::integer,1) AS no_of_openings,
            r.job_details->'extra_fields' AS extra_fields,
            COALESCE(r.job_details->>'location','') AS location,
            ARRAY(SELECT c.id::varchar(100) FROM public.rms_candidate c WHERE c.job_opening_id=a.id ORDER BY c.id) AS candidate_ids,
            COALESCE(r.job_details->>'hiring_flow','') AS hiring_flow,
            ARRAY(SELECT jsonb_array_elements_text(COALESCE(r.job_details::jsonb->'required_skills','[]'::jsonb)))::varchar[] AS required_skills,
            COALESCE(owner.auth_subject,'local|' || owner.id) AS created_by,
            r.created_at::timestamp AS created_at, COALESCE((SELECT max(e.created_at) FROM hirava_core.audit_events e WHERE e.resource_id=r.id AND e.resource_type='requisitions'),r.created_at)::timestamp AS updated_at
          FROM hirava_core.requisitions r
          JOIN hirava_core.job_references a ON a.requisition_id=r.id
          JOIN hirava_core.users owner ON owner.id=r.requested_by
          LEFT JOIN hirava_core.users u ON u.id=r.job_details->>'recruiter_id'
          WHERE r.customer_id={}''').format(sql.Literal(customer_id)))
        cur.execute(sql.SQL('''CREATE VIEW public.job_openings AS
          SELECT r.id, r.title,
            (CASE upper(replace(replace(COALESCE(r.job_details->>'job_type','FULL_TIME'),'-','_'),' ','_'))
              WHEN 'PART_TIME' THEN 'PART_TIME' WHEN 'INTERNSHIP' THEN 'INTERNSHIP'
              WHEN 'CONTRACT' THEN 'CONTRACT' ELSE 'FULL_TIME' END)::public."JobOpeningType" AS type,
            COALESCE((r.job_details->>'salary_min')::double precision,0) AS salary_min,
            COALESCE((r.job_details->>'salary_max')::double precision,0) AS salary_max,
            COALESCE(r.job_details->>'company_name','') AS company,
            COALESCE(r.job_details->>'location','') AS location,
            COALESCE(r.job_details->>'department','') AS department,
            COALESCE(r.job_details->>'logo','default') AS logo,
            r.status='published' AS is_active,
            r.created_at::timestamp AS created_at, COALESCE((SELECT max(e.created_at) FROM hirava_core.audit_events e WHERE e.resource_id=r.id AND e.resource_type='requisitions'),r.created_at)::timestamp AS updated_at
          FROM hirava_core.requisitions r JOIN hirava_core.job_references a ON a.requisition_id=r.id
          WHERE r.customer_id={}''').format(sql.Literal(customer_id)))
        for table, column in [('rms_candidate','job_opening_id'), ('rms_candidate_form_details','job_opening_id'),
                              ('rms_interview','job_id'), ('rms_interview_schedule','job_id'), ('rms_feedback','job_id')]:
            cur.execute(sql.SQL('ALTER TABLE public.{} ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES hirava_core.job_references(id) ON DELETE RESTRICT').format(sql.Identifier(table), sql.Identifier(table+'_canonical_job_fk'), sql.Identifier(column)))
        print('Canonical job views and reference constraints installed; original empty tables retained')


if __name__ == '__main__':
    try:
        settings=Settings()
        with psycopg.connect(settings.database_url.replace('postgresql+psycopg://','postgresql://',1), connect_timeout=15) as conn:
            install(conn, settings.customer_id)
    except Exception as exc:
        print('Job cutover failed:', type(exc).__name__, getattr(exc,'sqlstate',None))
        sys.exit(1)
