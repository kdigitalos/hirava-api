"""Rehearse the job cutover and relationships, then roll back every change."""
from pathlib import Path
import sys
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.core.models import User
from app.data.database import build_engine
from app.modules.organization.models import OrganizationUnit, Position
from app.modules.recruiting.models import JobReference, Requisition
from install_job_views import install


def main():
    settings = Settings()
    engine = build_engine(settings.database_url)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            # Materialize the SQLAlchemy transaction before using its driver.
            connection.execute(text('SELECT 1'))
            install(connection.connection.driver_connection, settings.customer_id)
            db = Session(bind=connection, join_transaction_mode='create_savepoint')
            user = User(customer_id=settings.customer_id, name='Synthetic view test',
                        email=f'job-view-{uuid4().hex}@example.com', role='recruiter')
            unit = OrganizationUnit(customer_id=settings.customer_id, name='Synthetic unit', kind='department')
            db.add_all([user,unit]); db.flush()
            position = Position(customer_id=settings.customer_id, title='Synthetic position', unit_id=unit.id, capacity=2)
            db.add(position); db.flush()
            job = Requisition(customer_id=settings.customer_id, title='Synthetic canonical job', description='Test only',
                              requested_by=user.id, position_id=position.id, status='published',
                              job_details={'budget':'12345.67','salary_min':'100.25','salary_max':'200.75','currency':'INR',
                                           'required_skills':['Python'],'no_of_openings':2,'job_type':'FULL_TIME'})
            db.add(job); db.flush()
            alias = JobReference(requisition_id=job.id); db.add(alias); db.flush()
            row=connection.execute(text('SELECT job_title,budget,required_skills FROM public.rms_job_openings WHERE id=:id'),{'id':alias.id}).one()
            assert row[0]==job.title and abs(row[1]-12345.67)<0.0001 and row[2]==['Python']
            row=connection.execute(text('SELECT title,is_active,salary_min FROM public.job_openings WHERE id=:id'),{'id':job.id}).one()
            assert row[0]==job.title and row[1] is True and row[2]==100.25
            candidate=connection.execute(text("INSERT INTO public.rms_candidate (job_opening_id,object) VALUES (:id,'{}') RETURNING id"),{'id':alias.id}).scalar_one()
            assert str(candidate) in connection.execute(text('SELECT candidate_ids FROM public.rms_job_openings WHERE id=:id'),{'id':alias.id}).scalar_one()
            connection.execute(text('INSERT INTO public.rms_interview (job_id,candidate_id,interview_date) VALUES (:job,:candidate,now())'),{'job':alias.id,'candidate':candidate})
            assert connection.execute(text('SELECT count(*) FROM public.rms_interview i JOIN public.rms_job_openings j ON j.id=i.job_id WHERE j.id=:id'),{'id':alias.id}).scalar_one()==1
            # Enforce references and read-only derived views at the database boundary.
            for statement in ["INSERT INTO public.rms_candidate (job_opening_id) VALUES (-123)",
                              "UPDATE public.rms_job_openings SET job_title='Forbidden' WHERE id=:id",
                              "UPDATE public.job_openings SET title='Forbidden' WHERE id=:uuid"]:
                savepoint = connection.begin_nested()
                try:
                    connection.execute(text(statement),{'id':alias.id,'uuid':job.id})
                except Exception as exc:
                    assert getattr(getattr(exc,'orig',None),'sqlstate',None) in {'23503','55000'}
                    savepoint.rollback()
                else:
                    savepoint.rollback()
                    raise AssertionError('Expected database protection')
            db.close()
            print('Both job views, decimal amounts, candidate/interview links, orphan rejection and read-only protection verified')
        finally:
            transaction.rollback()
            print('All rehearsal changes rolled back')
    engine.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Verification failed:',type(exc).__name__,getattr(getattr(exc,'orig',None),'sqlstate',None))
        sys.exit(1)
