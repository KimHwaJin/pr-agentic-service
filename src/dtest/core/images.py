"""Images users send with a turn.

Stored once under ``<STORAGE_ROOT>/images/users/<employee>/projects/<p>/
sessions/<s>/<image_id>.<ext>`` and referenced by id everywhere else (the
chat history, the agent checkpoint). The bytes reach the model only at call
time (see ``agent.middleware.persona``), so checkpoints stay small.
"""

import base64
import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from PIL import UnidentifiedImageError
from sqlalchemy import delete, select

from src.dtest.core.db import Database, new_id
from src.dtest.core.executor.storage import safe_part
from src.dtest.core.models import Image

MAX_SIDE = 1568  # longest side sent to the model
FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class ImageError(ValueError):
    pass


@dataclass(frozen=True)
class Prepared:
    data: bytes
    mime_type: str
    width: int
    height: int


def prepare(encoded: str, mime_type: str, max_bytes: int) -> Prepared:
    """Decode, check it is really that kind of image, shrink if needed."""
    if mime_type not in FORMATS:
        raise ImageError(f"unsupported image type {mime_type}")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ImageError("base64 is not valid") from None
    if len(raw) > max_bytes:
        raise ImageError(f"image is larger than {max_bytes} bytes")
    try:
        image = PILImage.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise ImageError("not a readable image") from None
    if image.format != FORMATS[mime_type]:
        raise ImageError(f"content is {image.format}, not {mime_type}")
    if max(image.size) <= MAX_SIDE:
        return Prepared(raw, mime_type, *image.size)
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    if FORMATS[mime_type] == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, format=FORMATS[mime_type])
    return Prepared(out.getvalue(), mime_type, *image.size)


class Images:
    def __init__(self, db: Database, storage_root: Path):
        self.db, self.root = db, storage_root

    async def save(
        self,
        prepared: Prepared,
        *,
        user_id: str,
        employee_id: str,
        project_id: str,
        session_id: str,
        run_id: str | None,
        name: str | None,
    ) -> Image:
        image_id = new_id()
        relative = "/".join(
            [
                "images",
                "users",
                safe_part(employee_id),
                "projects",
                safe_part(project_id),
                "sessions",
                safe_part(session_id),
                f"{image_id}.{EXTENSIONS[prepared.mime_type]}",
            ]
        )
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temp.write_bytes(prepared.data)
        os.replace(temp, target)
        row = Image(
            id=image_id,
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            run_id=run_id,
            name=name,
            mime_type=prepared.mime_type,
            size_bytes=len(prepared.data),
            width=prepared.width,
            height=prepared.height,
            sha256=hashlib.sha256(prepared.data).hexdigest(),
            path=relative,
        )
        async with self.db.sessions() as db:
            db.add(row)
            await db.commit()
        return row

    async def get(self, image_id: str) -> Image | None:
        async with self.db.sessions() as db:
            return await db.get(Image, image_id)

    def file(self, image: Image) -> Path:
        path = (self.root / image.path).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("image path escapes the storage root")
        return path

    def read_base64(self, image: Image) -> str:
        return base64.b64encode(self.file(image).read_bytes()).decode()

    async def remove(self, image_ids: list[str]) -> None:
        """Delete images (files and rows), e.g. when a run was refused."""
        if not image_ids:
            return
        async with self.db.sessions() as db:
            rows = (
                await db.scalars(select(Image).where(Image.id.in_(image_ids)))
            ).all()
            for row in rows:
                self.file(row).unlink(missing_ok=True)
            await db.execute(delete(Image).where(Image.id.in_(image_ids)))
            await db.commit()
