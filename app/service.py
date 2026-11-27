"""业务服务：课期 CRUD + 活动模块同步 + 重试队列 + 取消事件。

同步语义（需求原文）：
- 创建课期 → 调活动模块 POST /api/internal/events 建一场 type=academy_course 的活动，回填 event_id。
- 改时间/名额/场地 → PATCH 对应活动。
- 同步失败 → 课期照存（status=scheduled、event_id 为空、sync_status=failed），写重试队列，最多 5 次，指数退避。
- 已有报名时，名额不得改小到已报名人数以下。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .activities import ActivityClient, ActivityError, build_activity_payload
from .models import CourseSession, Enrollment, OutboxEvent, SyncRetry, utcnow
from .schemas import SessionCreate, SessionPatch

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 30
SYNC_FIELDS = ("starts_at", "ends_at", "venue_name", "capacity", "waitlist_capacity", "title", "audience", "requires_approval")


class NotFound(Exception):
    pass


class CapacityBelowEnrolled(Exception):
    def __init__(self, enrolled: int) -> None:
        super().__init__(f"capacity below enrolled: {enrolled}")
        self.enrolled = enrolled


class InvalidState(Exception):
    pass


def backoff_seconds(attempt: int, base: int = BASE_BACKOFF_SECONDS) -> int:
    """第 n 次失败后的等待：base * 2^(n-1) → 30 / 60 / 120 / 240 / 480 秒。"""
    return base * (2 ** (attempt - 1))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def activity_payload_from(sess: CourseSession) -> dict[str, Any]:
    title = sess.title if not sess.seq_label else f"{sess.title} {sess.seq_label}"
    return build_activity_payload(
        title=title,
        starts_at=_iso(sess.starts_at),
        ends_at=_iso(sess.ends_at),
        venue_name=sess.venue_name,
        capacity=sess.capacity,
        waitlist_capacity=sess.waitlist_capacity,
        requires_approval=sess.requires_approval,
        audience=sess.audience,
        org_id=sess.org_id,
        site_id=sess.site_id,
    )


async def enrolled_count(db: AsyncSession, session_id: str) -> int:
    q = select(func.count(Enrollment.id)).where(
        Enrollment.session_id == session_id,
        Enrollment.status == "enrolled",
        Enrollment.deleted_at.is_(None),
    )
    return int((await db.execute(q)).scalar_one())


async def enqueue_retry(db: AsyncSession, sess: CourseSession, operation: str, error: str,
                        attempts: int = 1, now: datetime | None = None) -> SyncRetry:
    now = now or utcnow()
    row = SyncRetry(
        org_id=sess.org_id,
        session_id=sess.id,
        operation=operation,
        attempts=attempts,
        max_attempts=MAX_ATTEMPTS,
        next_attempt_at=now + timedelta(seconds=backoff_seconds(attempts)),
        status="pending" if attempts < MAX_ATTEMPTS else "failed",
        last_error=error[:1000],
    )
    db.add(row)
    return row


async def list_sessions(db: AsyncSession, org_id: str, course_id: str,
                        status: str | None = None, limit: int = 20, offset: int = 0):
    base = select(CourseSession).where(
        CourseSession.org_id == org_id,
        CourseSession.course_id == course_id,
        CourseSession.deleted_at.is_(None),
    )
    if status:
        base = base.where(CourseSession.status == status)
    total = int((await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (await db.execute(
        base.order_by(CourseSession.starts_at.asc()).limit(limit).offset(offset)
    )).scalars().all()
    return rows, total


async def _get(db: AsyncSession, org_id: str, course_id: str, sid: str) -> CourseSession:
    row = (await db.execute(select(CourseSession).where(
        CourseSession.id == sid,
        CourseSession.org_id == org_id,
        CourseSession.course_id == course_id,
        CourseSession.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        raise NotFound(sid)
    return row


async def create_session(db: AsyncSession, org_id: str, course_id: str, data: SessionCreate,
                         client: ActivityClient, now: datetime | None = None) -> CourseSession:
    now = now or utcnow()
    sess = CourseSession(
        org_id=org_id,
        course_id=course_id,
        title=data.title,
        seq_label=data.seq_label,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        venue_name=data.venue_name,
        capacity=data.capacity,
        waitlist_capacity=data.waitlist_capacity,
        requires_approval=data.requires_approval,
        audience=data.audience,
        status="scheduled",
        created_at=now,
        updated_at=now,
    )
    db.add(sess)
    await db.flush()  # 先落库拿到 id，同步失败也不丢课期

    try:
        sess.event_id = await client.create_event(activity_payload_from(sess))
        sess.sync_status = "synced"
    except (ActivityError, Exception) as exc:  # 网络异常与 5xx 同等待遇
        sess.event_id = None
        sess.sync_status = "failed"
        await enqueue_retry(db, sess, "create", f"{type(exc).__name__}: {exc}", attempts=1, now=now)

    await db.commit()
    await db.refresh(sess)
    return sess


async def patch_session(db: AsyncSession, org_id: str, course_id: str, sid: str,
                        data: SessionPatch, client: ActivityClient,
                        now: datetime | None = None) -> CourseSession:
    now = now or utcnow()
    sess = await _get(db, org_id, course_id, sid)
    if sess.status == "cancelled":
        raise InvalidState("cancelled session cannot be modified")

    changes = data.model_dump(exclude_unset=True)
    if "capacity" in changes:
        enrolled = await enrolled_count(db, sess.id)
        if changes["capacity"] < enrolled:
            raise CapacityBelowEnrolled(enrolled)

    start = changes.get("starts_at", sess.starts_at)
    end = changes.get("ends_at", sess.ends_at)
    if end <= start:
        raise ValueError("ends_at must be later than starts_at")

    needs_sync = any(k in changes for k in SYNC_FIELDS)
    for key, value in changes.items():
        setattr(sess, key, value)
    sess.updated_at = now

    if needs_sync:
        if sess.event_id is None:
            try:
                sess.event_id = await client.create_event(activity_payload_from(sess))
                sess.sync_status = "synced"
            except Exception as exc:
                sess.sync_status = "failed"
                await enqueue_retry(db, sess, "create", f"{type(exc).__name__}: {exc}", attempts=1, now=now)
        else:
            try:
                await client.update_event(sess.event_id, activity_payload_from(sess))
                sess.sync_status = "synced"
            except Exception as exc:
                sess.sync_status = "failed"
                await enqueue_retry(db, sess, "patch", f"{type(exc).__name__}: {exc}", attempts=1, now=now)

    await db.commit()
    await db.refresh(sess)
    return sess


async def cancel_session(db: AsyncSession, org_id: str, course_id: str, sid: str,
                         now: datetime | None = None) -> CourseSession:
    now = now or utcnow()
    sess = await _get(db, org_id, course_id, sid)
    if sess.status == "cancelled":
        raise InvalidState("session already cancelled")

    sess.status = "cancelled"
    sess.cancelled_at = now
    sess.updated_at = now
    # 本单只发事件；通知与退权益由「课期取消」工单消费这条事件。
    db.add(OutboxEvent(
        org_id=sess.org_id,
        event_type="academy.session.cancelled",
        payload_json=json.dumps({
            "session_id": sess.id,
            "course_id": sess.course_id,
            "org_id": sess.org_id,
            "event_id": sess.event_id,
            "cancelled_at": _iso(now),
        }, ensure_ascii=False),
    ))
    await db.commit()
    await db.refresh(sess)
    return sess


async def process_due_retries(db: AsyncSession, client: ActivityClient, now: datetime | None = None,
                             limit: int = 50) -> dict[str, int]:
    """扫描到期重试行并执行；成功回填 event_id，达上限置 failed。"""
    now = now or utcnow()
    rows = (await db.execute(
        select(SyncRetry).where(
            SyncRetry.status == "pending",
            SyncRetry.next_attempt_at <= now,
        ).order_by(SyncRetry.next_attempt_at.asc()).limit(limit)
    )).scalars().all()

    stats = {"picked": len(rows), "done": 0, "retry_scheduled": 0, "failed": 0}
    for row in rows:
        sess = (await db.execute(select(CourseSession).where(CourseSession.id == row.session_id))).scalar_one_or_none()
        if sess is None:
            row.status = "failed"
            row.last_error = "session missing"
            stats["failed"] += 1
            continue
        try:
            if row.operation == "create":
                sess.event_id = await client.create_event(activity_payload_from(sess))
            else:
                if sess.event_id is None:
                    raise RuntimeError("patch retry without event_id")
                await client.update_event(sess.event_id, activity_payload_from(sess))
        except Exception as exc:
            row.attempts += 1
            row.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            if row.attempts >= row.max_attempts:
                row.status = "failed"
                stats["failed"] += 1
            else:
                row.next_attempt_at = now + timedelta(seconds=backoff_seconds(row.attempts))
                stats["retry_scheduled"] += 1
            sess.sync_status = "failed"
        else:
            row.status = "done"
            sess.event_id = sess.event_id or None
            sess.sync_status = "synced"
            stats["done"] += 1

    await db.commit()
    return stats
