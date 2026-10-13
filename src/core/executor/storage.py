"""Shared-volume access: PATH sources we write, Step manifests the executor writes."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

TEXT_TYPES = ("text/plain", "text/markdown", "application/json")


class SharedStorage:
    def __init__(self, input_root: Path, result_root: Path, input_subdir: str):
        self.input_root, self.result_root, self.input_subdir = input_root, result_root, input_subdir

    def write_source(self, code: str) -> dict[str, str]:
        """Content-addressed, never overwritten; returns an executor PATH source."""
        data = code.encode("utf-8")
        sha = hashlib.sha256(data).hexdigest()
        relative = f"{self.input_subdir}/sources/{sha[:2]}/{sha}.py"
        target = self.input_root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(f".{os.getpid()}.tmp")
            temp.write_bytes(data)
            os.replace(temp, target)
        return {"type": "PATH", "path": relative, "sha256": sha}

    def resolve_result(self, relative_path: str) -> Path:
        path = (self.result_root / relative_path).resolve()
        if not path.is_relative_to(self.result_root.resolve()):
            raise ValueError("result path escapes the shared root")
        return path

    def read_step_outputs(self, result_ref: dict[str, Any] | None, max_chars: int = 4000) -> dict[str, Any]:
        """Bounded view of one Step manifest for the model and the UI."""
        if not result_ref:
            return {"available": False}
        manifest = json.loads(self.resolve_result(result_ref["relative_path"]).read_text("utf-8"))
        texts: list[str] = []
        images: list[str] = []
        budget = max_chars
        for output in manifest.get("outputs", []):
            for rep in output.get("representations", []):
                media = rep.get("media_type", "")
                if media.startswith("image/"):
                    images.append(rep["relative_path"])
                elif media in TEXT_TYPES and budget > 0:
                    text = self.resolve_result(rep["relative_path"]).read_text("utf-8", errors="replace")
                    texts.append(text[:budget])
                    budget -= len(texts[-1])
                    break  # one text representation per output is enough
        return {
            "available": True,
            "complete": manifest.get("complete", False),
            "text": "\n".join(texts),
            "truncated": budget <= 0,
            "images": images,
            "error": manifest.get("error_message"),
        }
