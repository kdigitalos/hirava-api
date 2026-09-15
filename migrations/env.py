from alembic import context
from app.core.config import Settings
from app.data.database import Base, build_engine
from app.data import registry  # noqa: F401

target_metadata = Base.metadata
settings = Settings()


def include_object(obj, name, type_, reflected, compare_to):
    # Imported application storage is intentionally outside native ORM metadata.
    # Never let autogenerate propose dropping the retained helpdesk settings.
    return not (type_ == 'table' and name == 'ask_me_helpdesk_settings' and reflected and compare_to is None)

if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, compare_type=True, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = build_engine(settings.database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, include_object=include_object,
                          render_as_batch=settings.database_url.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
