"""Audio resampling utilities for Exotel <-> Gemini PCM conversion.

Exotel: 8 kHz 16-bit mono PCM (base64)
Gemini input: 16 kHz 16-bit mono PCM
Gemini output: 24 kHz 16-bit mono PCM
"""
import asyncio
import audioop
import base64
from functools import partial


def b64_to_pcm(b64_str: str) -> bytes:
    return base64.b64decode(b64_str)


def pcm_to_b64(pcm_bytes: bytes) -> str:
    return base64.b64encode(pcm_bytes).decode("utf-8")


class StreamResampler:
    """Stateful resampler for one continuous PCM stream.

    audioop.ratecv() carries an internal filter state that MUST be passed
    from one call to the next for a continuous audio stream, otherwise the
    filter effectively "restarts" at every chunk boundary. That produces an
    audible click/crack at the start of every chunk — which, at typical
    streaming chunk rates (every ~20-100ms), sounds like constant
    background crackling.

    Create ONE instance per direction, per call (e.g. one for
    caller->Gemini upsampling, one for Gemini->caller downsampling), and
    reuse it for the lifetime of that call. Do not share it across calls.
    """

    def __init__(self, from_rate: int, to_rate: int, width: int = 2, channels: int = 1):
        self.from_rate = from_rate
        self.to_rate = to_rate
        self.width = width
        self.channels = channels
        self._state = None  # persists across calls to feed()

    def feed(self, pcm: bytes) -> bytes:
        if self.from_rate == self.to_rate:
            return pcm
        converted, self._state = audioop.ratecv(
            pcm, self.width, self.channels,
            self.from_rate, self.to_rate,
            self._state,
        )
        return converted

    def reset(self):
        """Call this if you ever need to hard-reset (e.g. after a long
        silence gap where continuity no longer matters)."""
        self._state = None


async def resample_stream_async(resampler: StreamResampler, pcm: bytes) -> bytes:
    """Offload a stateful resample step to a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(resampler.feed, pcm))

def resample_pcm(pcm: bytes, from_rate: int, to_rate: int) -> bytes:
    """Stateless one-shot resample. Do NOT use this in a per-chunk
    streaming loop — it resets filter state every call, causing clicks
    at chunk boundaries."""
    if from_rate == to_rate:
        return pcm
    converted, _ = audioop.ratecv(pcm, 2, 1, from_rate, to_rate, None)
    return converted