"""Opaque login session and single-use login flow records in Redis.

Keys are hashed.
"""

import hashlib
import json
import re
import secrets
import time
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, replace
from typing import cast

from redis.asyncio import Redis

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_CONSUME = (
    "local v = redis.call('GET', KEYS[1]) redis.call('DEL', KEYS[1]) return v"
)


@dataclass(frozen=True)
class AuthSession:
    user_id: str
    csrf_token: str
    expires_at: int  # idle expiry; moves with activity (AuthStore.touch)
    started_at: int  # the login; caps how far expires_at may move


@dataclass(frozen=True)
class AuthFlow:
    return_to: str
    target: str  # app | docs
    # SSO pages already passed (login, then the token page): see _enter
    hops: int = 0


class AuthStore:
    def __init__(self, redis: Redis, namespace: str):
        self.redis, self.namespace = redis, namespace

    def _key(self, kind: str, token: str) -> str:
        digest = hashlib.sha256(token.encode()).hexdigest()
        return f"{self.namespace}:{kind}:{digest}"

    def _lookup_key(self, kind: str, token: str) -> str | None:
        """Key for a token that came from a client; None if malformed."""
        return self._key(kind, token) if _TOKEN.fullmatch(token) else None

    async def create_session(
        self, user_id: str, ttl: int
    ) -> tuple[str, AuthSession]:
        now = int(time.time())
        session = AuthSession(
            user_id, secrets.token_urlsafe(32), now + ttl, now
        )
        sid = secrets.token_urlsafe(32)
        await self._save(sid, session)
        return sid, session

    async def read_session(self, sid: str) -> AuthSession | None:
        key = self._lookup_key("login", sid)
        raw = await self.redis.get(key) if key else None
        if raw is None:
            return None
        try:
            session = AuthSession(**json.loads(raw))
        except TypeError:  # a record of another shape: log in again
            return None
        return session if session.expires_at > time.time() else None

    async def touch(
        self, sid: str, session: AuthSession, ttl: int, max_seconds: int
    ) -> AuthSession:
        """Slide the idle expiry on activity, never past the login's cap.

        Written at most once per half ``ttl`` so requests do not each write.
        """
        now = int(time.time())
        cap = session.started_at + max_seconds
        expires = min(now + ttl, cap)
        gain = expires - session.expires_at
        if gain <= 0 or (gain < ttl // 2 and expires < cap):
            return session
        session = replace(session, expires_at=expires)
        await self._save(sid, session)
        return session

    async def _save(self, sid: str, session: AuthSession) -> None:
        await self.redis.set(
            self._key("login", sid),
            json.dumps(asdict(session)),
            # ex, not exat: Redis 6.0 has no EXAT
            ex=max(1, session.expires_at - int(time.time())),
        )

    async def revoke_session(self, sid: str) -> None:
        if key := self._lookup_key("login", sid):
            await self.redis.delete(key)

    async def create_flow(self, token: str, flow: AuthFlow, ttl: int) -> None:
        await self.redis.set(
            self._key("flow", token), json.dumps(asdict(flow)), ex=ttl
        )

    async def consume_flow(self, token: str) -> AuthFlow | None:
        key = self._lookup_key("flow", token)
        raw = (
            await cast(
                Awaitable[str | None], self.redis.eval(_CONSUME, 1, key)
            )
            if key
            else None
        )
        return AuthFlow(**json.loads(raw)) if raw else None
