"""HTTP 层：路由 + 应用工厂。

鉴权/数据范围由 S2-IAM 工单接入；本单用 X-Org-Id 头代表已解析出的 org 上下文（README 第 4 节写对接点）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import service
from .activities import HttpActivityClient
from .db import init_models, make_engine, make_sessionmaker, settings
from .models import SyncRetry
from .schemas import SessionCreate, SessionListOut, SessionOut, SessionPatch

router = APIRouter(prefix="/api/admin/academy/courses/{course_id}/sessions", tags=["academy-sessions"])


async def get_db(request: Request) -> AsyncSession:
    maker = request.app.state.sessionmaker
    async with maker() as db:
        yield db


async def get_client(request: Request):
    return request.app.state.activity_client


def get_org(x_org_id: str | None = Header(default=None)) -> str:
    if not x_org_id:
        raise HTTPException(status_code=400, detail={"code": "org_required",
                                                    "message": "X-Org-Id header is required"})
    return x_org_id


def _out(sess, enrolled: int = 0) -> SessionOut:
    out = SessionOut.model_validate(sess)
    out.enrolled_count = enrolled
    return out


@router.get("", response_model=SessionListOut)
async def list_sessions(course_id: str,
                        status: str | None = Query(default=None, pattern="^(scheduled|cancelled)$"),
                        limit: int = Query(default=20, ge=1, le=100),
                        offset: int = Query(default=0, ge=0),
                        org_id: str = Depends(get_org),
                        db: AsyncSession = Depends(get_db)):
    rows, total = await service.list_sessions(db, org_id, course_id, status, limit, offset)
    items = []
    for row in rows:
        items.append(_out(row, await service.enrolled_count(db, row.id)))
    return SessionListOut(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(course_id: str, body: SessionCreate,
                         org_id: str = Depends(get_org),
                         db: AsyncSession = Depends(get_db),
                         client=Depends(get_client)):
    sess = await service.create_session(db, org_id, course_id, body, client)
    return _out(sess)


@router.patch("/{sid}", response_model=SessionOut)
async def patch_session(course_id: str, sid: str, body: SessionPatch,
                        org_id: str = Depends(get_org),
                        db: AsyncSession = Depends(get_db),
                        client=Depends(get_client)):
    try:
        sess = await service.patch_session(db, org_id, course_id, sid, body, client)
    except service.NotFound:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "session not found"})
    except service.CapacityBelowEnrolled as exc:
        raise HTTPException(status_code=422, detail={
            "code": "capacity_below_enrolled",
            "message": "capacity cannot be lower than enrolled count",
            "enrolled": exc.enrolled,
        })
    except service.InvalidState as exc:
        raise HTTPException(status_code=409, detail={"code": "invalid_state", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_time_range", "message": str(exc)})
    return _out(sess, await service.enrolled_count(db, sess.id))


@router.post("/{sid}/cancel", response_model=SessionOut)
async def cancel_session(course_id: str, sid: str,
                         org_id: str = Depends(get_org),
                         db: AsyncSession = Depends(get_db)):
    try:
        sess = await service.cancel_session(db, org_id, course_id, sid)
    except service.NotFound:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "session not found"})
    except service.InvalidState as exc:
        raise HTTPException(status_code=409, detail={"code": "invalid_state", "message": str(exc)})
    return _out(sess, await service.enrolled_count(db, sess.id))


ops = APIRouter(prefix="/api/internal/academy", tags=["academy-ops"])


@ops.post("/sync-retries/process")
async def process_retries(request: Request, db: AsyncSession = Depends(get_db),
                          client=Depends(get_client)):
    """运维/定时任务入口：跑一轮到期重试（生产由 Celery/APScheduler 每 30 秒调一次）。"""
    stats = await service.process_due_retries(db, client)
    return stats


@ops.get("/sync-retries")
async def list_retries(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SyncRetry).order_by(SyncRetry.created_at.desc()).limit(100))).scalars().all()
    return {"items": [{
        "id": r.id, "session_id": r.session_id, "operation": r.operation,
        "attempts": r.attempts, "max_attempts": r.max_attempts,
        "status": r.status, "next_attempt_at": r.next_attempt_at, "last_error": r.last_error,
    } for r in rows]}


def create_app(*, engine=None, activity_client=None) -> FastAPI:
    engine = engine or make_engine()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await init_models(engine)
        yield

    app = FastAPI(title="Member Space · Academy Sessions API", version="1.0.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.activity_client = activity_client or HttpActivityClient(
        settings.activity_base_url, settings.activity_token)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"detail": {"code": "internal_error", "message": str(exc)}})

    app.include_router(router)
    app.include_router(ops)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

    return app


app = create_app()
