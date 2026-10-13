"""Opaque keyset cursors: stable under inserts, no OFFSET scans."""

import base64
from datetime import datetime

from fastapi import HTTPException, Query
from sqlalchemy import and_, or_

Limit = Query(50, ge=1, le=200)


def encode(stamp: datetime, row_id: str) -> str:
    return base64.urlsafe_b64encode(f"{stamp.isoformat()}|{row_id}".encode()).decode()


def decode(cursor: str) -> tuple[datetime, str]:
    try:
        stamp, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(stamp), row_id
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "Invalid cursor.") from None


def older_than(stamp_column, id_column, cursor: str | None):
    """Filter for rows after ``cursor`` in (stamp DESC, id DESC) order."""
    if not cursor:
        return True
    stamp, row_id = decode(cursor)
    return or_(stamp_column < stamp, and_(stamp_column == stamp, id_column < row_id))
