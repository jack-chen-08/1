"""离线演练：不联网、不接数据库服务，一次跑完四条验收并打印真实报文。

用法：python scripts/demo_offline.py
输出每步的 HTTP 状态码与关键字段，可直接作为交付证据。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api import create_app  # noqa: E402
from app.db import init_models, make_engine  # noqa: E402
from app.models import Enrollment, SyncRetry  # noqa: E402
from mock_activity import MockActivityClient  # noqa: E402


def show(step: str, obj) -> None:
    print(f"\n### {step}")
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:1200])


async def main() -> None:
    tmp = tempfile.mkdtemp(prefix="acad-demo-")
    engine = make_engine(f"sqlite+aiosqlite:///{tmp}/demo.db")
    await init_models(engine)

    activity = MockActivityClient()
    app = create_app(engine=engine, activity_client=activity)
    org = str(uuid.uuid4())
    course = str(uuid.uuid4())
    base = f"/api/admin/academy/courses/{course}/sessions"
    headers = {"X-Org-Id": org}

    body = {
        "title": "产业资源对接实战", "seq_label": "第 3 期",
        "starts_at": "2026-12-10T09:00:00+08:00", "ends_at": "2026-12-10T12:00:00+08:00",
        "venue_name": "示例厅 A", "capacity": 40, "waitlist_capacity": 10,
        "requires_approval": False, "audience": "member_only",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://demo") as ac:
        print("=" * 62)
        print("AC1 创建课期 → 活动模块收到 1 次创建，event_id 回填")
        print("=" * 62)
        r = await ac.post(base, json=body, headers=headers)
        created = r.json()
        show(f"POST {base} -> {r.status_code}", {
            "id": created["id"], "event_id": created["event_id"],
            "sync_status": created["sync_status"], "status": created["status"]})
        show("活动模块收到", activity.creates())

        print("\n" + "=" * 62)
        print("AC2 活动模块 500 → 课期仍保存、sync_status=failed、重试队列有记录")
        print("=" * 62)
        activity.fail_times = 1
        r = await ac.post(base, json={**body, "title": "同步失败演练"}, headers=headers)
        failed = r.json()
        show(f"POST -> {r.status_code}", {
            "event_id": failed["event_id"], "sync_status": failed["sync_status"], "status": failed["status"]})
        show("重试队列", (await ac.get("/api/internal/academy/sync-retries")).json())

        print("\n" + "=" * 62)
        print("AC3 名额改到小于已报名人数 → 422，并给出已报名数")
        print("=" * 62)
        async with app.state.sessionmaker() as db:
            for _ in range(12):
                db.add(Enrollment(org_id=org, session_id=created["id"], member_id=str(uuid.uuid4())))
            await db.commit()
        r = await ac.patch(f"{base}/{created['id']}", json={"capacity": 10}, headers=headers)
        show(f"PATCH capacity=10 (已报名 12) -> {r.status_code}", r.json())

        print("\n" + "=" * 62)
        print("AC4 audience 三取值 → 活动可见范围映射")
        print("=" * 62)
        for audience in ("member_only", "public", "invite_only"):
            await ac.post(base, json={**body, "audience": audience, "title": f"映射-{audience}"},
                          headers=headers)
            print(f"{audience:12s} -> {activity.creates()[-1]['payload']['audience']}")

        print("\n" + "=" * 62)
        print("补充 1 改场地/名额 → PATCH 对应活动（带 event_id）")
        print("=" * 62)
        r = await ac.patch(f"{base}/{created['id']}",
                           json={"venue_name": "示例厅 B", "capacity": 60}, headers=headers)
        show(f"PATCH -> {r.status_code}", {"event_id": r.json()["event_id"],
                                           "activity_last_patch": activity.patches()[-1]})

        print("\n" + "=" * 62)
        print("补充 2 取消 → 状态 cancelled + 事件入发件箱；重复取消 409")
        print("=" * 62)
        r = await ac.post(f"{base}/{created['id']}/cancel", headers=headers)
        show(f"POST cancel -> {r.status_code}", {"status": r.json()["status"]})
        r2 = await ac.post(f"{base}/{created['id']}/cancel", headers=headers)
        show(f"重复 cancel -> {r2.status_code}", r2.json())

    print("\n" + "=" * 62)
    print(f"活动模块调用总计: {len(activity.calls)} 次 "
          f"(create={len(activity.creates())}, patch={len(activity.patches())})")
    print("跑完时间(UTC):", datetime.now(timezone.utc).isoformat())
    print("=" * 62)


if __name__ == "__main__":
    asyncio.run(main())
