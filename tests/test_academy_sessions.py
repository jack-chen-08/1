"""验收对应：AC1 / AC2 / AC3 / AC4 + 补充（PATCH 同步、取消事件、列表过滤）。"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def _create(client, org_id, course_id, body):
    r = await client.post(f"/api/admin/academy/courses/{course_id}/sessions",
                          json=body, headers={"X-Org-Id": org_id})
    assert r.status_code == 201, r.text
    return r.json()


async def _enroll(app, org_id: str, session_id: str, n: int) -> None:
    from app.models import Enrollment

    async with app.state.sessionmaker() as db:
        for i in range(n):
            db.add(Enrollment(org_id=org_id, session_id=session_id, member_id=str(uuid.uuid4())))
        await db.commit()


# ---------- AC1 ----------
async def test_ac1_create_triggers_one_activity_create_and_backfills_event_id(
        client, activity, org_id, course_id, session_payload):
    data = await _create(client, org_id, course_id, session_payload())

    assert len(activity.creates()) == 1
    payload = activity.creates()[0]["payload"]
    assert payload["type"] == "academy_course"
    assert payload["title"] == "产业资源对接实战 第 3 期"
    assert payload["capacity"] == 40 and payload["waitlist_capacity"] == 10
    assert payload["requires_approval"] is False

    assert data["event_id"] == activity.creates()[0]["event_id"]
    assert data["sync_status"] == "synced"
    assert data["status"] == "scheduled"


# ---------- AC2 ----------
async def test_ac2_activity_500_keeps_session_and_enqueues_retry(
        client, engine, app, org_id, course_id, session_payload):
    from mock_activity import MockActivityClient
    from app.api import create_app
    from httpx import ASGITransport, AsyncClient

    failing = MockActivityClient(fail_times=1)
    failing_app = create_app(engine=engine, activity_client=failing)
    async with AsyncClient(transport=ASGITransport(app=failing_app), base_url="http://test") as ac:
        r = await ac.post(f"/api/admin/academy/courses/{course_id}/sessions",
                          json=session_payload(), headers={"X-Org-Id": org_id})
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["event_id"] is None
        assert data["sync_status"] == "failed"
        assert data["status"] == "scheduled"

        retries = (await ac.get("/api/internal/academy/sync-retries")).json()["items"]
    assert len(retries) == 1
    row = retries[0]
    assert row["session_id"] == data["id"]
    assert row["operation"] == "create"
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["max_attempts"] == 5
    assert "mock activity error 500" in row["last_error"]


# ---------- AC3 ----------
async def test_ac3_capacity_below_enrolled_returns_422_with_enrolled_count(
        client, app, org_id, course_id, session_payload):
    data = await _create(client, org_id, course_id, session_payload(capacity=40))
    await _enroll(app, org_id, data["id"], 12)

    r = await client.patch(f"/api/admin/academy/courses/{course_id}/sessions/{data['id']}",
                           json={"capacity": 10}, headers={"X-Org-Id": org_id})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "capacity_below_enrolled"
    assert detail["enrolled"] == 12

    # 边界：等于已报名人数应放行
    ok = await client.patch(f"/api/admin/academy/courses/{course_id}/sessions/{data['id']}",
                            json={"capacity": 12}, headers={"X-Org-Id": org_id})
    assert ok.status_code == 200, ok.text
    assert ok.json()["capacity"] == 12
    assert ok.json()["enrolled_count"] == 12


# ---------- AC4 ----------
@pytest.mark.parametrize("audience,expected", [
    ("member_only", "members_only"),
    ("public", "public"),
    ("invite_only", "closed_door"),
])
async def test_ac4_audience_maps_to_activity_visibility(
        client, activity, org_id, course_id, session_payload, audience, expected):
    await _create(client, org_id, course_id, session_payload(audience=audience))
    assert activity.creates()[-1]["payload"]["audience"] == expected


async def test_ac4_unknown_audience_is_rejected(client, org_id, course_id, session_payload):
    r = await client.post(f"/api/admin/academy/courses/{course_id}/sessions",
                          json=session_payload(audience="vip_only"), headers={"X-Org-Id": org_id})
    assert r.status_code == 422


# ---------- 补充 ----------
async def test_patch_time_venue_capacity_syncs_activity(
        client, activity, org_id, course_id, session_payload):
    data = await _create(client, org_id, course_id, session_payload())
    r = await client.patch(f"/api/admin/academy/courses/{course_id}/sessions/{data['id']}",
                           json={"venue_name": "示例厅 B", "capacity": 60,
                                 "ends_at": "2026-12-10T13:30:00+08:00"},
                           headers={"X-Org-Id": org_id})
    assert r.status_code == 200, r.text
    assert r.json()["event_id"] == data["event_id"]
    assert len(activity.patches()) == 1
    patch = activity.patches()[0]
    assert patch["event_id"] == data["event_id"]
    assert patch["payload"]["venue_name"] == "示例厅 B"
    assert patch["payload"]["capacity"] == 60


async def test_patch_without_sync_fields_does_not_call_activity(
        client, activity, org_id, course_id, session_payload):
    data = await _create(client, org_id, course_id, session_payload())
    before = len(activity.calls)
    r = await client.patch(f"/api/admin/academy/courses/{course_id}/sessions/{data['id']}",
                           json={"seq_label": "第 4 期"}, headers={"X-Org-Id": org_id})
    assert r.status_code == 200
    assert len(activity.calls) == before


async def test_cancel_sets_status_and_emits_event_once(client, app, org_id, course_id, session_payload):
    from sqlalchemy import select
    from app.models import OutboxEvent

    data = await _create(client, org_id, course_id, session_payload())
    r = await client.post(f"/api/admin/academy/courses/{course_id}/sessions/{data['id']}/cancel",
                          headers={"X-Org-Id": org_id})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    async with app.state.sessionmaker() as db:
        rows = (await db.execute(select(OutboxEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "academy.session.cancelled"
    assert data["id"] in rows[0].payload_json

    again = await client.post(f"/api/admin/academy/courses/{course_id}/sessions/{data['id']}/cancel",
                              headers={"X-Org-Id": org_id})
    assert again.status_code == 409
    async with app.state.sessionmaker() as db:
        rows2 = (await db.execute(select(OutboxEvent))).scalars().all()
    assert len(rows2) == 1, "重复取消不得重复发事件"


async def test_list_filters_status_and_excludes_soft_deleted(
        client, app, org_id, course_id, session_payload):
    from datetime import datetime, timezone
    from app.models import CourseSession

    a = await _create(client, org_id, course_id, session_payload(title="课期 A",
                                                                 starts_at="2026-12-11T09:00:00+08:00",
                                                                 ends_at="2026-12-11T11:00:00+08:00"))
    b = await _create(client, org_id, course_id, session_payload(title="课期 B",
                                                                 starts_at="2026-12-12T09:00:00+08:00",
                                                                 ends_at="2026-12-12T11:00:00+08:00"))
    await client.post(f"/api/admin/academy/courses/{course_id}/sessions/{b['id']}/cancel",
                      headers={"X-Org-Id": org_id})

    async with app.state.sessionmaker() as db:
        row = await db.get(CourseSession, a["id"])
        row.deleted_at = datetime.now(timezone.utc)
        await db.commit()

    r = await client.get(f"/api/admin/academy/courses/{course_id}/sessions",
                         headers={"X-Org-Id": org_id})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["id"] == b["id"]

    sched = await client.get(f"/api/admin/academy/courses/{course_id}/sessions?status=scheduled",
                             headers={"X-Org-Id": org_id})
    assert sched.json()["total"] == 0


async def test_missing_org_header_is_rejected(client, course_id):
    r = await client.get(f"/api/admin/academy/courses/{course_id}/sessions")
    assert r.status_code == 400
