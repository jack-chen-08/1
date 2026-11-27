"""应用访问凭证缓存与刷新锁。

要求（需求原文）：
- 缓存键 `feishu:token:{app_id}`；
- 按飞书返回的 expire 提前 5 分钟过期；
- 刷新并发时用 Redis 锁，保证同一时刻只有一个刷新请求。

真实环境用 RedisTokenCache（redis.asyncio），测试与本地用 InMemoryTokenCache；
两者实现同一协议，行为（TTL、过期提前量、锁语义）一致。
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol

TOKEN_KEY_PREFIX = "feishu:token:"
LOCK_KEY_PREFIX = "feishu:token:lock:"


def token_key(app_id: str) -> str:
    return f"{TOKEN_KEY_PREFIX}{app_id}"


def lock_key(app_id: str) -> str:
    return f"{LOCK_KEY_PREFIX}{app_id}"


def effective_ttl(expire_seconds: int, skew_seconds: int = 300) -> int:
    """提前 skew 秒过期；expire 过小时至少留 30 秒，避免永不命中缓存。"""
    return max(int(expire_seconds) - int(skew_seconds), 30)


class TokenCache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    def lock(self, key: str, *, timeout: float = 5.0) -> AsyncIterator[bool]: ...


class InMemoryTokenCache:
    """进程内实现：TTL 用单调时钟，锁用 asyncio.Lock。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires_at = item
        if time.monotonic() >= expires_at:
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._data[key] = (value, time.monotonic() + max(int(ttl_seconds), 1))

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    @asynccontextmanager
    async def lock(self, key: str, *, timeout: float = 5.0) -> AsyncIterator[bool]:
        lock = self._lock_for(key)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
        except asyncio.TimeoutError:
            yield False
            return
        try:
            yield True
        finally:
            lock.release()

    def ttl_of(self, key: str) -> float:  # 测试辅助
        item = self._data.get(key)
        return 0.0 if item is None else max(item[1] - time.monotonic(), 0.0)


class RedisTokenCache:
    """redis.asyncio 实现；client 由调用方注入（便于测试与复用连接池）。"""

    def __init__(self, client) -> None:
        self.client = client

    async def get(self, key: str) -> str | None:
        value = await self.client.get(key)
        if value is None:
            return None
        return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self.client.set(key, value, ex=max(int(ttl_seconds), 1))

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    @asynccontextmanager
    async def lock(self, key: str, *, timeout: float = 5.0) -> AsyncIterator[bool]:
        # redis-py 的分布式锁：SET NX PX + 到期自动释放
        lock = self.client.lock(f"{key}:lock", timeout=timeout, blocking_timeout=timeout)
        acquired = await lock.acquire(blocking=True)
        try:
            yield bool(acquired)
        finally:
            if acquired:
                try:
                    await lock.release()
                except Exception:  # 锁已自动过期
                    pass
