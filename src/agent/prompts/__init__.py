"""Agent prompts are Markdown files: ``prompts/<agent>.md`` with optional frontmatter.

Frontmatter keys: ``skills`` (skill roots this agent may read: knowledge | analysis).
Body placeholders use ``{name}`` and are filled with str.format_map (missing keys stay as-is).
"""

from dataclasses import dataclass
from pathlib import Path

from core.assets import split_frontmatter


class _Keep(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(frozen=True)
class Prompt:
    name: str
    skills: tuple[str, ...]
    body: str

    def render(self, **values: object) -> str:
        return self.body.format_map(_Keep(values))


def load_prompt(root: Path, name: str) -> Prompt:
    meta, body = split_frontmatter((root / f"{name}.md").read_text("utf-8"))
    return Prompt(name, tuple(meta.get("skills", ())), body)
