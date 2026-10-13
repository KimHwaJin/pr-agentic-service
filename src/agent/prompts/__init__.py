"""Agent prompts are Markdown files: ``prompts/<agent>.md`` with optional frontmatter.

Frontmatter keys: ``skills`` (skill roots this agent may read: knowledge | analysis).
Body placeholders use ``{name}`` and are filled with str.format_map (missing keys stay as-is).
"""

from dataclasses import dataclass
from pathlib import Path

from core.assets import AssetLoader, split_frontmatter


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


_loaders: dict[Path, AssetLoader] = {}


def _parse(root: Path) -> dict[str, Prompt]:
    prompts = {}
    for path in root.glob("*.md"):
        meta, body = split_frontmatter(path.read_text("utf-8"))
        prompts[path.stem] = Prompt(path.stem, tuple(meta.get("skills", ())), body)
    return prompts


def load_prompt(root: Path, name: str) -> Prompt:
    """Edited prompt files apply to the next model call without a restart."""
    loader = _loaders.setdefault(root, AssetLoader(root, _parse))
    return loader.get()[name]
