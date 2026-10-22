import time
from dataclasses import dataclass, field


@dataclass
class TurnLatency:
    """STT final -> first LLM token -> first audio byte. These numbers judge "not robotic"."""

    stt_final_at: float = field(default_factory=time.perf_counter)
    first_token_at: float | None = None
    first_audio_at: float | None = None

    def mark_first_token(self) -> None:
        if self.first_token_at is None:
            self.first_token_at = time.perf_counter()

    def mark_first_audio(self) -> None:
        if self.first_audio_at is None:
            self.first_audio_at = time.perf_counter()

    def _ms(self, start: float, end: float | None) -> float | None:
        return None if end is None else round((end - start) * 1000, 1)

    def stt_to_first_token_ms(self) -> float | None:
        return self._ms(self.stt_final_at, self.first_token_at)

    def first_token_to_audio_ms(self) -> float | None:
        if self.first_token_at is None:
            return None
        return self._ms(self.first_token_at, self.first_audio_at)

    def stt_to_first_audio_ms(self) -> float | None:
        return self._ms(self.stt_final_at, self.first_audio_at)
