"""Shared-volume access.

PATH sources we write, Step manifests the executor writes.
"""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

TEXT_TYPES = ("text/plain", "text/markdown", "application/json")


_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def safe_part(value: str) -> str:
    """One path segment from an id or a name (no separators, no dot-dirs)."""
    part = _SAFE.sub("-", value).strip(".") or "-"
    return part[:128]


class SharedStorage:
    def __init__(
        self, storage_root: Path, executor_path: str, result_root: Path
    ):
        # storage_root: this service's folder on the executor input PV;
        # executor_path: the same folder relative to INPUT_STORAGE_ROOT
        self.storage_root = storage_root
        self.executor_path = executor_path.strip("/")
        self.result_root = result_root

    @property
    def sources_root(self) -> Path:
        return self.storage_root / "sources"

    def write_source(
        self, code: str, relative: str
    ) -> tuple[dict[str, str], int]:
        """Write-once code file under ``sources/``.

        If the file already exists (a tool re-run after a resume or a pod
        failover) its content is reused, so the executor always gets the
        code first sent for that path. Returns the executor PATH source and
        the file size.
        """
        target = (self.sources_root / relative).resolve()
        if not target.is_relative_to(self.sources_root.resolve()):
            raise ValueError("source path escapes the storage root")
        if target.exists():
            data = target.read_bytes()
        else:
            data = code.encode("utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            temp.write_bytes(data)
            os.replace(temp, target)
        path = "/".join(
            p for p in (self.executor_path, "sources", relative) if p
        )
        sha = hashlib.sha256(data).hexdigest()
        return {"type": "PATH", "path": path, "sha256": sha}, len(data)

    def delete_source(self, executor_path: str) -> None:
        """Remove a sent file and the folders it leaves empty."""
        prefix = (
            f"{self.executor_path}/sources/"
            if self.executor_path
            else "sources/"
        )
        if not executor_path.startswith(prefix):
            return
        target = self.sources_root / executor_path[len(prefix) :]
        target.unlink(missing_ok=True)
        root = self.sources_root.resolve()
        parent = target.parent.resolve()
        while parent != root and parent.is_relative_to(root):
            try:
                parent.rmdir()  # only when empty
            except OSError:
                break
            parent = parent.parent

    def resolve_result(self, relative_path: str) -> Path:
        path = (self.result_root / relative_path).resolve()
        if not path.is_relative_to(self.result_root.resolve()):
            raise ValueError("result path escapes the shared root")
        return path

    def read_step_outputs(
        self, result_ref: dict[str, Any] | None, max_chars: int = 12000
    ) -> dict[str, Any]:
        """Bounded view of one Step manifest for the model and the UI."""
        if not result_ref:
            return {"available": False}
        try:
            manifest = json.loads(
                self.resolve_result(result_ref["relative_path"]).read_text(
                    "utf-8"
                )
            )
        except (OSError, ValueError) as exc:
            # a missing or broken manifest is one step's problem, not the
            # whole operation's: the caller still records every result
            return {
                "available": False,
                "error": f"결과 파일을 읽지 못했습니다: {type(exc).__name__}",
            }
        texts: list[str] = []
        images: list[str] = []
        budget, truncated = max_chars, False
        for output in manifest.get("outputs", []):
            reps = output.get("representations", [])
            images += [
                r["relative_path"]
                for r in reps
                if r.get("media_type", "").startswith("image/")
            ]
            if any(r.get("media_type", "").startswith("image/") for r in reps):
                # a figure's text/plain twin ("<Figure ...>") adds nothing
                continue
            text_rep = next(
                (r for r in reps if r.get("media_type") in TEXT_TYPES), None
            )
            if text_rep and not truncated:
                text = self._read_text(text_rep["relative_path"], budget + 1)
                truncated = len(text) > budget
                texts.append(text[:budget])
                budget -= len(texts[-1])
        return {
            "available": True,
            "complete": manifest.get("complete", False),
            "text": "\n".join(texts),
            "truncated": truncated,
            "images": images,
            "error": manifest.get("error_message"),
        }

    def step_source(
        self, result_ref: dict[str, Any], limit: int = 2000
    ) -> str:
        """The step's code as the executor snapshotted it, or ""."""
        try:
            manifest = json.loads(
                self.resolve_result(result_ref["relative_path"]).read_text(
                    "utf-8"
                )
            )
            source = manifest.get("source") or {}
            if not source.get("relative_path"):
                return ""
            with self.resolve_result(source["relative_path"]).open(
                encoding="utf-8", errors="replace"
            ) as file:
                return file.read(limit)
        except (OSError, ValueError):
            return ""

    def _read_text(self, relative_path: str, limit: int) -> str:
        """At most ``limit`` characters; outputs can be very large."""
        try:
            with self.resolve_result(relative_path).open(
                encoding="utf-8", errors="replace"
            ) as file:
                return file.read(limit)
        except OSError as exc:
            return f"(출력 파일을 읽지 못했습니다: {type(exc).__name__})"
