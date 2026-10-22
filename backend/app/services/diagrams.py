import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import load_prompt
from app.agent.schemas import DiagramDraft
from app.db.models import Diagram, DiagramKind
from app.llm.client import LLMClient
from app.services.mermaid import MermaidError, validate_mermaid

log = logging.getLogger(__name__)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def fallback_steps(body_md: str) -> list[str]:
    """Plain steps taken from the note's own sentences (never new content)."""
    return [s.strip() for s in _SENTENCE.split(body_md.strip()) if s.strip()][:6]


async def build_diagram(
    llm: LLMClient,
    *,
    title: str,
    body_md: str,
    session_id: uuid.UUID | None = None,
    prompt_name: str = "diagram",
    user: str | None = None,
) -> tuple[DiagramKind, str]:
    """Generate a diagram, validate it by parsing, retry once with the parser error, then fall back.

    Returns ("mermaid", valid source) or ("steps", newline-separated steps).
    """
    system = load_prompt(prompt_name).text
    user = user or f"TITLE: {title}\nBODY:\n{body_md}"
    steps: list[str] = []
    error: str | None = None
    previous = ""
    for _attempt in range(2):
        prompt = user
        if error is not None:
            prompt += (
                f"\n\nYour previous diagram failed to parse: {error}\n"
                f"PREVIOUS DIAGRAM:\n{previous}\nReturn a corrected diagram."
            )
        draft = await llm.complete_structured(
            "deep", system=system, user=prompt, schema=DiagramDraft, session_id=session_id
        )
        steps = draft.steps or steps
        try:
            return DiagramKind.mermaid, validate_mermaid(draft.mermaid).source
        except MermaidError as exc:
            log.warning("diagram rejected (%s): %s", title[:40], exc)
            error, previous = str(exc), draft.mermaid
    return DiagramKind.steps, "\n".join(steps or fallback_steps(body_md))


async def get_diagram(db: AsyncSession, note_id: uuid.UUID) -> Diagram | None:
    return (
        await db.execute(select(Diagram).where(Diagram.note_id == note_id))
    ).scalar_one_or_none()


async def save_diagram(
    db: AsyncSession, note_id: uuid.UUID, kind: DiagramKind, source: str
) -> Diagram:
    diagram = await get_diagram(db, note_id)
    if diagram is None:
        diagram = Diagram(note_id=note_id, kind=kind, source=source)
        db.add(diagram)
    else:
        diagram.kind, diagram.source = kind, source
    await db.commit()
    return diagram
