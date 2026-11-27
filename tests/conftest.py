from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api import create_app
from app.db import init_models, make_engine
from mock_activity import MockActivityClient


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_models(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def activity():
    return MockActivityClient()


@pytest_asyncio.fixture
async def app(engine, activity):
    application = create_app(engine=engine, activity_client=activity)
    return application


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def org_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def course_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def session_payload():
    def _make(**over):
        body = {
            "title": "产业资源对接实战",
            "seq_label": "第 3 期",
            "starts_at": "2026-12-10T09:00:00+08:00",
            "ends_at": "2026-12-10T12:00:00+08:00",
            "venue_name": "示例厅 A",
            "capacity": 40,
            "waitlist_capacity": 10,
            "requires_approval": False,
            "audience": "member_only",
        }
        body.update(over)
        return body
    return _make


@pytest.fixture(autouse=True)
def _anyio_backend():
    return "asyncio"
