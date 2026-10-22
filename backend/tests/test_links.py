import json
import uuid
from typing import Any

from fastapi.testclient import TestClient

from app.agent.schemas import LinkProposal, LinkProposals
from app.config import get_settings
from app.db.models import LinkKind, NoteOrigin
from app.services import links as links_svc
from app.services import notes as notes_svc
from tests.helpers import ScriptedLLM
from tests.test_capture import run_db, say, unit_vector


async def _two_notes(db: Any, track: Any, similarity: float) -> tuple[Any, Any]:
    a, _ = await notes_svc.create_note(
        db,
        track=track,
        title="Chunking splits documents",
        body_md="a",
        origin=NoteOrigin.user,
        embedding=unit_vector(1.0),
    )
    b, _ = await notes_svc.create_note(
        db,
        track=track,
        title="Chunk size matters",
        body_md="b",
        origin=NoteOrigin.user,
        embedding=unit_vector(similarity),
    )
    return a, b


def propose(llm: ScriptedLLM, similarity: float = 0.8) -> tuple[Any, Any, list[Any]]:
    async def body(db: Any, track: Any) -> tuple[Any, Any, list[Any]]:
        a, b = await _two_notes(db, track, similarity)
        created = await links_svc.propose_links(db, llm, b, get_settings())
        return (
            a.id,
            b.id,
            [
                (link.from_note_id, link.to_note_id, link.kind, link.origin, link.confirmed)
                for link in created
            ],
        )

    return run_db(body)


def test_proposed_links_are_assistant_origin_and_unconfirmed() -> None:
    llm = ScriptedLLM(
        LinkProposals(links=[LinkProposal(candidate=1, kind="prerequisite", direction="from")])
    )
    a, b, created = propose(llm)
    # direction "from": the candidate (a) points at the new note (b).
    assert created == [(a, b, LinkKind.prerequisite, NoteOrigin.assistant, False)]
    assert "[1] Chunking splits documents" in llm.users[0]


def test_direction_to_points_from_the_new_note() -> None:
    llm = ScriptedLLM(
        LinkProposals(links=[LinkProposal(candidate=1, kind="contrasts", direction="to")])
    )
    a, b, created = propose(llm)
    assert created[0][:3] == (b, a, LinkKind.contrasts)


def test_nonexistent_candidates_are_ignored() -> None:
    llm = ScriptedLLM(
        LinkProposals(links=[LinkProposal(candidate=7, kind="related", direction="to")])
    )
    assert propose(llm)[2] == []


def test_dissimilar_notes_are_never_sent_to_the_llm() -> None:
    llm = ScriptedLLM()  # would fail if it were called
    assert propose(llm, similarity=0.1)[2] == []
    assert llm.users == []


def test_an_already_linked_pair_is_not_proposed_again() -> None:
    llm = ScriptedLLM()

    async def body(db: Any, track: Any) -> list[Any]:
        a, b = await _two_notes(db, track, 0.8)
        await links_svc.create_link(
            db, from_note_id=a.id, to_note_id=b.id, kind=LinkKind.related, origin=NoteOrigin.user
        )
        return await links_svc.propose_links(db, llm, b, get_settings())

    assert run_db(body) == []
    assert llm.users == []


# ---- REST + graph ----


def make_notes(client: TestClient) -> tuple[str, str]:
    ids = []
    for title in ("Chunking", "Reranking"):
        r = client.post(
            "/api/notes", json={"track": "ai-eng", "title": title, "body_md": "x y z w"}
        )
        ids.append(r.json()["id"])
    return ids[0], ids[1]


def test_link_crud_and_confirmation(client: TestClient) -> None:
    a, b = make_notes(client)
    created = client.post(
        "/api/links", json={"from_note_id": a, "to_note_id": b, "kind": "prerequisite"}
    )
    assert created.status_code == 201
    link = created.json()
    assert link["origin"] == "user" and link["confirmed"] is True
    assert (link["from_title"], link["to_title"]) == ("Chunking", "Reranking")

    assert client.post("/api/links", json={"from_note_id": b, "to_note_id": a}).status_code == 409
    assert client.post("/api/links", json={"from_note_id": a, "to_note_id": a}).status_code == 422
    missing = {"from_note_id": str(uuid.uuid4()), "to_note_id": a}
    assert client.post("/api/links", json=missing).status_code == 404

    assert [x["id"] for x in client.get(f"/api/notes/{b}/links").json()] == [link["id"]]
    patched = client.patch(f"/api/links/{link['id']}", json={"confirmed": False}).json()
    assert patched["confirmed"] is False
    assert client.delete(f"/api/links/{link['id']}").status_code == 204
    assert client.get(f"/api/notes/{a}/links").json() == []
    assert client.delete(f"/api/links/{link['id']}").status_code == 404


def test_graph_returns_nodes_edges_and_phase3_placeholders(client: TestClient) -> None:
    a, b = make_notes(client)
    client.post("/api/links", json={"from_note_id": a, "to_note_id": b, "kind": "related"})
    graph = client.get("/api/graph?track=ai-eng").json()
    assert {n["title"] for n in graph["nodes"]} == {"Chunking", "Reranking"}
    assert all(n["strength"] is None and n["fragile"] is False for n in graph["nodes"])
    assert len(graph["edges"]) == 1 and graph["edges"][0]["kind"] == "related"
    assert client.get("/api/graph?track=nope").json() == {"nodes": [], "edges": []}


def test_deleting_a_note_removes_its_links_from_the_graph(client: TestClient) -> None:
    a, b = make_notes(client)
    client.post("/api/links", json={"from_note_id": a, "to_note_id": b, "kind": "related"})
    assert client.get(f"/api/notes/{a}/diagram").status_code == 404
    regenerated = client.post(f"/api/notes/{a}/diagram/regenerate").json()
    assert regenerated["kind"] == "mermaid" and regenerated["source"].startswith("flowchart")
    assert client.get(f"/api/notes/{a}/diagram").json()["source"] == regenerated["source"]


# ---- end to end over the websocket ----


def collect(
    ws: Any, *kinds: str, seen: list[dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """Gather the first event of each kind, starting from events a helper already consumed."""
    got: dict[str, dict[str, Any]] = {}
    for ev in seen or []:
        got.setdefault(ev["type"], ev)
    while not all(k in got for k in kinds):
        ev = ws.receive_json()
        got.setdefault(ev["type"], ev)
    return got


def test_capture_emits_notes_then_a_diagram_then_unconfirmed_links(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_text(json.dumps({"type": "start", "track": "ai-eng"}))
        ws.receive_json()
        seen = say(ws, "RAG retrieves relevant documents before generation.")
        first = collect(ws, "diagram", seen=seen)
        assert first["diagram"]["items"][0]["kind"] == "mermaid"
        assert first["diagram"]["items"][0]["source"].startswith("flowchart TD")

        ws.send_text(
            json.dumps(
                {"type": "text", "text": "RAG retrieves relevant documents using embeddings."}
            )
        )
        second = collect(ws, "links")
        link = second["links"]["items"][0]
        assert link["origin"] == "assistant" and link["confirmed"] is False
        assert link["kind"] == "related"
