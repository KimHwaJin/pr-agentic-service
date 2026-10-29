"""Identity headers of our calls to the executor and pr-batch.

Both take ``X-Api-Key`` (our key) and the same identity headers
(docs/specs/service-auth.md). The values are always ones this service
verified, never headers a caller sent us.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    """Who a call to the executor or pr-batch is made for.

    Sent as headers, never in bodies. ``user_id`` None is a system call:
    reads only, over the executions of the tenant. ``tenant`` None is the
    tenant of our key; as a relay we name another one (``X-Tenant-Id``).
    pr-batch ignores ``X-Session-Id``.
    """

    user_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    tenant: str | None = None

    def headers(self) -> dict[str, str]:
        values = {
            "X-User-Id": self.user_id,
            "X-Project-Id": self.project_id,
            "X-Session-Id": self.session_id if self.project_id else None,
            "X-Tenant-Id": self.tenant,
        }
        return {k: v for k, v in values.items() if v}


SYSTEM = Identity()


def with_key(key: str, who: Identity = SYSTEM) -> dict[str, str]:
    """``X-Api-Key`` (when set) and the identity headers."""
    return {**({"X-Api-Key": key} if key else {}), **who.headers()}
