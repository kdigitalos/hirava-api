from alembic import context
from app.core.config import Settings
from app.data.database import Base, build_engine
from app.data import registry  # noqa: F401

target_metadata = Base.metadata
settings = Settings()

if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = build_engine(settings.database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          render_as_batch=settings.database_url.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
