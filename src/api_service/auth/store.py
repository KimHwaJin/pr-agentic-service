"""Opaque login session and single-use login flow records in Redis (hashed keys)."""

import hashlib
import json
import re
import secrets
import time
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_CONSUME = "local v = redis.call('GET', KEYS[1]) redis.call('DEL', KEYS[1]) return v"


@dataclass(frozen=True)
class LoginSession:
    user_id: str
    csrf_token: str
    expires_at: int


@dataclass(frozen=True)
class LoginFlow:
    return_to: str
    target: str  # app | docs


class AuthStore:
    def __init__(self, redis: Redis, namespace: str):
        self.redis, self.namespace = redis, namespace

    def _key(self, kind: str, token: str) -> str | None:
        if not _TOKEN.fullmatch(token):
            return None
        return f"{self.namespace}:{kind}:{hashlib.sha256(token.encode()).hexdigest()}"

    async def create_session(self, user_id: str, ttl: int) -> tuple[str, LoginSession]:
        session = LoginSession(user_id, secrets.token_urlsafe(32), int(time.time()) + ttl)
        sid = secrets.token_urlsafe(32)
        await self.redis.set(self._key("login", sid), json.dumps(asdict(session)), ex=ttl)
        return sid, session

    async def read_session(self, sid: str) -> LoginSession | None:
        key = self._key("login", sid)
        raw = await self.redis.get(key) if key else None
        if raw is None:
            return None
        session = LoginSession(**json.loads(raw))
        return session if session.expires_at > time.time() else None

    async def revoke_session(self, sid: str) -> None:
        if key := self._key("login", sid):
            await self.redis.delete(key)

    async def create_flow(self, token: str, flow: LoginFlow, ttl: int) -> None:
        await self.redis.set(self._key("flow", token), json.dumps(asdict(flow)), ex=ttl)

    async def consume_flow(self, token: str) -> LoginFlow | None:
        key = self._key("flow", token)
        raw = await self.redis.eval(_CONSUME, 1, key) if key else None
        return LoginFlow(**json.loads(raw)) if raw else None
