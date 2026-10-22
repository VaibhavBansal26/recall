from dataclasses import dataclass


@dataclass
class BargeInDetector:
    """Decides whether the user is talking over the assistant.

    Two signals: the client's VAD hint (instant) or a partial transcript with enough
    words in it (rules out a cough or a stray syllable).
    """

    min_words: int = 2

    def should_interrupt(
        self,
        *,
        assistant_speaking: bool,
        speech_started: bool = False,
        partial_text: str = "",
    ) -> bool:
        if not assistant_speaking:
            return False
        return speech_started or len(partial_text.split()) >= self.min_words
