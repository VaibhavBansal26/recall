"""Strict parser for the Mermaid subset we generate: flowchart, sequenceDiagram, mindmap.

Mermaid's own parser only exists in JavaScript, so the backend validates in Python before saving.
The grammar is deliberately narrower than Mermaid's: anything outside it is rejected so the model
is asked to retry with a plain construct. The frontend still parses again at render time.
"""

import re
from dataclasses import dataclass


class MermaidError(ValueError):
    """Raised with a line-numbered message the model can act on."""


@dataclass(frozen=True)
class ValidDiagram:
    kind: str  # "flowchart" | "sequence" | "mindmap"
    source: str


_FENCE = re.compile(r"^\s*```(?:mermaid)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def normalize(source: str) -> str:
    """Strip a Markdown code fence and surrounding blank lines the model may have added."""
    text = source.strip("\n\r ")
    fenced = _FENCE.match(text)
    return (fenced.group(1) if fenced else text).strip("\n\r ")


def validate_mermaid(source: str) -> ValidDiagram:
    text = normalize(source)
    lines = text.split("\n")
    content = [
        (n, ln) for n, ln in enumerate(lines, 1) if ln.strip() and not ln.strip().startswith("%%")
    ]
    if not content:
        raise MermaidError("diagram is empty")
    first_no, first = content[0]
    header = first.strip()
    body = content[1:]
    if re.fullmatch(r"(flowchart|graph)\s+(TD|TB|LR|RL|BT)", header):
        _flowchart(body)
        return ValidDiagram("flowchart", text)
    if header == "sequenceDiagram":
        _sequence(body)
        return ValidDiagram("sequence", text)
    if header == "mindmap":
        _mindmap(body)
        return ValidDiagram("mindmap", text)
    raise MermaidError(
        f"line {first_no}: must start with 'flowchart TD|LR', 'sequenceDiagram' or 'mindmap', "
        f"got {header!r}"
    )


# ---------------------------------------------------------------- flowchart

_ID = re.compile(r"[A-Za-z0-9_]+")
# (open, close), longest opener first.
_SHAPES = [
    ("((", "))"),
    ("([", "])"),
    ("[(", ")]"),
    ("[[", "]]"),
    ("{{", "}}"),
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
    (">", "]"),
]
_LABEL_FORBIDDEN = set('[](){}"')
_EDGE = re.compile(r"(?:<-->|-->|==>|-\.->|-\.-|---|===|~~~|--[ox])(?:\|[^|\n]*\|)?")
_TEXT_EDGE = re.compile(r"(?:--|==|-\.)\s+[^\n]*?\s+(?:-->|==>|-\.->|---)")
_FLOW_KEYWORDS = ("direction ", "classDef ", "class ", "style ", "linkStyle ", "click ")


def _flowchart(body: list[tuple[int, str]]) -> None:
    statements = 0
    depth = 0
    for no, raw in body:
        line = raw.strip().rstrip(";").strip()
        if line.startswith("subgraph"):
            if not line[len("subgraph") :].strip():
                raise MermaidError(f"line {no}: subgraph needs a title")
            depth += 1
        elif line == "end":
            depth -= 1
            if depth < 0:
                raise MermaidError(f"line {no}: 'end' without a matching subgraph")
        elif line.startswith(_FLOW_KEYWORDS):
            continue
        else:
            _flow_statement(no, line)
            statements += 1
    if depth != 0:
        raise MermaidError("subgraph is missing its 'end'")
    if statements == 0:
        raise MermaidError("flowchart has no nodes or edges")


def _flow_node(no: int, line: str, i: int) -> int:
    m = _ID.match(line, i)
    if not m:
        raise MermaidError(
            f"line {no}: expected a node id at column {i + 1}, got {line[i : i + 12]!r}"
        )
    i = m.end()
    for opener, closer in _SHAPES:
        if not line.startswith(opener, i):
            continue
        start = i + len(opener)
        if line.startswith('"', start):
            end_quote = line.find('"', start + 1)
            if end_quote == -1:
                raise MermaidError(f"line {no}: unterminated quote in node label")
            if not line.startswith(closer, end_quote + 1):
                raise MermaidError(f"line {no}: expected {closer!r} after the quoted label")
            if end_quote == start + 1:
                raise MermaidError(f"line {no}: empty node label")
            return end_quote + 1 + len(closer)
        end = line.find(closer, start)
        if end == -1:
            raise MermaidError(f"line {no}: node label is missing its closing {closer!r}")
        label = line[start:end]
        if not label.strip():
            raise MermaidError(f"line {no}: empty node label")
        bad = _LABEL_FORBIDDEN & set(label)
        if bad:
            raise MermaidError(
                f"line {no}: label {label!r} contains {''.join(sorted(bad))!r}; "
                'wrap the whole label in double quotes, e.g. A["text (with parens)"]'
            )
        return end + len(closer)
    return i


def _flow_statement(no: int, line: str) -> None:
    i = _flow_node(no, line, 0)
    while True:
        while i < len(line) and line[i] == " ":
            i += 1
        if i >= len(line):
            return
        if line[i] == "&":
            i = _flow_node(no, line, _skip_ws(line, i + 1))
            continue
        edge = _EDGE.match(line, i) or _TEXT_EDGE.match(line, i)
        if not edge:
            raise MermaidError(f"line {no}: expected an edge like '-->' at column {i + 1}")
        i = _flow_node(no, line, _skip_ws(line, edge.end()))


def _skip_ws(line: str, i: int) -> int:
    while i < len(line) and line[i] == " ":
        i += 1
    return i


# ---------------------------------------------------------------- sequence

_PARTICIPANT = re.compile(r"(?:participant|actor)\s+\S+(?:\s+as\s+.+)?")
_MESSAGE = re.compile(r"[^\s:]+\s*(?:-->>|->>|-->|->|--x|-x|--\)|-\))\s*[+-]?[^\s:]+\s*:\s*\S.*")
_NOTE = re.compile(r"Note\s+(?:over|left of|right of)\s+[^:]+:\s*\S.*")
_BLOCK_OPEN = re.compile(r"(?:loop|alt|opt|par|critical|break|rect)\b.*")
_BLOCK_MID = re.compile(r"(?:else|and|option)\b.*")
_SEQ_SIMPLE = re.compile(r"(?:autonumber|activate\s+\S+|deactivate\s+\S+|title\s+.+)")


def _sequence(body: list[tuple[int, str]]) -> None:
    messages = 0
    depth = 0
    for no, raw in body:
        line = raw.strip()
        if _MESSAGE.fullmatch(line):
            messages += 1
        elif (
            _PARTICIPANT.fullmatch(line)
            or _NOTE.fullmatch(line)
            or _SEQ_SIMPLE.fullmatch(line)
            or _BLOCK_MID.fullmatch(line)
        ):
            continue
        elif _BLOCK_OPEN.fullmatch(line):
            depth += 1
        elif line == "end":
            depth -= 1
            if depth < 0:
                raise MermaidError(f"line {no}: 'end' without a matching block")
        else:
            raise MermaidError(f"line {no}: not a valid sequence diagram line: {line!r}")
    if depth != 0:
        raise MermaidError("a loop/alt/opt block is missing its 'end'")
    if messages == 0:
        raise MermaidError("sequence diagram has no messages like 'A->>B: text'")


# ---------------------------------------------------------------- mindmap


def _mindmap(body: list[tuple[int, str]]) -> None:
    if len(body) < 2:
        raise MermaidError("mindmap needs a root and at least one child")
    indents: list[tuple[int, int, str]] = []
    for no, raw in body:
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise MermaidError(f"line {no}: use spaces, not tabs, to indent a mindmap")
        text = raw.strip()
        if text.count("(") != text.count(")") or text.count("[") != text.count("]"):
            raise MermaidError(f"line {no}: unbalanced brackets in {text!r}")
        indents.append((no, len(raw) - len(raw.lstrip()), text))
    root_indent = min(i for _, i, _ in indents)
    roots = [t for _, i, t in indents if i == root_indent]
    if len(roots) != 1 or indents[0][1] != root_indent:
        raise MermaidError("mindmap must have exactly one root, as its first line")
