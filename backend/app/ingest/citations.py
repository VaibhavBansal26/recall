"""Checking that a note's cited quote really is in the cited chunk (never trust the model)."""

import re

MIN_QUOTE_WORDS = 3


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def quote_in_chunk(quote: str, chunk: str) -> bool:
    """True if the quote appears in the chunk, ignoring case, punctuation and spacing."""
    q = normalize(quote)
    return len(q.split()) >= MIN_QUOTE_WORDS and q in normalize(chunk)
