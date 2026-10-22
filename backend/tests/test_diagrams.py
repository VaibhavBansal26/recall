import asyncio

from app.agent.schemas import DiagramDraft
from app.db.models import DiagramKind
from app.services.diagrams import build_diagram, fallback_steps
from tests.helpers import ScriptedLLM

BODY = "RAG retrieves context first. The model then answers from it. This reduces guessing."
GOOD = "flowchart TD\n  A[Retrieve] --> B[Answer]"
BAD = "flowchart TD\n  A[fetch (top k)] --> B"


def build(llm: ScriptedLLM) -> tuple[DiagramKind, str]:
    return asyncio.run(build_diagram(llm, title="RAG", body_md=BODY))


def test_valid_diagram_is_used_as_is() -> None:
    llm = ScriptedLLM(DiagramDraft(mermaid=GOOD))
    assert build(llm) == (DiagramKind.mermaid, GOOD)
    assert len(llm.users) == 1


def test_invalid_diagram_is_retried_once_with_the_parser_error() -> None:
    llm = ScriptedLLM(DiagramDraft(mermaid=BAD), DiagramDraft(mermaid=GOOD))
    assert build(llm) == (DiagramKind.mermaid, GOOD)
    retry_prompt = llm.users[1]
    assert "failed to parse" in retry_prompt and "double quotes" in retry_prompt
    assert BAD in retry_prompt


def test_two_invalid_attempts_fall_back_to_the_llms_steps() -> None:
    llm = ScriptedLLM(
        DiagramDraft(mermaid=BAD, steps=["Retrieve context", "Answer from it"]),
        DiagramDraft(mermaid="not mermaid"),
    )
    assert build(llm) == (DiagramKind.steps, "Retrieve context\nAnswer from it")
    assert len(llm.users) == 2  # exactly one retry


def test_fallback_without_steps_uses_the_notes_own_sentences() -> None:
    llm = ScriptedLLM(DiagramDraft(mermaid=BAD), DiagramDraft(mermaid=BAD))
    kind, source = build(llm)
    assert kind == DiagramKind.steps
    assert (
        source.split("\n")
        == fallback_steps(BODY)
        == [
            "RAG retrieves context first.",
            "The model then answers from it.",
            "This reduces guessing.",
        ]
    )
