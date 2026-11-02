from app.foundation.db import checkpointer_dsn


def test_checkpointer_uses_psycopg_compatible_postgres_url() -> None:
    assert checkpointer_dsn("postgresql+asyncpg://user:pass@db:5432/app") == (
        "postgresql://user:pass@db:5432/app"
    )
    assert checkpointer_dsn("postgresql://user:pass@db:5432/app") == (
        "postgresql://user:pass@db:5432/app"
    )
