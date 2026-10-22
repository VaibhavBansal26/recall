"""Versioned prompt files. Each `*.md` starts with a `version: N` front-matter line."""

import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path

log = logging.getLogger(__name__)
PROMPTS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str


@cache
def load_prompt(name: str) -> Prompt:
    raw = (PROMPTS_DIR / f"{name}.md").read_text()
    _, header, body = raw.split("---\n", 2)
    version = int(header.split("version:", 1)[1].strip())
    log.debug("loaded prompt %s v%d", name, version)
    return Prompt(name=name, version=version, text=body.strip())
