from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fsrs import Rating
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.db.models import PromptKind
from app.main import create_app
from app.services import reviews as reviews_svc
from tests.helpers import Conv, run_db, seed_note

ANSWER = "an answer here"


def weak_notes(count: int = 3) -> list[str]:
    """Reviewed a while ago, so they are the weakest; each has one question answered by ANSWER."""
    now = datetime.now(UTC)
    ids = []
    for i in range(count):
        reviewed_at = now - timedelta(days=30 + 10 * i)
        note_id, (item_id,) = seed_note(
            f"Weak topic {i}",
            f"Weak topic {i} body text here.",
            [(f"Question {i}: what is it?", ANSWER, PromptKind.question)],
            now=reviewed_at - timedelta(minutes=5),
        )

        async def grade(
            db: Any, track: Any, item_id: Any = item_id, at: datetime = reviewed_at
        ) -> None:
            item = await reviews_svc.get_item(db, item_id)
            assert item is not None
            await reviews_svc.grade_item(db, item, Rating.Good, now=at)

        run_db(grade)
        ids.append(str(note_id))
    return ids


# ---- the endpoint the n8n cron calls ----


def test_the_morning_cron_builds_one_brief_and_calling_again_returns_it(client: TestClient) -> None:
    notes = weak_notes(3)
    first = client.post("/api/sessions/daily-brief")
    assert first.status_code == 201
    brief = first.json()
    assert brief["status"] == "ready" and brief["created"] is True and brief["track"] == "ai-eng"
    assert {q["note_id"] for q in brief["questions"]} == set(notes)
    assert all("answer" not in q and q["prompt"] for q in brief["questions"])
    assert brief["due_today"] >= 3

    again = client.post("/api/sessions/daily-brief")
    assert (
        again.status_code == 200
        and again.json()["id"] == brief["id"]
        and again.json()["created"] is False
    )


def test_an_unknown_track_is_404_and_an_empty_day_gives_an_empty_brief(client: TestClient) -> None:
    assert client.post("/api/sessions/daily-brief?track=nope").status_code == 404
    brief = client.post("/api/sessions/daily-brief").json()
    assert brief["status"] == "empty" and brief["questions"] == []
    assert client.get("/api/briefs/ready").json() is None  # nothing to prompt about


def test_the_ready_prompt_shows_until_the_brief_is_started(client: TestClient) -> None:
    weak_notes(2)
    brief = client.post("/api/sessions/daily-brief").json()
    ready = client.get("/api/briefs/ready").json()
    assert ready["id"] == brief["id"] and len(ready["questions"]) == 2
    assert client.get(f"/api/briefs/{brief['id']}").json()["status"] == "ready"
    assert client.get("/api/briefs/00000000-0000-0000-0000-0000000000ab").status_code == 404


# ---- running the brief by voice ----


def test_the_brief_runs_as_a_short_spoken_session_and_ends_with_whats_due(
    client: TestClient,
) -> None:
    weak_notes(3)
    brief = client.post("/api/sessions/daily-brief").json()
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.send(type="quiz", brief_id=brief["id"])
        conv.kind("mode", mode="recall_quiz")
        asking = conv.kind("quiz", phase="asking")
        assert asking["position"] == 1 and asking["total"] == 3
        conv.kind("assistant_done")
        assert "Good morning" in conv.spoken() and "3 topics that are slipping" in conv.spoken()

        for number in (1, 2, 3):
            conv.say(ANSWER)
            graded = conv.kind("quiz", phase="graded")
            assert graded["tier"] == 0 and graded["grade"] in ("Good", "Easy")
            conv.kind("assistant_done")
            if number < 3:
                assert conv.kind("quiz", phase="asking")["position"] == number + 1
        ended = conv.kind("quiz", phase="ended")
        assert ended["summary"]["total"] == 3 and ended["summary"]["unaided"] == 3
        assert "due today" in conv.spoken()  # the one-line "what's due today"
        conv.kind("mode", mode="capture")

    assert client.get(f"/api/briefs/{brief['id']}").json()["status"] == "completed"
    assert client.get("/api/briefs/ready").json() is None
    assert client.get("/api/stats").json()["reviews_today"] == 3


