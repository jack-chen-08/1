"""活动模块 mock：一个可注入的替身类 + 一个可独立启动的假服务。

独立启动（演练用）：
    uvicorn mock_activity:mock_app --port 8099
    curl -X POST localhost:8099/api/internal/events -H 'Content-Type: application/json' -d '{...}'
    curl localhost:8099/_calls

对接点：真实活动模块工单上线后，只把 ACTIVITY_BASE_URL 指向它即可，课期侧零改动。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request


class MockActivityClient:
    """进程内替身：记录每次调用，可编程失败（fail_times 次返回 500）。"""

    def __init__(self, fail_times: int = 0, fail_status: int = 500) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_times = fail_times
        self.fail_status = fail_status
        self._seq = 0

    def _record(self, op: str, payload: dict[str, Any], event_id: str | None = None) -> None:
        self._seq += 1
        self.calls.append({"seq": self._seq, "op": op, "event_id": event_id, "payload": payload})

    def _maybe_fail(self) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ActivityErrorLike(self.fail_status)

    async def create_event(self, payload: dict[str, Any]) -> str:
        self._maybe_fail()
        event_id = "evt-" + str(uuid.uuid4())
        self._record("create", payload, event_id)
        return event_id

    async def update_event(self, event_id: str, payload: dict[str, Any]) -> None:
        self._maybe_fail()
        self._record("patch", payload, event_id)

    # 断言辅助
    def creates(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["op"] == "create"]

    def patches(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["op"] == "patch"]


class ActivityErrorLike(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"mock activity error {status_code}")
        self.status_code = status_code


mock_app = FastAPI(title="Mock Activity Service")
_calls: list[dict[str, Any]] = []
_fail_next = {"n": 0}


@mock_app.post("/api/internal/events")
async def create_event(request: Request):
    body = await request.json()
    if _fail_next["n"] > 0:
        _fail_next["n"] -= 1
        raise HTTPException(status_code=500, detail="injected failure")
    event_id = "evt-" + str(uuid.uuid4())
    _calls.append({"op": "create", "event_id": event_id, "payload": body})
    return {"event_id": event_id, "data": {"event_id": event_id, "type": body.get("type")}}


@mock_app.patch("/api/internal/events/{event_id}")
async def update_event(event_id: str, request: Request):
    body = await request.json()
    _calls.append({"op": "patch", "event_id": event_id, "payload": body})
    return {"event_id": event_id, "updated": True}


@mock_app.get("/_calls")
async def list_calls():
    return {"count": len(_calls), "items": _calls}


@mock_app.post("/_fail_next")
async def set_fail(n: int = 1):
    _fail_next["n"] = n
    return {"fail_next": n}
