import pytest

from app.services.scoring import (
    Word,
    compute_metrics,
    count_fillers,
    sentence_stats,
    words_from_text,
)


def tokens(text: str) -> list[str]:
    return text.split()


# ---- filler words ----


def test_simple_fillers_are_counted_by_kind() -> None:
    counts = count_fillers(tokens("So um the index is uh basically a tree and umm actually fast"))
    assert counts == {"um": 2, "uh": 1, "basically": 1, "actually": 1}


def test_you_know_is_a_filler_only_when_set_off_not_in_a_real_question() -> None:
    assert count_fillers(tokens("It is, you know, a vector")) == {"you know": 1}
    assert count_fillers(tokens("It maps text to vectors, you know.")) == {"you know": 1}
    assert count_fillers(tokens("Do you know how it works")) == {}
    assert count_fillers(tokens("If you know the key you can look it up")) == {}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It is, like, a database", 1),  # set off by commas
        ("so like it keeps going", 1),  # "so like" lead-in
        ("and it was like totally slow", 1),
        ("I like databases", 0),  # a verb
        ("It looks like a tree", 0),  # looks like
        ("It is like a tree", 0),  # comparison: "like a"
        ("Things like caches help", 0),
        ("Would you like to hear more", 0),
        ("We do like indexes", 0),
    ],
)
def test_like_is_counted_only_when_it_is_a_filler(text: str, expected: int) -> None:
    assert count_fillers(tokens(text)).get("like", 0) == expected


def test_punctuation_and_case_do_not_hide_fillers() -> None:
    assert count_fillers(tokens("Um, UH... Basically, ACTUALLY.")) == {
        "um": 1,
        "uh": 1,
        "basically": 1,
        "actually": 1,
    }


# ---- pace and pauses (timed words) ----


def timed(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(t, s, e) for t, s, e in spec]


def steady(n: int, start: float = 0.0, per_word: float = 0.4) -> list[Word]:
    """n words, each `per_word` seconds long with no gaps."""
    return [Word(f"w{i}", start + i * per_word, start + (i + 1) * per_word) for i in range(n)]


def test_words_per_minute_comes_from_the_word_timings() -> None:
    m = compute_metrics(steady(60, per_word=0.4))  # 60 words in 24 s = 150 wpm
    assert (
        m.word_count == 60 and m.duration_s == pytest.approx(24.0) and m.wpm == pytest.approx(150.0)
    )


def test_wpm_is_withheld_when_the_span_or_the_text_is_too_short_to_mean_anything() -> None:
    assert compute_metrics(steady(8)).wpm is None  # under 10 words
    assert compute_metrics(steady(10, per_word=0.1)).wpm is None  # under 3 seconds
    assert compute_metrics(steady(10, per_word=0.4)).wpm == pytest.approx(150.0)


def test_typed_answers_have_no_timings_so_no_pace_or_pauses() -> None:
    m = compute_metrics(
        words_from_text("An index is a sorted structure that speeds up lookups a lot.")
    )
    assert m.wpm is None and m.duration_s is None and m.long_pauses == 0 and m.word_count == 12


def test_long_pauses_are_gaps_of_a_second_and_a_half_or_more_between_words() -> None:
    words = timed(
        [
            ("First", 0.0, 0.4),
            ("it", 0.5, 0.6),  # 0.1 s: normal
            ("hashes", 2.4, 2.9),  # 1.8 s gap: long
            ("the", 3.0, 3.1),
            ("key", 5.6, 5.9),  # 2.5 s gap: longest
            ("quickly", 6.0, 6.5),
        ]
    )
    m = compute_metrics(words)
    assert m.long_pauses == 2 and m.longest_pause_s == pytest.approx(2.5)
    assert [(p.after_word, p.seconds) for p in m.pauses] == [
        ("the", 2.5),
        ("it", 1.8),
    ]  # longest first


def test_a_gap_just_under_the_threshold_is_not_a_long_pause() -> None:
    m = compute_metrics(timed([("a", 0.0, 0.5), ("b", 1.99, 2.4)]))
    assert m.long_pauses == 0


# ---- fillers as a rate ----


def test_filler_rate_is_per_hundred_words() -> None:
    text = "um " + " ".join(["word"] * 98) + " uh"  # 100 words, 2 fillers
    m = compute_metrics(words_from_text(text))
    assert m.word_count == 100 and m.filler_count == 2 and m.filler_rate == 2.0
    assert compute_metrics([]).filler_rate == 0.0


# ---- sentences ----


def test_sentence_lengths_are_bucketed() -> None:
    short = "It is a tree."  # 4
    medium = "The index stores keys in sorted order so that lookups stay fast."  # 12
    long = " ".join(["word"] * 25) + "."
    s = sentence_stats(f"{short} {medium} {long}")
    assert (s.count, s.short, s.medium, s.long, s.longest) == (3, 1, 1, 1, 25)
    assert s.mean == pytest.approx((4 + 12 + 25) / 3, abs=0.1) and s.punctuated is True


def test_unpunctuated_text_is_one_long_run_and_says_so() -> None:
    s = sentence_stats("so the index is a tree and it keeps keys sorted and lookups are fast")
    assert s.count == 1 and s.punctuated is False and s.long == 0 and s.medium == 1


def test_metrics_are_deterministic() -> None:
    words = steady(40)
    assert compute_metrics(words) == compute_metrics(words)
