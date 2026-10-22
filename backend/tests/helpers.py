import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from app.llm.client import LLMClient, ModelKind, T


class ScriptedLLM(LLMClient):
    """Returns queued structured responses in order and records every prompt it was given."""

    def __init__(self, *responses: BaseModel) -> None:
        self.responses = list(responses)
        self.users: list[str] = []
        self.systems: list[str] = []

    async def complete_structured(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        schema: type[T],
        session_id: uuid.UUID | None = None,
    ) -> T:
        self.users.append(user)
        self.systems.append(system)
        response: Any = self.responses.pop(0)
        assert isinstance(response, schema)
        return response

    async def stream_text(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        session_id: uuid.UUID | None = None,
        purpose: str = "ack",
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover


# ---- database seeding for recall tests ----

from datetime import datetime  # noqa: E402

from app.db.models import NoteOrigin, PromptKind  # noqa: E402
from app.embeddings import FakeEmbedder  # noqa: E402
from app.services import notes as notes_svc  # noqa: E402
from app.services import reviews as reviews_svc  # noqa: E402
from app.services.sessions import get_track  # noqa: E402
from tests.test_capture import run_db  # noqa: E402

ItemSpec = tuple[str, str, PromptKind]


def seed_note(
    title: str,
    body: str,
    items: list[ItemSpec] | None = None,
    *,
    now: datetime | None = None,
    track_slug: str = "ai-eng",
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Create a note (default track ai-eng, with a fake embedding) and review items; return ids."""

    async def go(db: Any, default_track: Any) -> tuple[uuid.UUID, list[uuid.UUID]]:
        track = await get_track(db, track_slug)
        assert track is not None
        note, _ = await notes_svc.create_note(
            db,
            track=track,
            title=title,
            body_md=body,
            origin=NoteOrigin.user,
            embedding=FakeEmbedder._one(f"{title}\n{body}"),
            record_event=False,
        )
        ids = []
        for prompt, answer, kind in items or []:
            item = await reviews_svc.create_item(
                db, note, kind=kind, prompt=prompt, answer=answer, now=now
            )
            ids.append(item.id)
        return note.id, ids

    return run_db(go)


# ---- websocket conversation helper ----

import json  # noqa: E402
from collections.abc import Callable  # noqa: E402


class Conv:
    """Drives /ws/voice and remembers every event it has read, so nothing is lost between waits."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.seen: list[dict[str, Any]] = []
        self._claimed: set[int] = set()

    def start(self, track: str = "ai-eng") -> dict[str, Any]:
        self.ws.send_text(json.dumps({"type": "start", "track": track}))
        return self.until(lambda e: e["type"] == "session")

    def say(self, text: str) -> None:
        self.ws.send_text(json.dumps({"type": "text", "text": text}))

    def send(self, **event: Any) -> None:
        self.ws.send_text(json.dumps(event))

    def until(self, pred: Callable[[dict[str, Any]], bool], limit: int = 120) -> dict[str, Any]:
        for _ in range(limit):
            event = self.ws.receive_json()
            self.seen.append(event)
            if pred(event):
                return event
        kinds = [e["type"] for e in self.seen[-20:]]
        raise AssertionError(f"event not seen in {limit} events; last kinds: {kinds}")

    def kind(self, kind: str, limit: int = 120, **match: Any) -> dict[str, Any]:
        """The next unclaimed event of this kind, whether it already arrived or is still coming.

        Order-insensitive on purpose: another wait may have read past it, and each event can be
        claimed once.
        """

        def ok(e: dict[str, Any]) -> bool:
            return e["type"] == kind and all(e.get(k) == v for k, v in match.items())

        for _ in range(limit):
            for i, event in enumerate(self.seen):
                if i not in self._claimed and ok(event):
                    self._claimed.add(i)
                    return event
            self.seen.append(self.ws.receive_json())
        kinds = [e["type"] for e in self.seen[-20:]]
        raise AssertionError(f"no {kind} {match} in {limit} events; last kinds: {kinds}")

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.seen if e["type"] == kind]

    def spoken(self) -> str:
        return " ".join(e["text"] for e in self.of("assistant_delta"))


# ---- ingestion fixtures ----

import textwrap  # noqa: E402


def make_pdf(text: str) -> bytes:
    """A minimal one-page PDF containing `text` (enough for pypdf to extract it)."""
    escape = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    lines = textwrap.wrap(text, 90)[:55]
    stream = (
        "BT /F1 9 Tf 11 TL 30 800 Td "
        + " T* ".join(f"({escape(line)}) Tj" for line in lines)
        + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


ARTICLE_PARAGRAPHS = [
    "Retrieval augmented generation fetches relevant documents before the model writes an answer, "
    "which grounds the response in real sources and reduces made up details in the final output.",
    "Chunk size is a trade off between recall and precision because smaller chunks match queries "
    "more exactly while larger chunks keep more surrounding context for the model to read.",
    "A reranking step reorders the retrieved chunks with a slower and more accurate model so that "
    "the best evidence appears first in the prompt that the language model receives.",
    "Embeddings map text into vectors so that similar meanings land close together, and vector "
    "search then finds the nearest chunks to a query using cosine similarity between them.",
    "Evaluation of a retrieval system should measure both whether the right chunks were found and "
    "whether the final answer actually used them faithfully without adding unsupported claims.",
    "Caching frequent queries and their retrieved context can cut latency and cost noticeably "
    "while still keeping answers fresh when the underlying documents change only occasionally.",
]


def article_html(title: str = "RAG in practice", paragraphs: list[str] | None = None) -> str:
    body = "".join(f"<p>{p}</p>" for p in (paragraphs or ARTICLE_PARAGRAPHS))
    return (
        f"<html><head><title>{title} - Some Blog</title>"
        f'<meta property="og:title" content="{title}"></head><body>'
        "<nav>Home About Contact Subscribe</nav><header>Site header banner</header>"
        f"<article><h1>{title}</h1>{body}</article>"
        "<aside>Related posts you may like</aside><footer>Copyright footer text</footer>"
        "<script>var tracking = 1;</script></body></html>"
    )
