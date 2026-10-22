from typing import Any

from app.db.models import LinkKind, NoteOrigin
from app.embeddings import FakeEmbedder
from app.services import links as links_svc
from app.services import notes as notes_svc
from app.services import retrieval
from tests.helpers import run_db, seed_note


def search(query: str, limit: int = 6) -> list[str]:
    async def go(db: Any, track: Any) -> list[str]:
        found = await retrieval.hybrid_search(
            db, FakeEmbedder(), track_slug="ai-eng", query=query, limit=limit
        )
        return [n.title for n in found]

    return run_db(go)


def test_keyword_and_vector_matches_are_both_found_and_unrelated_notes_are_not() -> None:
    seed_note("Chunk size trades recall against precision", "Smaller chunks raise precision.")
    seed_note("Reranking reorders retrieved results", "A cross encoder rescoring the top results.")
    seed_note("Gradient descent minimises loss", "Step against the gradient of the loss.")
    assert search("chunk size") == ["Chunk size trades recall against precision"]
    found = search("reranking retrieved results")
    assert found[0] == "Reranking reorders retrieved results"
    assert "Gradient descent minimises loss" not in found


def test_results_are_limited_and_empty_when_nothing_matches() -> None:
    for i in range(4):
        seed_note(f"Vector search note {i}", "Vector search uses embeddings and cosine similarity.")
    assert len(search("vector search embeddings", limit=3)) == 3
    assert search("quantum chromodynamics zebra") == []


def test_prerequisites_come_first_and_the_rest_keep_relevance_order() -> None:
    a, _ = seed_note("Embeddings basics", "Embeddings map text to vectors.")
    b, _ = seed_note("Vector search", "Vector search finds nearest embeddings.")
    c, _ = seed_note("Reranking", "Reranking rescoring results.")

    async def go(db: Any, track: Any) -> list[str]:
        # "Embeddings basics" must be understood before "Vector search".
        await links_svc.create_link(
            db, from_note_id=a, to_note_id=b, kind=LinkKind.prerequisite, origin=NoteOrigin.user
        )
        notes = [await notes_svc.get_note(db, i) for i in (b, c, a)]
        ordered = await retrieval.order_by_prerequisites(db, [n for n in notes if n])
        return [n.title for n in ordered]

    ordered = run_db(go)
    assert ordered.index("Embeddings basics") < ordered.index("Vector search")
    assert set(ordered) == {"Embeddings basics", "Vector search", "Reranking"}


def test_a_prerequisite_cycle_does_not_hang_or_drop_notes() -> None:
    a, _ = seed_note("Cycle A", "Alpha text content.")
    b, _ = seed_note("Cycle B", "Beta text content.")

    async def go(db: Any, track: Any) -> list[str]:
        for src, dst in ((a, b), (b, a)):
            await links_svc.create_link(
                db,
                from_note_id=src,
                to_note_id=dst,
                kind=LinkKind.prerequisite,
                origin=NoteOrigin.user,
            )
        notes = [await notes_svc.get_note(db, i) for i in (a, b)]
        return [
            n.title for n in await retrieval.order_by_prerequisites(db, [n for n in notes if n])
        ]

    assert sorted(run_db(go)) == ["Cycle A", "Cycle B"]
