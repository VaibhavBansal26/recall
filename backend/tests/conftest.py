import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

# Must be set before app modules read settings.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://recall:recall@localhost:5433/recall_test"
)
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["VOICE_PROVIDER"] = "fake"
os.environ["LLM_PROVIDER"] = "fake"
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["CONFUSION_SILENCE_S"] = "0"  # silence trigger is tested explicitly
os.environ["FAKE_DELAY_S"] = "0.25"  # long enough for the barge-in test to interrupt mid-reply

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _ensure_database() -> None:
    url = make_url(TEST_DB_URL)
    admin = url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)
        ).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(str(url.database))))


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> None:
    _ensure_database()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_notes() -> None:
    url = make_url(TEST_DB_URL).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute("TRUNCATE capture_events, notes, sources, daily_briefs CASCADE")
