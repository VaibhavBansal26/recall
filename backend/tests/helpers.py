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
from tests.test_capture import run_db  # noqa: E402

ItemSpec = tuple[str, str, PromptKind]


def seed_note(
    title: str,
    body: str,
    items: list[ItemSpec] | None = None,
    *,
    now: datetime | None = None,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Create an ai-eng note (with a fake embedding) and review items; return their ids."""

    async def go(db: Any, track: Any) -> tuple[uuid.UUID, list[uuid.UUID]]:
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
