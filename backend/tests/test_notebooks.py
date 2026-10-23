from typing import Any

from fastapi.testclient import TestClient

from app.db.models import NotebookKind
from app.services import notebooks as svc
from app.services.sessions import get_track
from tests.helpers import run_db, seed_note


def make(client: TestClient, track: str, name: str) -> dict[str, Any]:
    res = client.post("/api/notebooks", json={"track": track, "name": name})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def test_create_list_and_get_or_create_ignores_case_and_punctuation(client: TestClient) -> None:
    a = make(client, "dsa", "binary search")
    assert a["name"] == "Binary search" and a["note_count"] == 0 and a["kind"] == "notes"
    assert make(client, "dsa", "Binary-Search!")["id"] == a["id"]  # the same file
    other = make(client, "ai-eng", "Binary search")  # another track may reuse the name
    assert other["id"] != a["id"]
    assert [b["name"] for b in client.get("/api/notebooks?track=dsa").json()] == ["Binary search"]
    assert len(client.get("/api/notebooks").json()) == 2


def test_unknown_track_and_empty_names_are_rejected(client: TestClient) -> None:
    assert client.post("/api/notebooks", json={"track": "nope", "name": "x"}).status_code == 404
    assert client.post("/api/notebooks", json={"track": "dsa", "name": "!!!"}).status_code == 422
    assert client.post("/api/notebooks", json={"track": "dsa", "name": ""}).status_code == 422


def test_moving_notes_in_and_out_and_listing_them_oldest_first(client: TestClient) -> None:
    book = make(client, "dsa", "Hash map")
    first, _ = seed_note("Hash maps give O(1) lookups", "On average.", track_slug="dsa")
    second, _ = seed_note("Collisions need chaining", "Or open addressing.", track_slug="dsa")
    for note_id in (first, second):
        res = client.patch(f"/api/notes/{note_id}", json={"notebook_id": book["id"]})
        assert res.status_code == 200 and res.json()["notebook_id"] == book["id"]
    titles = [n["title"] for n in client.get(f"/api/notebooks/{book['id']}/notes").json()]
    assert titles == ["Hash maps give O(1) lookups", "Collisions need chaining"]
    assert client.get("/api/notebooks?track=dsa").json()[0]["note_count"] == 2

    # null unfiles; leaving the field out changes nothing
    assert (
        client.patch(f"/api/notes/{first}", json={"notebook_id": None}).json()["notebook_id"]
        is None
    )
    assert (
        client.patch(f"/api/notes/{second}", json={"title": "Chaining"}).json()["notebook_id"]
        == book["id"]
    )


def test_a_note_cannot_move_to_another_tracks_notebook(client: TestClient) -> None:
    ai_book = make(client, "ai-eng", "RAG")
    note, _ = seed_note("A dsa note", "Body.", track_slug="dsa")
    res = client.patch(f"/api/notes/{note}", json={"notebook_id": ai_book["id"]})
    assert res.status_code == 422


def test_renaming_and_deleting_keep_the_notes(client: TestClient) -> None:
    book = make(client, "dsa", "Trees")
    other = make(client, "dsa", "Graphs")
    note, _ = seed_note("Trees have a root", "One root.", track_slug="dsa")
    client.patch(f"/api/notes/{note}", json={"notebook_id": book["id"]})

    assert (
        client.patch(f"/api/notebooks/{book['id']}", json={"name": "Binary trees"}).json()["name"]
        == "Binary trees"
    )
    assert client.patch(f"/api/notebooks/{book['id']}", json={"name": "graphs"}).status_code == 409
    assert other["id"]

    assert client.delete(f"/api/notebooks/{book['id']}").status_code == 204
    assert client.get(f"/api/notebooks/{book['id']}/notes").status_code == 404
    kept = client.get(f"/api/notes/{note}").json()
    assert kept["title"] == "Trees have a root" and kept["notebook_id"] is None


def test_finding_a_notebook_by_a_spoken_name(client: TestClient) -> None:
    make(client, "dsa", "Binary search")
    make(client, "dsa", "Hash map basics")

    async def go(db: Any, _: Any) -> list[str | None]:
        track = await get_track(db, "dsa")
        assert track is not None
        names = []
        for spoken in ("binary search", "the binary", "hash map", "map basics", "graphs"):
            found = await svc.find(db, track.id, spoken)
            names.append(found.name if found else None)
        return names

    assert run_db(go) == [
        "Binary search",
        "Binary search",
        "Hash map basics",
        "Hash map basics",
        None,
    ]


def test_kinds_are_stored(client: TestClient) -> None:
    async def go(db: Any, _: Any) -> str:
        track = await get_track(db, "solutions")
        assert track is not None
        book, created = await svc.get_or_create(
            db, track, "Design a URL shortener", NotebookKind.discussion
        )
        assert created
        return book.kind.value

    assert run_db(go) == "discussion"
