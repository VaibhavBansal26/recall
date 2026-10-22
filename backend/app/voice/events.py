"""WebSocket contract for /ws/voice. Mirrored by frontend/lib/events.ts."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.agent.state import CaptureItem, DiagramItem, LinkItem
from app.db.models import Speaker

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


ClientMessage = StartEvent | TextEvent | InterruptEvent | SpeechStartEvent | EndSpeechEvent
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
    | DiagramEvent
    | LinksEvent
    | LatencyEvent
    | AssistantDeltaEvent
    | AudioEvent
    | AssistantDoneEvent
    | InterruptedEvent
    | ErrorEvent
)
