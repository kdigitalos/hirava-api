# Imported database baseline

These two files were relocated from the retired Node backend without changing
their bytes. `imported-schema.sql` is used by `scripts/migrate_imported.py` only
for a new empty public schema. Do not replay it to reset an existing database.

`schema.prisma` is a historical schema reference used by the Python metadata and
inventory generators. No Prisma CLI, Node ORM or third service is needed to run
FastAPI. Runtime metadata is `app/data/imported_schema.json`.

Use Alembic and reviewed additive migrations for existing installations.
