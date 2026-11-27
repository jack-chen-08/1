"""活动模块客户端：真 HTTP 实现 + 可注入的替身。

对接点（README 第 3 节）：POST /api/internal/events 创建活动，PATCH /api/internal/events/{id} 改活动。
活动模块工单未上线前，用 mock_activity.MockActivityClient 或 mock_activity 服务先行。
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from .audience import activity_visibility


class ActivityError(RuntimeError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"activity service {status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body


class ActivityClient(Protocol):
    async def create_event(self, payload: dict[str, Any]) -> str: ...

    async def update_event(self, event_id: str, payload: dict[str, Any]) -> None: ...


def build_activity_payload(
    *,
    title: str,
    starts_at: str,
    ends_at: str,
    venue_name: str,
    capacity: int,
    waitlist_capacity: int,
    requires_approval: bool,
    audience: str,
    org_id: str,
    site_id: str = "",
) -> dict[str, Any]:
    """把课期字段翻译成活动模块入参；本函数是两边字段的唯一翻译点。"""
    return {
        "type": "academy_course",
        "title": title,                       # 课程名 + 期次
        "starts_at": starts_at,
        "ends_at": ends_at,
        "venue_name": venue_name,
        "capacity": capacity,
        "waitlist_capacity": waitlist_capacity,
        "requires_approval": requires_approval,
        "audience": activity_visibility(audience),
        "org_id": org_id,
        "site_id": site_id,
    }


class HttpActivityClient:
    """生产实现：httpx.AsyncClient；base_url / token 只从环境变量来。"""

    def __init__(self, base_url: str, token: str = "", timeout: float = 5.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client = client

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = "Bearer " + self._token
        return h

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        own = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.request(method, self._base + path, headers=self._headers(),
                                        content=json.dumps(payload, ensure_ascii=False).encode() if payload else None)
        finally:
            if own:
                await client.aclose()
        if resp.status_code >= 400:
            raise ActivityError(resp.status_code, resp.text)
        if not resp.content:
            return {}
        return resp.json()

    async def create_event(self, payload: dict[str, Any]) -> str:
        data = await self._request("POST", "/api/internal/events", payload)
        event_id = data.get("event_id") or (data.get("data") or {}).get("event_id")
        if not event_id:
            raise ActivityError(200, f"missing event_id in response: {data}")
        return str(event_id)

    async def update_event(self, event_id: str, payload: dict[str, Any]) -> None:
        await self._request("PATCH", f"/api/internal/events/{event_id}", payload)
