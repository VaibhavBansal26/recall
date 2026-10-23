import uuid
from collections.abc import AsyncIterator

from app.agent import persona
from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt


async def chitchat_stream(
    deps: AgentDeps,
    session_id: uuid.UUID,
    text: str,
    *,
    track: str,
    notebook_id: uuid.UUID | None = None,
    about: bool = False,
) -> AsyncIterator[str]:
    """Small talk, and questions about Aria herself or what is in the learner's notebooks."""
    system = await persona.system_for(
        deps, load_prompt("chitchat").text, track=track, notebook_id=notebook_id
    )
    async for token in deps.llm.stream_text(
        "fast",
        system=system,
        user=text,
        session_id=session_id,
        purpose="about" if about else "chitchat",
    ):
        yield token
