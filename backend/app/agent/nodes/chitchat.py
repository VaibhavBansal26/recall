import uuid
from collections.abc import AsyncIterator

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt


def chitchat_stream(deps: AgentDeps, session_id: uuid.UUID, text: str) -> AsyncIterator[str]:
    return deps.llm.stream_text(
        "fast",
        system=load_prompt("chitchat").text,
        user=text,
        session_id=session_id,
        purpose="chitchat",
    )
