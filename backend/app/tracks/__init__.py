"""Data-driven tracks: each `*.yaml` in this folder defines one track.

Adding a track is a new YAML file plus prompts, not a new code path.
"""

from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track

TRACKS_DIR = Path(__file__).parent


class Endpointing(BaseModel):
    silence_ms: int = 700
    capture_silence_ms: int = 1200


class Guidance(BaseModel):
    """Per-track instructions appended to the shared prompts. This is how tracks differ."""

    capture: str = ""  # how notes taken from speech (and from sources) are shaped
    explain: str = ""
    quiz: str = ""
    review: str = ""  # what practice questions to write
    links: str = ""  # how notes relate
    diagram: str = ""
    teach_back: str = ""  # what to look for when the learner explains something back


class TrackConfig(BaseModel):
    slug: str
    name: str
    description: str = ""
    endpointing: Endpointing = Endpointing()
    guidance: Guidance = Guidance()
    # Algorithm notes get a step-by-step position diagram (pointers on an array) where it fits.
    walkthrough_diagrams: bool = False
    # Things worth explaining out loud, offered as teach-back ideas.
    teach_back_ideas: list[str] = []


@cache
def _configs_by_slug() -> dict[str, TrackConfig]:
    return {c.slug: c for c in load_track_configs()}


def get_track_config(slug: str) -> TrackConfig:
    """The YAML config for a track (a plain default for an unknown slug)."""
    return _configs_by_slug().get(slug) or TrackConfig(slug=slug, name=slug)


def guidance_for(slug: str, key: str) -> str:
    """A suffix for a system prompt carrying the track's instructions for `key`, or ''."""
    cfg = get_track_config(slug)
    text = str(getattr(cfg.guidance, key, "")).strip()
    return f"\n\nTRACK GUIDANCE ({cfg.name}):\n{text}" if text else ""


def load_track_configs(directory: Path = TRACKS_DIR) -> list[TrackConfig]:
    return [
        TrackConfig.model_validate(yaml.safe_load(path.read_text()))
        for path in sorted(directory.glob("*.yaml"))
    ]


async def sync_tracks(db: AsyncSession, configs: list[TrackConfig] | None = None) -> None:
    """Upsert YAML track definitions into the `tracks` table by slug."""
    for cfg in configs if configs is not None else load_track_configs():
        existing = (
            await db.execute(select(Track).where(Track.slug == cfg.slug))
        ).scalar_one_or_none()
        config = cfg.model_dump(exclude={"slug", "name"})
        if existing is None:
            db.add(Track(slug=cfg.slug, name=cfg.name, config=config))
        else:
            existing.name = cfg.name
            existing.config = config
    await db.commit()
