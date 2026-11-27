"""重试队列（指数退避、上限 5 次）+ 真 HTTP 客户端路径（httpx.MockTransport）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.activities import ActivityError, HttpActivityClient
from app.service import backoff_seconds
from mock_activity import MockActivityClient

pytestmark = pytest.mark.asyncio


async def _make_failing_session(engine, org_id, course_id):
    from app.api import create_app
    from httpx import ASGITransport, AsyncClient

    failing = MockActivityClient(fail_times=99)
    app = create_app(engine=engine, activity_client=failing)
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    r = await ac.post(f"/api/admin/academy/courses/{course_id}/sessions", json={
        "title": "重试演练", "starts_at": "2026-12-20T09:00:00+08:00",
        "ends_at": "2026-12-20T11:00:00+08:00", "venue_name": "示例厅 C",
        "capacity": 20, "audience": "public",
    }, headers={"X-Org-Id": org_id})
    assert r.status_code == 201, r.text
    return app, ac, failing, r.json()


async def test_backoff_is_exponential():
    assert [backoff_seconds(n) for n in range(1, 6)] == [30, 60, 120, 240, 480]


async def test_retry_succeeds_and_backfills_event_id(engine, org_id, course_id):
    from sqlalchemy import select
    from app.models import CourseSession, SyncRetry

    app, ac, failing, data = await _make_failing_session(engine, org_id, course_id)
    failing.fail_times = 0  # 活动服务恢复
    async with app.state.sessionmaker() as db:
        row = (await db.execute(select(SyncRetry))).scalar_one()
        row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

    stats = (await ac.post("/api/internal/academy/sync-retries/process")).json()
    assert stats == {"picked": 1, "done": 1, "retry_scheduled": 0, "failed": 0}

    async with app.state.sessionmaker() as db:
        row = (await db.execute(select(SyncRetry))).scalar_one()
        sess = await db.get(CourseSession, data["id"])
    assert row.status == "done" and row.attempts == 1
    assert sess.event_id and sess.sync_status == "synced"
    await ac.aclose()


async def test_retry_stops_after_five_attempts(engine, org_id, course_id):
    from sqlalchemy import select
    from app.models import SyncRetry

    app, ac, failing, data = await _make_failing_session(engine, org_id, course_id)

    seen_next_at = []
    for expected_attempt in (2, 3, 4, 5):
        async with app.state.sessionmaker() as db:
            row = (await db.execute(select(SyncRetry))).scalar_one()
            row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        stats = (await ac.post("/api/internal/academy/sync-retries/process")).json()
        async with app.state.sessionmaker() as db:
            row = (await db.execute(select(SyncRetry))).scalar_one()
        assert row.attempts == expected_attempt
        if expected_attempt < 5:
            assert row.status == "pending"
            assert stats["retry_scheduled"] == 1
            delta = (row.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
            assert delta > 0
            seen_next_at.append(row.next_attempt_at)
        else:
            assert row.status == "failed"
            assert stats["failed"] == 1

    # 达到上限后不再被取出
    async with app.state.sessionmaker() as db:
        row = (await db.execute(select(SyncRetry))).scalar_one()
        row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    stats = (await ac.post("/api/internal/academy/sync-retries/process")).json()
    assert stats["picked"] == 0
    await ac.aclose()


async def test_http_activity_client_posts_and_patches():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({
            "method": request.method,
            "url": str(request.url),
            "body": json.loads(request.content.decode() or "{}"),
            "auth": request.headers.get("authorization"),
        })
        if request.method == "POST":
            return httpx.Response(201, json={"event_id": "evt-123"})
        return httpx.Response(200, json={"updated": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as hc:
        client = HttpActivityClient("http://activity.local", token="t-1", client=hc)
        eid = await client.create_event({"type": "academy_course", "audience": "public"})
        await client.update_event(eid, {"capacity": 30})

    assert eid == "evt-123"
    assert [s["method"] for s in seen] == ["POST", "PATCH"]
    assert seen[0]["url"] == "http://activity.local/api/internal/events"
    assert seen[1]["url"] == "http://activity.local/api/internal/events/evt-123"
    assert seen[0]["auth"] == "Bearer t-1"
    assert seen[1]["body"]["capacity"] == 30


async def test_http_activity_client_raises_on_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as hc:
        client = HttpActivityClient("http://activity.local", client=hc)
        with pytest.raises(ActivityError) as ei:
            await client.create_event({"type": "academy_course"})
    assert ei.value.status_code == 500
