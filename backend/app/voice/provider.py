from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass


@dataclass
class SttEvent:
    text: str
    final: bool
    confidence: float | None = None


SttCallback = Callable[[SttEvent], Awaitable[None]]


class SttSession(ABC):
    """One live streaming-transcription session (16 kHz mono PCM in)."""

    @abstractmethod
    async def send_audio(self, pcm: bytes) -> None: ...

    @abstractmethod
    async def finalize(self) -> None:
        """Flush pending speech as a final transcript (push-to-talk release)."""

    @abstractmethod
    async def close(self) -> None: ...


class VoiceProvider(ABC):
    """Speech in (STT) and speech out (TTS). The words in between come from the agent."""

    name: str
    audio_input: bool

    @abstractmethod
    async def open_stt(self, *, silence_ms: int, on_event: SttCallback) -> SttSession:
        """Start streaming transcription. `silence_ms` is the endpointing threshold."""

    @abstractmethod
    def synthesize(self, sentence: str, speed: float | None = None) -> AsyncIterator[bytes]:
        """Stream PCM s16le 16 kHz mono audio for one sentence. `speed` overrides the default."""

    async def aclose(self) -> None:  # noqa: B027
        """Release network clients."""
