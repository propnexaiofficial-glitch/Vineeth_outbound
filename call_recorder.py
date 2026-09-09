"""
CallRecorder -- records a two-party phone call (caller + AI agent) into a
single stereo WAV file, with the two channels kept in sync using wall-clock
timestamps (not just "append whatever arrives whenever").

Left channel  (channel 0) = caller audio
Right channel (channel 1) = agent/AI audio

Usage:
    recorder = CallRecorder(call_sid="abc123", sample_rate=8000)

    # whenever you get caller audio (8kHz, 16-bit PCM, mono):
    await recorder.add_caller_audio(pcm_bytes)

    # whenever you get agent audio (same format):
    await recorder.add_agent_audio(pcm_bytes)

    # when call ends:
    path = recorder.save()   # writes WAV to disk, returns local file path

--------------------------------------------------------------------------
FIX NOTES #1 (why real-phone-call recordings were crackling, but browser/
local testing sounded fine):

_pad_to_elapsed() used to insert silence bytes EVERY time a chunk arrived
even a few milliseconds later than the previous one relative to wall clock.
On a real telephony leg (SIP/PSTN), chunk arrival has natural jitter from
network latency + asyncio scheduling + shared lock contention between the
caller/agent writers. Every one of those tiny delays was being misread as
"the caller went silent" and got a zero-byte gap punched into the middle of
otherwise continuous speech. Each such gap is an abrupt 0 -> non-zero
transition in the waveform, which is exactly what produces an audible
click/crackle. Do this dozens of times during a call and it sounds like
constant crackling. Local/browser testing has much lower, more consistent
latency, so the same code rarely (or never) triggered padding there --
which is why it "worked" for internal testing but broke on real calls.

Fix: only pad when the gap between expected and actual buffered audio
exceeds a jitter tolerance (default 80ms) -- i.e. only insert silence when
a party has genuinely gone quiet, not for ordinary network/processing
jitter between consecutive chunks of continuous speech. Also split the
single shared lock into per-channel locks so a slow write on one channel
can't delay (and falsely "silence-pad") the other.

--------------------------------------------------------------------------
FIX NOTES #2 (why the caller's voice sounded like it was "missing" /
getting overlapped/masked by the agent's voice on playback):

Even with the two parties recorded on separate channels, telephony audio
coming from the caller's PSTN/SIP leg is naturally much quieter than the
agent's TTS output (which is normalized/loud by default). When this stereo
file gets played back or downmixed to mono (many browsers, dashboards, and
MP3 exporters do this silently), the loud agent channel drowns out the
quieter caller channel -- so the caller sounds "missing" even though the
audio is technically present in the recording.

A flat/fixed gain multiplier is a blunt fix for this: if set high enough
to make quiet speech audible, it clips (and audibly distorts/"breaks") any
chunk where the caller happened to speak louder. If set low enough to
never clip, quiet speech stays too quiet.

Fix: apply RMS-based dynamic normalization per chunk instead. Each
incoming caller chunk's loudness (RMS) is measured, and the gain applied
to THAT chunk is scaled to bring it toward a target loudness -- with an
upper cap on the gain so near-silence isn't amplified into a loud hiss,
and clipping protection so no sample ever overflows/distorts. Net effect:
quiet speech gets boosted more, already-loud speech gets boosted less (or
not at all), so both parties end up at a comparable, consistently clear
volume without introducing crackle/breaks.
--------------------------------------------------------------------------
"""

import asyncio
import os
import re
import time
import wave
from array import array
from typing import Optional


def _safe_filename(name: str) -> str:
    """Windows (and some other filesystems) forbid characters like : \\ / * ? " < > |
    in filenames. Telephony/OBD panels often generate call_ids containing a
    timestamp with colons (e.g. '622872_9811104030_17:31:03'), which would
    otherwise crash the local file write. This only affects the LOCAL disk
    filename -- the original call_sid is still used unchanged as the MongoDB
    lookup key, so matching against the OBD panel's own report still works."""
    return re.sub(r'[<>:"/\\|?*]', "_", name)

_PAD_JITTER_TOLERANCE_MS = 80

_TARGET_RMS = 4000          # desired average loudness (16-bit PCM scale, max 32767)
_MAX_CALLER_GAIN = 3.0      # never boost a chunk more than this, even if very quiet
_MIN_RMS_TO_BOOST = 50      # below this RMS, treat chunk as silence/noise -- don't boost


