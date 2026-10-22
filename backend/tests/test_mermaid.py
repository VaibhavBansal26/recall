import pytest

from app.services.mermaid import MermaidError, normalize, validate_mermaid

VALID = {
    "flowchart": [
        "flowchart TD\n  A[User] --> B[Retriever]\n  B --> C[LLM]",
        'flowchart LR\n  A["fetch (top k)"] -->|chunks| B{{Rerank}}\n  B --> C((Answer))',
        "graph TD\n  A -- reads --> B\n  B --- C",
        "flowchart TD\n  subgraph Index\n    A[Chunk] --> B[(Vector DB)]\n  end\n  B --> C[Query]",
        "flowchart TD\n  A & B --> C\n  %% a comment\n  classDef x fill:#fff",
    ],
    "sequence": [
        "sequenceDiagram\n  participant U as User\n  U->>R: asks\n  R-->>U: answers",
        "sequenceDiagram\n  User->>API: request\n  loop retry\n    API->>DB: query\n  end\n"
        "  Note over API,DB: cached",
    ],
    "mindmap": ["mindmap\n  root((RAG))\n    Retrieve\n    Generate\n      Cite sources"],
}


@pytest.mark.parametrize(("kind", "source"), [(k, s) for k, v in VALID.items() for s in v])
def test_valid_diagrams_pass(kind: str, source: str) -> None:
    assert validate_mermaid(source).kind == kind


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("", "empty"),
        ("pie\n  a: 1", "must start with"),
        ("flowchart TD\n  A[fetch (top k)] --> B", "double quotes"),
        ("flowchart TD\n  A[unterminated --> B", "closing"),
        ("flowchart TD\n  A B", "expected an edge"),
        ("flowchart TD\n  A -->", "expected a node id"),
        ("flowchart TD\n  A[] --> B", "empty node label"),
        ("flowchart TD\n  subgraph S\n    A --> B", "missing its 'end'"),
        ("flowchart TD\n  end", "without a matching subgraph"),
        ("flowchart TD\n  %% nothing else", "no nodes"),
        ("sequenceDiagram\n  participant A", "no messages"),
        ("sequenceDiagram\n  A->>B: hi\n  garbage here", "not a valid sequence"),
        ("sequenceDiagram\n  loop x\n  A->>B: hi", "missing its 'end'"),
        ("mindmap\n  root", "at least one child"),
        ("mindmap\n  root\n  other", "exactly one root"),
        ("mindmap\n  root((a)\n    child", "unbalanced"),
    ],
)
def test_invalid_diagrams_are_rejected_with_a_useful_message(source: str, message: str) -> None:
    with pytest.raises(MermaidError, match=message):
        validate_mermaid(source)


def test_error_messages_carry_the_line_number() -> None:
    with pytest.raises(MermaidError, match=r"line 3:"):
        validate_mermaid("flowchart TD\n  A --> B\n  B[oops (x)] --> C")


def test_code_fences_are_stripped() -> None:
    fenced = "```mermaid\nflowchart TD\n  A --> B\n```"
    assert normalize(fenced) == "flowchart TD\n  A --> B"
    assert validate_mermaid(fenced).source == "flowchart TD\n  A --> B"
