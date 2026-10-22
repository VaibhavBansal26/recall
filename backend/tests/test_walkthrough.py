import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.schemas import WalkthroughDraft, WalkthroughStep
from app.db.models import DiagramKind
from app.llm.client import UsageTracker
from app.llm.fake import FakeLLM
from app.services.diagrams import build_walkthrough
from app.services.walkthrough import WalkthroughError, validate_walkthrough
from tests.helpers import Conv, ScriptedLLM

ARRAY = ["1", "3", "5", "7", "9", "11"]


def draft(**over: Any) -> WalkthroughDraft:
    base: dict[str, Any] = {
        "applicable": True,
        "array": ARRAY,
        "steps": [
            WalkthroughStep(
                caption="Start at both ends.", pointers={"left": 0, "right": 5}, highlight=[0, 5]
            ),
            WalkthroughStep(caption="Move left up.", pointers={"left": 1, "right": 5}),
        ],
    }
    base.update(over)
    return WalkthroughDraft(**base)


# ---- validation ----


def test_a_good_walkthrough_is_stored_as_json_with_pointer_positions() -> None:
    data = json.loads(validate_walkthrough(draft()))
    assert data["array"] == ARRAY and len(data["steps"]) == 2
    assert data["steps"][0] == {
        "caption": "Start at both ends.",
        "pointers": {"left": 0, "right": 5},
        "highlight": [0, 5],
    }


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"applicable": False}, "not applicable"),
        ({"array": ["1"]}, "array must have"),
        ({"array": [str(i) for i in range(30)]}, "array must have"),
        ({"steps": [WalkthroughStep(caption="Only one step.")]}, "need 2 to"),
        (
            {
                "steps": [
                    WalkthroughStep(caption="ok", pointers={"i": 0}),
                    WalkthroughStep(caption="bad", pointers={"i": 6}),
                ]
            },
            "outside 0..5",
        ),
        (
            {
                "steps": [
                    WalkthroughStep(caption="ok"),
                    WalkthroughStep(caption="neg", pointers={"i": -1}),
                ]
            },
            "outside 0..5",
        ),
        (
            {
                "steps": [
                    WalkthroughStep(caption="ok"),
                    WalkthroughStep(caption="hl", highlight=[9]),
                ]
            },
            "highlight index",
        ),
        ({"steps": [WalkthroughStep(caption="ok"), WalkthroughStep(caption="  ")]}, "caption"),
        (
            {
                "steps": [
                    WalkthroughStep(caption="ok"),
                    WalkthroughStep(caption="swap", array=["1", "2"]),
                ]
            },
            "same length",
        ),
        (
            {
                "steps": [
                    WalkthroughStep(caption="ok"),
                    WalkthroughStep(caption="long name", pointers={"waytoolongname": 1}),
                ]
            },
            "pointer names",
        ),
    ],
)
def test_walkthroughs_that_cannot_be_drawn_are_rejected_with_a_reason(
    override: dict[str, Any], message: str
) -> None:
    with pytest.raises(WalkthroughError, match=message):
        validate_walkthrough(draft(**override))


def test_a_step_may_change_the_arrays_values() -> None:
    swapped = ["3", "1", "5", "7", "9", "11"]
    data = json.loads(
        validate_walkthrough(
            draft(
                steps=[
                    WalkthroughStep(caption="Start."),
                    WalkthroughStep(caption="Swap the first two.", array=swapped),
                ]
            )
        )
    )
    assert data["steps"][1]["array"] == swapped


# ---- building ----

BAD = draft(
    steps=[
        WalkthroughStep(caption="a", pointers={"i": 0}),
        WalkthroughStep(caption="b", pointers={"i": 99}),
    ]
)


def build(llm: Any) -> str | None:
    return asyncio.run(
        build_walkthrough(llm, title="Two pointers", body_md="Use two pointers on a sorted array.")
    )


def test_not_applicable_ideas_get_no_walkthrough() -> None:
    llm = ScriptedLLM(WalkthroughDraft(applicable=False))
    assert build(llm) is None and len(llm.users) == 1


def test_an_invalid_walkthrough_is_retried_once_with_the_reason() -> None:
    llm = ScriptedLLM(BAD, draft())
    assert build(llm) is not None
    assert "outside 0..5" in llm.users[1] and "rejected" in llm.users[1]


def test_two_invalid_attempts_give_up_so_the_caller_can_fall_back() -> None:
    llm = ScriptedLLM(BAD, BAD)
    assert build(llm) is None and len(llm.users) == 2


# ---- per track ----


def test_a_dsa_procedure_note_gets_a_walkthrough_and_other_tracks_get_mermaid(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say(
            "Two pointers walks a left and a right pointer inward over a sorted array to find a pair."
        )
        conv.kind("notes")
        item = conv.kind("diagram")["items"][0]
    assert item["kind"] == "walkthrough"
    data = json.loads(item["source"])
    assert data["array"] == ARRAY and data["steps"][-1]["pointers"] == {"left": 1, "right": 4}

    stored = client.get(f"/api/notes/{item['note_id']}/diagram").json()
    assert stored["kind"] == DiagramKind.walkthrough.value

    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("ai-eng")
        conv.say(
            "Two pointers walks a left and a right pointer inward over a sorted array to find a pair."
        )
        conv.kind("notes")
        assert conv.kind("diagram")["items"][0]["kind"] == "mermaid"  # the first track is unchanged


def test_a_dsa_note_that_is_not_array_based_falls_back_to_a_normal_diagram(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("A hash map trades extra memory for constant time lookups on average.")
        conv.kind("notes")
        assert conv.kind("diagram")["items"][0]["kind"] == "mermaid"


def test_the_fake_model_only_draws_walkthroughs_for_pointer_style_ideas() -> None:
    llm = FakeLLM(UsageTracker())
    yes = asyncio.run(
        llm.complete_structured(
            "deep",
            system="",
            user="TITLE: x\nBODY:\nbinary search on an array",
            schema=WalkthroughDraft,
        )
    )
    no = asyncio.run(
        llm.complete_structured(
            "deep", system="", user="TITLE: x\nBODY:\nhash maps", schema=WalkthroughDraft
        )
    )
    assert yes.applicable and not no.applicable
