"""Split text into overlapping chunks of roughly 500-800 tokens (about 450 words)."""

import re

TARGET_WORDS = 450  # ~600 tokens
OVERLAP_WORDS = 60  # ~80 tokens carried into the next chunk so ideas are not cut at the seam

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _units(text: str, target: int) -> list[str]:
    """Paragraphs, then sentences, then raw word runs: nothing larger than `target` words."""
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        if len(paragraph.split()) <= target:
            units.append(paragraph)
            continue
        for sentence in _SENTENCE.split(paragraph):
            words = sentence.split()
            for start in range(0, len(words), target):  # e.g. an unpunctuated transcript
                units.append(" ".join(words[start : start + target]))
    return units


def chunk_text(
    text: str, target_words: int = TARGET_WORDS, overlap_words: int = OVERLAP_WORDS
) -> list[str]:
    units = _units(text, target_words)
    chunks: list[str] = []
    current: list[str] = []
    count = 0

    def close() -> None:
        nonlocal current, count
        body = " ".join(current).strip()
        if body:
            chunks.append(body)
        tail = body.split()[-overlap_words:] if overlap_words else []
        current, count = ([" ".join(tail)] if tail else []), len(tail)

    for unit in units:
        n = len(unit.split())
        if current and count + n > target_words:
            close()
        current.append(unit)
        count += n
    if count > (overlap_words if chunks else 0):  # a trailing chunk with new content in it
        close()
    return chunks
