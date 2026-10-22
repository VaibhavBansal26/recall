import pytest
from fsrs import Rating

from app.agent.hint_ladder import EASY_WITHIN_MS, HintLadder, Step, rating_for


def test_correct_unaided_finishes_at_tier_zero() -> None:
    ladder = HintLadder()
    assert ladder.on_answer(True) == Step("finish", 0)
    assert ladder.finished


@pytest.mark.parametrize("correct_at", [1, 2, 3])
def test_a_wrong_answer_climbs_one_tier_and_a_correct_one_ends_it_there(correct_at: int) -> None:
    ladder = HintLadder()
    for expected_tier in range(1, correct_at):
        assert ladder.on_answer(False) == Step("advance", expected_tier)
    # Landing on `correct_at` by one more wrong answer, then getting it right at that tier.
    assert ladder.on_answer(False) == Step("advance", correct_at)
    assert ladder.on_answer(True) == Step("finish", correct_at)


def test_forgetting_walks_the_full_ladder_and_tier_three_always_ends_it() -> None:
    ladder = HintLadder()
    assert [ladder.on_give_up() for _ in range(3)] == [
        Step("advance", 1),
        Step("advance", 2),
        Step("advance", 3),
    ]
    assert ladder.on_give_up() == Step("finish", 3)
    assert ladder.finished


def test_a_wrong_answer_after_the_reveal_still_finishes_at_tier_three() -> None:
    ladder = HintLadder(tier=3)
    assert ladder.on_answer(False) == Step("finish", 3)


@pytest.mark.parametrize(
    ("tier", "latency", "rating"),
    [
        (0, None, Rating.Good),
        (0, EASY_WITHIN_MS + 1, Rating.Good),
        (0, EASY_WITHIN_MS, Rating.Easy),
        (0, 800, Rating.Easy),
        (1, 500, Rating.Hard),
        (2, None, Rating.Again),
        (3, None, Rating.Again),
    ],
)
def test_grade_mapping(tier: int, latency: int | None, rating: Rating) -> None:
    assert rating_for(tier, latency) == rating
