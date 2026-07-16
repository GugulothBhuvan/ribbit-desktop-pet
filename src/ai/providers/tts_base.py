"""Shared contract for text-to-speech providers.

Providers return an AudioClip carrying its OWN format rather than assuming a
fixed sample rate: Deepgram Aura hands back raw linear16 @ 24 kHz, while Sarvam
returns a base64 WAV whose rate is configurable. The player reads the format off
the clip, so adding a provider never touches playback code.

An empty clip (EMPTY_CLIP) means "synthesis failed / nothing to say" — callers
skip playback. TTS is never allowed to break a reply.
"""
from typing import NamedTuple


class AudioClip(NamedTuple):
    pcm: bytes          # raw PCM frames (no container/header)
    sample_rate: int
    channels: int
    sample_width: int   # bytes per sample (2 = int16)

    def __bool__(self) -> bool:
        return bool(self.pcm)


EMPTY_CLIP = AudioClip(b"", 0, 0, 0)
