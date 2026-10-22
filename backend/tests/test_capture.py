import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import EMBEDDING_DIM
from app.db.models import CaptureAction, Note, NoteOrigin
from app.db.session import make_engine, make_sessionmaker
from app.services import notes as svc
from app.services.sessions import get_track
from tests.conftest import TEST_DB_URL


def unit_vector(similarity_to_e0: float) -> list[float]:
    """A unit vector whose cosine similarity to e0 is `similarity_to_e0`."""
    v = [0.0] * EMBEDDING_DIM
    v[0] = similarity_to_e0
    v[1] = (1 - similarity_to_e0**2) ** 0.5
    return v


async def _with_db(fn: Any) -> Any:
    engine = make_engine(TEST_DB_URL)
    try:
        async with make_sessionmaker(engine)() as db:
            track = await get_track(db, "ai-eng")
            assert track is not None
            return await fn(db, track)
    finally:
        await engine.dispose()


def run_db(fn: Any) -> Any:
    return asyncio.run(_with_db(fn))


# ---- dedup / merge / undo at the service level (controlled vectors) ----


@pytest.mark.parametrize(
    ("similarity", "is_duplicate"), [(0.95, True), (0.89, True), (0.85, False), (0.2, False)]
)
def test_dedup_threshold_is_cosine_088(similarity: float, is_duplicate: bool) -> None:
    async def body(db: Any, track: Any) -> Any:
        await svc.create_note(
            db,
            track=track,
            title="Existing note",
            body_md="x",
            origin=NoteOrigin.user,
            embedding=unit_vector(1.0),
        )
        return await svc.find_duplicate(
            db, track.id, "A different title", unit_vector(similarity), 0.88
        )

    found = run_db(body)
    assert (found is not None) is is_duplicate
    if found:
        assert found[1] == pytest.approx(similarity, abs=1e-3)


def test_same_title_is_a_duplicate_even_with_unrelated_embedding() -> None:
    async def body(db: Any, track: Any) -> Any:
        await svc.create_note(
            db,
            track=track,
            title="Chunk size trades recall for precision",
            body_md="x",
            origin=NoteOrigin.user,
            embedding=unit_vector(1.0),
        )
        return await svc.find_duplicate(
            db, track.id, "  chunk size TRADES recall for precision ", unit_vector(0.0), 0.88
        )

    found = run_db(body)
    assert found is not None and found[1] == 1.0


def test_merge_then_undo_restores_the_note_and_undoing_a_create_deletes_it() -> None:
    async def body(db: Any, track: Any) -> None:
        note, created = await svc.create_note(
            db,
            track=track,
            title="T",
            body_md="original",
            origin=NoteOrigin.user,
            embedding=unit_vector(1.0),
        )
        merge = await svc.merge_into(
            db, note=note, body_md="original plus more", embedding=unit_vector(0.9), similarity=0.9
        )
        assert merge.action == CaptureAction.merged and note.body_md == "original plus more"

        await svc.undo_capture(db, merge.id)
        assert note.body_md == "original"
        assert note.embedding is not None and float(note.embedding[0]) == pytest.approx(1.0)

        assert created is not None
        await svc.undo_capture(db, created.id)
        assert (await db.execute(select(Note).where(Note.id == note.id))).first() is None

    run_db(body)


# ---- end to end over the websocket ----


def say(ws: Any, text: str) -> list[dict[str, Any]]:
    ws.send_text(json.dumps({"type": "text", "text": text}))
    events: list[dict[str, Any]] = []
    while not any(e["type"] == "notes" for e in events) or not any(
        e["type"] == "assistant_done" for e in events
    ):
        events.append(ws.receive_json())
    return events


def test_capture_creates_atomic_notes_and_a_repeat_merges_instead_of_duplicating(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_text(json.dumps({"type": "start", "track": "ai-eng"}))
        ws.receive_json()

        first = say(
            ws,
            "RAG retrieves relevant documents before generation. "
            "Chunk size trades recall against precision. Um, okay.",
        )
        items = next(e for e in first if e["type"] == "notes")["items"]
        assert [i["action"] for i in items] == ["created", "created"]  # filler sentence dropped
        assert all(i["origin"] == "user" and i["confirmed"] for i in items)

        second = say(ws, "RAG retrieves relevant documents before generation.")
        again = next(e for e in second if e["type"] == "notes")["items"]
        assert [i["action"] for i in again] == ["merged"]
        assert again[0]["note_id"] == items[0]["note_id"]
        assert again[0]["before_body_md"] == items[0]["body_md"]

    titles = [n["title"] for n in client.get("/api/notes?track=ai-eng").json()]
    assert sorted(titles) == [
        "Chunk size trades recall against precision",
        "RAG retrieves relevant documents before generation",
    ]


def test_undo_endpoint_reverts_a_capture(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_text(json.dumps({"type": "start", "track": "ai-eng"}))
        ws.receive_json()
        items = next(
            e for e in say(ws, "Embeddings map text into vectors.") if e["type"] == "notes"
        )["items"]

    undone = client.post(f"/api/capture-events/{items[0]['event_id']}/undo").json()
    assert undone["undone"] is True
    assert client.get("/api/notes?track=ai-eng").json() == []
    assert client.post(f"/api/capture-events/{uuid.uuid4()}/undo").status_code == 404


def test_notes_crud(client: TestClient) -> None:
    created = client.post(
        "/api/notes", json={"track": "ai-eng", "title": "Evals", "body_md": "Test the system."}
    )
    assert created.status_code == 201 and created.json()["origin"] == "user"
    note_id = created.json()["id"]

    patched = client.patch(f"/api/notes/{note_id}", json={"body_md": "Test the whole system."})
    assert patched.json()["body_md"] == "Test the whole system."
    assert client.get(f"/api/notes/{note_id}").json()["title"] == "Evals"
    assert client.get(f"/api/notes/{uuid.uuid4()}").status_code == 404