def test_saying_start_my_brief_builds_it_if_the_cron_has_not_run(client: TestClient) -> None:
    weak_notes(3)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("start my daily brief")
        conv.kind("mode", mode="recall_quiz")
        assert conv.kind("quiz", phase="asking")["total"] == 3
    assert client.get("/api/briefs/ready").json() is None  # it was started, so no more prompt


def test_asking_again_after_finishing_says_it_is_done(client: TestClient) -> None:
    weak_notes(1)
    brief = client.post("/api/sessions/daily-brief").json()
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.send(type="quiz", brief_id=brief["id"])
        conv.kind("quiz", phase="asking")
        conv.kind("assistant_done")
        conv.send(type="quiz_action", action="end")  # stop early: the brief counts as done
        conv.kind("quiz", phase="ended")
        conv.kind("assistant_done")
        conv.say("morning brief")
        conv.kind("assistant_done")
        assert "already done today's brief" in conv.spoken()


def test_an_empty_brief_by_voice_says_there_is_nothing_yet(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("start my brief")
        conv.kind("assistant_done")
        assert "nothing to put in a brief" in conv.spoken()


# ---- stats ----


def test_stats_summarise_reviews_streaks_retention_and_weak_notes(client: TestClient) -> None:
    empty = client.get("/api/stats").json()
    assert empty["due_now"] == 0 and empty["streak_current"] == 0 and empty["retention_7d"] is None
    assert len(empty["retention_curve"]) == 30 and empty["weak_nodes"] == []
    assert empty["articulation_trend"] == []  # arrives with the English track

    weak_notes(2)
    _, (due_id,) = seed_note(
        "Due now", "Due now body text.", [("Q?", "a b c d", PromptKind.question)]
    )
    before = client.get("/api/stats").json()
    assert (
        before["due_now"] == 3 and before["items_total"] == 3
    )  # the stale two are overdue too and before["items_reviewed"] == 2
    assert before["notes_total"] == 3 and len(before["weak_nodes"]) == 2
    assert all(w["strength"] is not None for w in before["weak_nodes"])
    assert before["average_retrievability"] is not None and before["average_retrievability"] < 0.9

    client.post(f"/api/reviews/{due_id}/grade", json={"grade": "good"})
    client.post(f"/api/reviews/{due_id}/grade", json={"grade": "again", "hint_tier_used": 3})
    after = client.get("/api/stats").json()
    assert after["reviewed_today"] is True and after["reviews_today"] == 2
    assert after["streak_current"] == 1 and after["streak_longest"] == 1
    assert after["retention_7d"] == pytest.approx(0.5) and after[
        "unaided_rate_30d"
    ] == pytest.approx(0.5)
    today = after["retention_curve"][-1]
    assert today["reviews"] == 2 and today["recalled"] == 1 and today["retention"] == 0.5
    assert client.get("/api/stats?track=nope").json()["items_total"] == 0


def test_stats_count_sources_waiting_for_approval(client: TestClient) -> None:
    assert client.get("/api/stats").json()["sources_awaiting"] == 0


# ---- n8n access and configuration ----


@pytest.fixture
def secured(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for key, value in {
        "AUTH_PASSPHRASE": "correct horse battery staple",
        "SESSION_SECRET": "s" * 40,
        "RECALL_SHARED_SECRET": "n8n-shared-secret-0123456789",
        "CORS_ORIGINS": '["http://localhost:3000"]',
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        with TestClient(create_app(), base_url="http://localhost:3000") as client:
            yield client
    finally:
        get_settings.cache_clear()


def test_n8n_can_build_the_brief_and_read_stats_but_not_the_ready_prompt(
    secured: TestClient,
) -> None:
    good = {"X-Recall-Secret": "n8n-shared-secret-0123456789"}
    assert secured.post("/api/sessions/daily-brief").status_code == 401
    assert secured.post("/api/sessions/daily-brief", headers=good).status_code == 201
    assert secured.get("/api/stats", headers=good).status_code == 200
    assert secured.get("/api/stats").status_code == 401
    assert secured.get("/api/briefs/ready", headers=good).status_code == 401  # browser-only


def test_an_invalid_time_zone_refuses_to_start() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, user_timezone="Mars/Olympus_Mons")  # type: ignore[call-arg]
    assert Settings(_env_file=None, user_timezone="Asia/Kolkata").user_timezone == "Asia/Kolkata"  # type: ignore[call-arg]
