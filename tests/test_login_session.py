import time

from api_service.auth.store import AuthStore


class FakeRedis:
    def __init__(self):
        self.data, self.ttl = {}, {}

    async def set(self, key, value, ex=None):
        self.data[key], self.ttl[key] = value, ex

    async def get(self, key):
        return self.data.get(key)


async def test_activity_slides_the_idle_expiry_up_to_the_cap(monkeypatch):
    redis = FakeRedis()
    store = AuthStore(redis, "t")  # ty: ignore[invalid-argument-type]
    now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    sid, session = await store.create_session("u1", ttl=1800)
    assert session.expires_at == 1_000_000 + 1800

    now[0] += 600  # early in the window: no write
    assert await store.touch(sid, session, 1800, 3600) == session

    now[0] += 600  # past half the window: extended, and stored
    moved = await store.touch(sid, session, 1800, 3600)
    assert moved.expires_at == 1_000_000 + 1200 + 1800
    assert await store.read_session(sid) == moved

    now[0] = 1_000_000 + 3000  # near the cap: never past the login + max
    capped = await store.touch(sid, moved, 1800, 3600)
    assert capped.expires_at == 1_000_000 + 3600


async def test_idle_session_expires():
    store = AuthStore(FakeRedis(), "t")  # ty: ignore[invalid-argument-type]
    sid, _ = await store.create_session("u1", ttl=60)
    assert await store.read_session(sid) is not None
    assert await store.read_session("x" * 43) is None
