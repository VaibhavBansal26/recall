"""WebSocket contract for /ws/voice. Mirrored by frontend/lib/events.ts."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.agent.state import CaptureItem, DiagramItem, LinkItem
from app.db.models import Speaker
from app.services.scoring import Metrics

# ---- client -> server ----


class StartEvent(BaseModel):
    type: Literal["start"] = "start"
    track: str = "ai-eng"
    session_id: uuid.UUID | None = None


class TextEvent(BaseModel):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=8000)


class InterruptEvent(BaseModel):
    type: Literal["interrupt"] = "interrupt"


class SpeechStartEvent(BaseModel):
    """Client-side VAD heard the user start talking (used for instant barge-in)."""

    type: Literal["speech_start"] = "speech_start"


class EndSpeechEvent(BaseModel):
    """Push-to-talk released: flush whatever was said as a final transcript."""

    type: Literal["end_speech"] = "end_speech"


class QuizStartEvent(BaseModel):
    """Begin a quiz: of what is due, or practice on one note (the map's "Quiz me on this")."""

    type: Literal["quiz"] = "quiz"
    note_id: uuid.UUID | None = None
    brief_id: uuid.UUID | None = None  # start the spoken daily brief instead


class QuizActionEvent(BaseModel):
    """Button equivalents of the spoken commands."""

    type: Literal["quiz_action"] = "quiz_action"
    action: Literal["hint", "forgot", "skip", "end"]


class TeachBackStartEvent(BaseModel):
    """Begin a teach-back: the learner will explain `topic` out loud."""

    type: Literal["teachback_start"] = "teachback_start"
    topic: str | None = None


class TeachBackDoneEvent(BaseModel):
    """The learner has finished explaining (button equivalent of "I'm done")."""

    type: Literal["teachback_done"] = "teachback_done"
    cancel: bool = False


class NotebookOpenEvent(BaseModel):
    """Choose the notebook new notes go into (null closes it)."""

    type: Literal["notebook_open"] = "notebook_open"
    notebook_id: uuid.UUID | None = None


class ReciteStartEvent(BaseModel):
    """Recite a notebook (explain each note and ask questions in between)."""

    type: Literal["recite_start"] = "recite_start"
    notebook_id: uuid.UUID | None = None


class DiscussStartEvent(BaseModel):
    type: Literal["discuss_start"] = "discuss_start"
    topic: str


ClientMessage = (
    StartEvent
    | TextEvent
    | InterruptEvent
    | SpeechStartEvent
    | EndSpeechEvent
    | QuizStartEvent
    | QuizActionEvent
    | TeachBackStartEvent
    | TeachBackDoneEvent
    | NotebookOpenEvent
    | ReciteStartEvent
    | DiscussStartEvent
)
ClientEvent = Annotated[ClientMessage, Field(discriminator="type")]
client_event_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientEvent)

# ---- server -> client ----


class SessionEvent(BaseModel):
    type: Literal["session"] = "session"
    session_id: uuid.UUID
    track: str
    audio_input: bool = False


class TranscriptEvent(BaseModel):
    """Live partial transcript while the user is speaking."""

    type: Literal["transcript"] = "transcript"
    text: str
    final: bool = False


class UtteranceEvent(BaseModel):
    """A stored utterance. The UI renders the transcript from these."""

    type: Literal["utterance"] = "utterance"
    id: uuid.UUID
    speaker: Speaker
    text: str
    interrupted: bool = False


class NotesEvent(BaseModel):
    type: Literal["notes"] = "notes"
    items: list[CaptureItem]


class DiagramEvent(BaseModel):
    type: Literal["diagram"] = "diagram"
    items: list[DiagramItem]


class LinksEvent(BaseModel):
    """Assistant-proposed links, unconfirmed until the user accepts them."""

    type: Literal["links"] = "links"
    items: list[LinkItem]


class QuizSummary(BaseModel):
    total: int
    unaided: int
    hinted: int
    revealed: int
    fragile: int


