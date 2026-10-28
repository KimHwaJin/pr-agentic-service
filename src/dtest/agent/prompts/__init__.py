"""Agent prompts are Markdown files: ``prompts/<agent>.md``.

Each file may start with frontmatter. Frontmatter keys: ``skills`` (skill
roots this agent may read: knowledge | analysis). Body placeholders use
``{name}``; only the names passed to ``render`` are replaced.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from src.dtest.core.assets import AssetLoader, split_frontmatter


@dataclass(frozen=True)
class Prompt:
    name: str
    skills: tuple[str, ...]
    body: str

    def render(self, **values: object) -> str:
        """Fills the {name} placeholders that are given.

        Any other braces (JSON examples) stay as written.
        """
        return re.sub(
            r"\{(\w+)\}",
            lambda m: (
                str(values[m.group(1)]) if m.group(1) in values else m.group(0)
            ),
            self.body,
        )


ROOT = Path(__file__).parent


def _parse(root: Path) -> dict[str, Prompt]:
    prompts = {}
    for path in root.glob("*.md"):
        meta, body = split_frontmatter(path.read_text("utf-8"))
        prompts[path.stem] = Prompt(
            path.stem, tuple(meta.get("skills", ())), body
        )
    return prompts


_loader = AssetLoader(ROOT, _parse)


def load_prompt(name: str) -> Prompt:
    """Edited prompt files apply to the next model call without a restart."""
    return _loader.get()[name]
