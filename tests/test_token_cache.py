"""缓存与锁的单元测试：TTL 提前量、过期、Redis 实现的读写与锁。"""

from __future__ import annotations

import asyncio
import time

import pytest

from feishu.token_cache import (
    InMemoryTokenCache,
    RedisTokenCache,
    effective_ttl,
    lock_key,
    token_key,
)

pytestmark = pytest.mark.asyncio


class FakeLock:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    async def acquire(self, blocking: bool = True) -> bool:
        self.acquired += 1
        return True

    async def release(self) -> None:
        self.released += 1


class FakeRedis:
    """只实现 RedisTokenCache 用到的方法，便于在无 Redis 环境下验证契约。"""

    def __init__(self) -> None:
        self.data: dict[str, tuple[str, float | None]] = {}
        self.locks: dict[str, FakeLock] = {}
        self.last_ex: int | None = None

    async def get(self, key: str):
        item = self.data.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and time.monotonic() >= expires_at:
            self.data.pop(key, None)
            return None
        return value.encode()

    async def set(self, key: str, value: str, ex: int | None = None):
        self.last_ex = ex
        self.data[key] = (value, None if ex is None else time.monotonic() + ex)
        return True

    async def delete(self, key: str):
        self.data.pop(key, None)
        return 1

    def lock(self, name: str, timeout: float | None = None, blocking_timeout: float | None = None):
        return self.locks.setdefault(name, FakeLock())


async def test_effective_ttl_reserves_five_minutes():
    assert effective_ttl(7200, 300) == 6900
    assert effective_ttl(7200) == 6900
    assert effective_ttl(120, 300) == 30          # 过小时保底 30 秒


async def test_key_helpers_use_documented_prefix():
    assert token_key("cli_x") == "feishu:token:cli_x"
    assert lock_key("cli_x") == "feishu:token:lock:cli_x"


async def test_inmemory_cache_expires():
    cache = InMemoryTokenCache()
    await cache.set("k", "v", 1)
    assert await cache.get("k") == "v"
    await asyncio.sleep(1.15)
    assert await cache.get("k") is None


async def test_inmemory_lock_is_exclusive():
    cache = InMemoryTokenCache()
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with cache.lock("L", timeout=1) as got:
            assert got is True
            started.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await started.wait()
    async with cache.lock("L", timeout=0.05) as got:
        assert got is False                        # 超时未获得锁
    release.set()
    await task


async def test_redis_cache_roundtrip_and_ttl():
    redis = FakeRedis()
    cache = RedisTokenCache(redis)

    await cache.set("feishu:token:app", "t-token", 6900)
    assert redis.last_ex == 6900                   # 真正写进 Redis 的 TTL 是提前后的值
    assert await cache.get("feishu:token:app") == "t-token"
    await cache.delete("feishu:token:app")
    assert await cache.get("feishu:token:app") is None


async def test_redis_cache_lock_releases():
    redis = FakeRedis()
    cache = RedisTokenCache(redis)
    async with cache.lock("feishu:token:lock:app") as got:
        assert got is True
    lock = redis.locks["feishu:token:lock:app:lock"]
    assert lock.acquired == 1 and lock.released == 1
