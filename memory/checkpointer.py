"""LangGraph Postgres checkpointer wiring lives here (Phase 7).

Checkpoint tables are created by Alembic revision `001_initial_schema`, which
seeds `checkpoint_migrations` to match `langgraph.checkpoint.postgres.base.MIGRATIONS`.
`AsyncPostgresSaver.setup()` is therefore unnecessary after migrations, but safe
if called on an already-migrated database.
"""