class QuizStateEvent(BaseModel):
    """Display payload for recall_quiz: the question, the hint ladder tier, the grade."""

    type: Literal["quiz"] = "quiz"
    phase: Literal["asking", "hint", "graded", "ended", "empty"]
    item_id: uuid.UUID | None = None
    note_id: uuid.UUID | None = None
    note_title: str | None = None
    prompt: str | None = None
    tier: int = 0
    hint: str | None = None
    answer: str | None = None  # only once revealed (tier 3) or graded
    grade: str | None = None
    fragile: bool = False
    next_due: datetime | None = None
    position: int = 0
    total: int = 0
    summary: QuizSummary | None = None


class ExplainEvent(BaseModel):
    """An explanation (what/how/why/impact) with its diagram, optionally saved as a note."""

    type: Literal["explain"] = "explain"
    explain_id: uuid.UUID
    topic: str
    simple: bool = False
    text: str
    diagram: DiagramItem | None = None
    note_id: uuid.UUID | None = None  # the learner's note it was grounded on, if any


class ReadBackEvent(BaseModel):
    type: Literal["read_back"] = "read_back"
    index: int
    total: int
    note_id: uuid.UUID | None = None
    title: str | None = None
    body_md: str | None = None
    why: str | None = None
    speed: float = 1.0
    finished: bool = False


class ConfusionEvent(BaseModel):
    """Confusion was detected: the note was marked fragile and is being re-explained simply."""

    type: Literal["confusion"] = "confusion"
    trigger: str
    note_id: uuid.UUID | None = None


class TeachBackBeat(BaseModel):
    present: bool
    evidence: str = ""


class TeachBackRewrite(BaseModel):
    original: str
    improved: str


class TeachBackEvent(BaseModel):
    """Teach-back progress and, once scored, the objective metrics plus structure scoring."""

    type: Literal["teachback"] = "teachback"
    phase: Literal["listening", "scoring", "scored", "too_short", "cancelled"]
    topic: str = ""
    words: int = 0
    ideas: list[str] = []
    metrics: Metrics | None = None
    beats: dict[str, TeachBackBeat] | None = None
    clarity: float | None = None
    structure: float | None = None
    clarity_reason: str = ""
    well_done: str = ""
    to_fix: str = ""
    suggestions: list[str] = []
    rewrite: TeachBackRewrite | None = None


class NotebookEvent(BaseModel):
    """The notebook new notes are filed into right now (null id: none)."""

    type: Literal["notebook"] = "notebook"
    notebook_id: uuid.UUID | None = None
    name: str = ""
    track: str = ""
    kind: str = "notes"
    note_count: int = 0
    created: bool = False


class SessionEndEvent(BaseModel):
    """The learner ended the session by voice: the client turns the microphone off."""

    type: Literal["session_end"] = "session_end"


class ModeEvent(BaseModel):
    type: Literal["mode"] = "mode"
    mode: str


class LatencyEvent(BaseModel):
    type: Literal["latency"] = "latency"
    stt_to_first_token_ms: float | None = None
    first_token_to_audio_ms: float | None = None
    stt_to_first_audio_ms: float | None = None


class AssistantDeltaEvent(BaseModel):
    type: Literal["assistant_delta"] = "assistant_delta"
    text: str


class AudioEvent(BaseModel):
    type: Literal["audio"] = "audio"
    format: Literal["pcm_s16le_16000"] = "pcm_s16le_16000"
    data: str  # base64


class AssistantDoneEvent(BaseModel):
    type: Literal["assistant_done"] = "assistant_done"


class InterruptedEvent(BaseModel):
    type: Literal["interrupted"] = "interrupted"


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


ServerEvent = (
    SessionEvent
    | TranscriptEvent
    | UtteranceEvent
    | NotesEvent
    | QuizStateEvent
    | ExplainEvent
    | ReadBackEvent
    | ConfusionEvent
    | TeachBackEvent
    | ModeEvent
    | SessionEndEvent
    | NotebookEvent
    | DiagramEvent
    | LinksEvent
    | LatencyEvent
    | AssistantDeltaEvent
    | AudioEvent
    | AssistantDoneEvent
    | InterruptedEvent
    | ErrorEvent
)
