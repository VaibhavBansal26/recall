"""Data-driven tracks: each `*.yaml` in this folder defines one track.

Adding a track is a new YAML file plus prompts, not a new code path.
"""

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


class TrackConfig(BaseModel):
    slug: str
    name: str
    description: str = ""
    endpointing: Endpointing = Endpointing()


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
