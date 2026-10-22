from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db.models import PromptKind
from app.tracks import get_track_config, guidance_for, load_track_configs
from tests.helpers import Conv, ScriptedLLM, run_db, seed_note

SLUGS = ["ai-eng", "dsa", "solutions", "english"]
# A phrase that appears only in that track's capture guidance.
CAPTURE_MARK = {
    "dsa": "pattern notes",
    "solutions": '"Problem: ..."',
    "english": "wants to say better",
}


# ---- the tracks are data ----


def test_all_four_tracks_are_defined_as_config() -> None:
    configs = {c.slug: c for c in load_track_configs()}
    assert sorted(configs) == sorted(SLUGS)
    for slug in ("dsa", "solutions", "english"):
        g = configs[slug].guidance
        assert g.capture and g.explain and g.quiz, slug
        assert configs[slug].description
    assert configs["ai-eng"].guidance.capture == ""  # unchanged behaviour for the first track


def test_each_track_differs_in_the_ways_the_spec_asks() -> None:
    assert get_track_config("dsa").walkthrough_diagrams is True
    assert all(
        not get_track_config(s).walkthrough_diagrams for s in ("ai-eng", "solutions", "english")
    )
    assert "complexity" in get_track_config("dsa").guidance.capture.lower()
    sol = get_track_config("solutions").guidance.capture
    assert all(label in sol for label in ("Problem:", "Approach:", "Tradeoff:", "Decision:"))
    assert (
        "teach_back" and get_track_config("english").guidance.teach_back
    )  # teach-back is its focus
    # Spoken English gets longer to finish a thought before it is cut off.
    assert (
        get_track_config("english").endpointing.capture_silence_ms
        > get_track_config("ai-eng").endpointing.capture_silence_ms
    )


def test_guidance_is_appended_to_a_prompt_only_when_the_track_has_some() -> None:
    assert guidance_for("ai-eng", "capture") == ""
    assert guidance_for("nonexistent", "capture") == ""
    dsa = guidance_for("dsa", "capture")
    assert (
        dsa.startswith("\n\nTRACK GUIDANCE (Data Structures & Algorithms):")
        and "pattern notes" in dsa
    )


def test_tracks_are_listed_by_the_api_with_their_names(client: TestClient) -> None:
    listed = {t["slug"]: t["name"] for t in client.get("/api/tracks").json()}
    assert listed["dsa"] == "Data Structures & Algorithms" and listed["english"] == "Spoken English"


# ---- the guidance really reaches the model, per track ----


class RecordingLLM:
    """Wraps the fake LLM and remembers every system prompt it was given."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.systems: list[tuple[str, str]] = []  # (purpose or schema name, system)

    async def complete_structured(self, kind: Any, *, system: str, schema: type, **kw: Any) -> Any:
        self.systems.append((schema.__name__, system))
        return await self.inner.complete_structured(kind, system=system, schema=schema, **kw)

    def stream_text(self, kind: Any, *, system: str, purpose: str = "ack", **kw: Any) -> Any:
        self.systems.append((purpose, system))
        return self.inner.stream_text(kind, system=system, purpose=purpose, **kw)

    def system_for(self, name: str) -> str:
        return next(s for n, s in self.systems if n == name)


def recording(client: TestClient) -> RecordingLLM:
    deps = client.app.state.deps  # type: ignore[attr-defined]
    llm = RecordingLLM(deps.llm)
    deps.llm = llm
    return llm


@pytest.mark.parametrize("slug", SLUGS)
def test_capture_is_shaped_by_the_tracks_guidance(client: TestClient, slug: str) -> None:
    llm = recording(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start(slug)
        conv.say("This is a sentence that is long enough to become a note.")
        conv.kind("notes")
    system = llm.system_for("ExtractedNotes")
    assert ("TRACK GUIDANCE" in system) == (slug in CAPTURE_MARK)
    for other, mark in CAPTURE_MARK.items():
        assert (mark in system) == (other == slug)  # one track's rules never leak into another's


@pytest.mark.parametrize("slug", ["dsa", "solutions", "english"])
def test_enrichment_uses_the_tracks_review_and_link_guidance(client: TestClient, slug: str) -> None:
    llm = recording(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start(slug)
        conv.say("This is a sentence that is long enough to become a note.")
        conv.kind("notes")
        conv.kind("diagram")
    assert guidance_for(slug, "review").strip() in llm.system_for("ReviewDrafts")
    assert guidance_for(slug, "diagram").strip() in llm.system_for("DiagramDraft") or slug == "dsa"


@pytest.mark.parametrize("slug", ["dsa", "solutions", "english"])
def test_explanations_follow_the_tracks_style(client: TestClient, slug: str) -> None:
    llm = recording(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start(slug)
        conv.say("explain how two pointers work")
        conv.kind("assistant_done")
    assert any(guidance_for(slug, "explain").strip() in system for _, system in llm.systems)


def test_quizzing_follows_the_tracks_style(client: TestClient) -> None:
    llm = recording(client)
    seed_note(
        "Two pointers: sorted pair",
        "Use two pointers on a sorted array.",
        [("When to use it?", "sorted arrays", PromptKind.question)],
        track_slug="dsa",
    )
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.send(type="quiz")
        conv.kind("quiz", phase="asking")
        conv.say("no idea")
        conv.kind("quiz", phase="hint")
    assert guidance_for("dsa", "quiz").strip() in llm.system_for("QuizTurn")


# ---- end to end: pick a track and talk ----


@pytest.mark.parametrize("slug", ["dsa", "solutions", "english"])
def test_talking_in_a_track_files_notes_there_and_uses_its_guidance(
    client: TestClient, slug: str
) -> None:
    llm = recording(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        assert conv.start(slug)["track"] == slug
        conv.say("This is a sentence that is long enough to become a note.")
        conv.kind("notes")
    assert CAPTURE_MARK[slug] in llm.system_for("ExtractedNotes")
    assert len(client.get(f"/api/notes?track={slug}").json()) == 1
    assert client.get("/api/notes?track=ai-eng").json() == []  # tracks keep their notes apart


def test_a_track_does_not_see_another_tracks_notes_when_reading_back(client: TestClient) -> None:
    seed_note(
        "Binary search halves the range",
        "Binary search halves the range each step.",
        track_slug="dsa",
    )
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("english")
        conv.say("read me my notes on binary search")
        conv.kind("assistant_done")
        assert "don't have any notes about binary search" in conv.spoken()
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("read me my notes on binary search")
        assert conv.kind("read_back")["title"] == "Binary search halves the range"


def test_run_db_helper_still_defaults_to_the_first_track() -> None:
    async def go(db: Any, track: Any) -> str:
        return str(track.slug)

    assert run_db(go) == "ai-eng"
    assert ScriptedLLM().systems == []
