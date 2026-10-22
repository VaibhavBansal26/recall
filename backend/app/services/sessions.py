import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LOCAL_USER_ID
from app.db.models import LearningSession, Speaker, Track, Utterance
from app.llm.client import Usage
from app.schemas import SessionDetail, SessionOut, UsageOut, UtteranceOut


async def get_track(db: AsyncSession, slug: str) -> Track | None:
    return (await db.execute(select(Track).where(Track.slug == slug))).scalar_one_or_none()


async def list_tracks(db: AsyncSession) -> list[Track]:
    return list((await db.execute(select(Track).order_by(Track.slug))).scalars())


async def create_session(db: AsyncSession, track: Track) -> LearningSession:
    session = LearningSession(user_id=LOCAL_USER_ID, track=track)
    db.add(session)
    await db.commit()
    return session


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> LearningSession | None:
    return (
        await db.execute(select(LearningSession).where(LearningSession.id == session_id))
    ).scalar_one_or_none()


async def add_utterance(
    db: AsyncSession,
    session_id: uuid.UUID,
    speaker: Speaker,
    text: str,
    confidence: float | None = None,
    words: list[dict[str, Any]] | None = None,
) -> Utterance:
    utterance = Utterance(
        session_id=session_id, speaker=speaker, text=text, confidence=confidence, words=words
    )
    db.add(utterance)
    await db.commit()
    return utterance


def to_session_out(session: LearningSession) -> SessionOut:
    return SessionOut(
        id=session.id,
        track=session.track.slug,
        mode=session.mode,
        started_at=session.started_at,
        ended_at=session.ended_at,
        summary=session.summary,
    )


def to_session_detail(session: LearningSession, usage: Usage | None = None) -> SessionDetail:
    return SessionDetail(
        **to_session_out(session).model_dump(),
        utterances=[UtteranceOut.model_validate(u) for u in session.utterances],
        usage=UsageOut(**asdict(usage)) if usage else None,
    )
