"""Pytest fixtures providing isolated temporary SQLite databases and upload directories."""

from dataclasses import replace
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import database as db_module
from backend.config import settings
from backend.main import create_app
from backend.routes import tickets as tickets_route
from backend.seed import seed_demo_data


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    """Create isolated SQLite database, upload root, and seeded TestClient per test."""
    db_file = tmp_path / "test_triagedesk.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    test_engine = db_module.create_app_engine(f"sqlite:///{db_file}")
    db_module.init_db(test_engine)
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(tickets_route, "settings", replace(settings, upload_dir=upload_dir))

    with Session(test_engine) as session:
        seed_demo_data(session)

    import backend.main as main_module

    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(main_module, "init_db", lambda: db_module.init_db(test_engine))
    monkeypatch.setattr(main_module, "seed_demo_data", lambda _s: None)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
