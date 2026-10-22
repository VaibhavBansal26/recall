import asyncio

from app.voice.fake import FakeVoiceProvider


def test_fake_provider_streams_canned_audio() -> None:
    async def run() -> list[bytes]:
        return [c async for c in FakeVoiceProvider().synthesize("hello")]

    chunks = asyncio.run(run())
    assert len(chunks) == 1 and len(chunks[0]) == 3200  # 100 ms of 16 kHz s16le mono


def test_fake_provider_has_no_audio_input() -> None:
    assert FakeVoiceProvider().audio_input is False
