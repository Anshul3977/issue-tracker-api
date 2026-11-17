from app.config import normalize_database_url


def test_render_postgres_url_moves_sslmode_to_connect_args() -> None:
    url, args = normalize_database_url(
        "postgres://user:p%40ss@dpg-db:5432/issue_tracker?sslmode=require"
    )
    assert url == "postgresql+asyncpg://user:p%40ss@dpg-db:5432/issue_tracker"
    assert args == {"ssl": "require"}


def test_asyncpg_url_is_unchanged_without_sslmode() -> None:
    url, args = normalize_database_url("postgresql+asyncpg://issue:issue@localhost:5432/app")
    assert url == "postgresql+asyncpg://issue:issue@localhost:5432/app"
    assert args == {}
