"""Text shaping for speech: split an LLM token stream into sentences, make text speakable."""

import re

_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_ABBREVIATIONS = {"e.g.", "i.e.", "vs.", "etc.", "dr.", "mr.", "mrs.", "ms.", "approx."}


def _is_abbreviation(text_before_boundary: str) -> bool:
    last = text_before_boundary.rsplit(None, 1)[-1].lower() if text_before_boundary.strip() else ""
    return last in _ABBREVIATIONS or bool(re.fullmatch(r"[a-z]\.", last))


class SentenceChunker:
    """Feed streamed tokens, get complete sentences as soon as each one ends."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, token: str) -> list[str]:
        self._buf += token
        out: list[str] = []
        pos = 0
        for m in _BOUNDARY.finditer(self._buf):
            candidate = self._buf[pos : m.start()]
            if not candidate.strip() or (m.group().strip() == "" and _is_abbreviation(candidate)):
                continue
            out.append(candidate.strip())
            pos = m.end()
        self._buf = self._buf[pos:]
        return out

    def flush(self) -> str | None:
        rest, self._buf = self._buf.strip(), ""
        return rest or None


_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+|www\.\S+")
_MD_DECOR = re.compile(r"[*_`#>~]+")
_BULLET = re.compile(r"^\s*(?:[-+•]|\d+[.)])\s+", re.MULTILINE)
_SPACES = re.compile(r"\s+")

_SYMBOLS = [
    ("->", " to "),
    ("=>", " gives "),
    ("&", " and "),
    ("%", " percent"),
    ("e.g.", "for example"),
    ("i.e.", "that is"),
    (" vs.", " versus"),
    ("/", " slash "),
]


def clean_for_speech(text: str) -> str:
    """Strip markdown and URLs and expand symbols so TTS reads natural prose."""
    text = _CODE_BLOCK.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _BULLET.sub("", text)
    for symbol, spoken in _SYMBOLS:  # before decoration is stripped, which would eat ">"
        text = text.replace(symbol, spoken)
    text = _MD_DECOR.sub("", text)
    return _SPACES.sub(" ", text).strip()