class CallRecorder:
    def __init__(
        self,
        call_sid: str,
        sample_rate: int = 8000,
        output_dir: str = "recordings",
        target_rms: int = _TARGET_RMS,
        max_caller_gain: float = _MAX_CALLER_GAIN,
    ):
        self.call_sid = call_sid
        self.sample_rate = sample_rate
        self.output_dir = output_dir
        self.target_rms = target_rms
        self.max_caller_gain = max_caller_gain

        os.makedirs(self.output_dir, exist_ok=True)
        self._start_time = time.monotonic()

        self._caller_buf = bytearray()
        self._agent_buf = bytearray()
        self._caller_lock = asyncio.Lock()
        self._agent_lock = asyncio.Lock()

        self._tolerance_bytes = int((_PAD_JITTER_TOLERANCE_MS / 1000) * self.sample_rate) * 2

        self._saved_path: Optional[str] = None

    async def add_caller_audio(self, pcm_16bit_mono: bytes):
        """Call this with each chunk of caller (inbound) audio, same
        format/sample-rate you're already feeding into bridge.send_audio().
        RMS-based dynamic gain is applied here so the caller's volume stays
        comparable to the agent's on playback, without clipping/distorting
        already-loud speech (see FIX NOTES #2 above)."""
        async with self._caller_lock:
            boosted = self._normalize_chunk(pcm_16bit_mono)
            self._pad_to_elapsed(self._caller_buf)
            self._caller_buf.extend(boosted)

    async def add_agent_audio(self, pcm_16bit_mono: bytes):
        """Call this with each chunk of agent (outbound/Gemini) audio,
        same format/sample-rate as what you send to the caller (8kHz here,
        after your existing downsample_24k_to_8k step)."""
        async with self._agent_lock:
            self._pad_to_elapsed(self._agent_buf)
            self._agent_buf.extend(pcm_16bit_mono)

    def _normalize_chunk(self, pcm_bytes: bytes) -> bytes:
        """RMS-based dynamic normalization for a single caller chunk.

        1. Measure this chunk's RMS (average loudness).
        2. If it's near-silence/background noise (RMS below
           _MIN_RMS_TO_BOOST), leave it alone -- boosting noise/silence
           just raises the hiss floor, it doesn't make speech clearer.
        3. Otherwise compute the gain needed to bring this chunk's RMS up
           to target_rms, capped at max_caller_gain so we never amplify a
           very quiet chunk into an unnaturally loud/noisy one.
        4. Apply that gain with clipping protection (clamp to 16-bit
           range) so loud syllables within the chunk never overflow/wrap,
           which is what causes audible distortion/"breaking"."""
        samples = array("h")
        samples.frombytes(pcm_bytes)
        if len(samples) == 0:
            return pcm_bytes
        sum_sq = sum(s * s for s in samples)
        rms = (sum_sq / len(samples)) ** 0.5

        if rms < _MIN_RMS_TO_BOOST:
            return pcm_bytes  

        gain = self.target_rms / rms
        gain = min(gain, self.max_caller_gain)
        gain = max(gain, 1.0)  

        if gain == 1.0:
            return pcm_bytes

        for i in range(len(samples)):
            boosted = int(samples[i] * gain)
            samples[i] = max(-32768, min(32767, boosted))
        return samples.tobytes()

    def _pad_to_elapsed(self, buf: bytearray):
        """Pad a channel buffer with silence up to 'now', so that a chunk
        arriving late (because that party wasn't speaking) lands at the
        correct offset instead of right after the previous chunk.

        ✅ FIX: only pad if the gap exceeds a jitter tolerance. Without this,
        ordinary network/asyncio scheduling jitter between consecutive
        chunks of continuous speech (a few ms, very common on a real
        telephony leg) was being treated as "the caller went silent" and
        a small silence gap got punched into the middle of live speech --
        that's what was causing the crackling sound on real phone calls.
        """
        elapsed = time.monotonic() - self._start_time
        target_bytes = int(elapsed * self.sample_rate) * 2  # 16-bit = 2 bytes/sample
        gap = target_bytes - len(buf)
        if gap > self._tolerance_bytes:
            buf.extend(b"\x00" * gap)

    # Finalize

    def save(self) -> str:
        """Write the recording to a stereo WAV file and return its path.
        Safe to call once, at call end (e.g. from _cleanup())."""

       
        max_len = max(len(self._caller_buf), len(self._agent_buf))
        if len(self._caller_buf) < max_len:
            self._caller_buf.extend(b"\x00" * (max_len - len(self._caller_buf)))
        if len(self._agent_buf) < max_len:
            self._agent_buf.extend(b"\x00" * (max_len - len(self._agent_buf)))

        caller_samples = array("h")
        caller_samples.frombytes(bytes(self._caller_buf))

        agent_samples = array("h")
        agent_samples.frombytes(bytes(self._agent_buf))
        interleaved = array("h", [0]) * (len(caller_samples) * 2)
        interleaved[0::2] = caller_samples
        interleaved[1::2] = agent_samples

        path = os.path.join(self.output_dir, f"{_safe_filename(self.call_sid)}.wav")

        with wave.open(path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(interleaved.tobytes())

        self._saved_path = path
        return path

    @property
    def saved_path(self) -> Optional[str]:
        return self._saved_path