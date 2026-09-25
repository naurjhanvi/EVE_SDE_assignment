import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DB = Path("test_eve_healthcare.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-change-me"

from app import config, database

config.settings.database_url = os.environ["DATABASE_URL"]
config.settings.jwt_secret_key = os.environ["JWT_SECRET_KEY"]
database.engine = database.create_engine(config.settings.database_url, connect_args={"check_same_thread": False})
database.SessionLocal.configure(bind=database.engine)

import app.main as main
from app.database import Base
from app.seed import seed_catalog
from app.rate_limit import _consume_local, _local_lock, _local_windows


@pytest.fixture()
def client(monkeypatch):
    with _local_lock:
        _local_windows.clear()
    # Keep normal API tests isolated from a running Redis instance and from
    # rate-limit counters left by previous test cases.
    monkeypatch.setattr(main, "consume_request_limit", _consume_local)
    Base.metadata.drop_all(bind=database.engine)
    Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        seed_catalog(db)
    with TestClient(main.app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=database.engine)
    database.engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture()
def auth_headers(client):
    response = client.post("/auth/signup", json={"name": "Asha Rao", "email": "asha@example.com", "password": "correct-horse-8"})
    assert response.status_code == 201
    token = client.post("/auth/login", json={"email": "asha@example.com", "password": "correct-horse-8"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def booking_payload(client):
    centre = client.get("/centres").json()[0]
    return {"centre_id": centre["id"], "test_id": centre["tests"][0]["id"],
            "appointment_at": "2035-01-01T10:00:00+05:30"}
