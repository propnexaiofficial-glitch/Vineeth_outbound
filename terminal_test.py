
import argparse
import asyncio
import base64
import logging
import os
import sys
import threading
import wave
import audioop
from collections import deque
from datetime import datetime
from typing import Optional

import numpy as np
import sounddevice as sd

sys.path.insert(0, os.path.dirname(__file__))

from config import AGENT_NAME, COMPANY_NAME, GEMINI_VOICE, GEMINI_MODEL
from prompts import PromptType
from gemini_bridge import GeminiBridge

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("terminal_test")

# ── Audio constants ───────────────────────────────────────────────────────────
MIC_RATE       = 16_000
OUT_RATE       = 24_000
MIC_CHUNK_MS   = 20
MIC_FRAMES     = MIC_RATE * MIC_CHUNK_MS // 1000   # 320 frames
OUT_BLOCK_MS   = 20
OUT_FRAMES     = OUT_RATE * OUT_BLOCK_MS // 1000   # 480 frames

# ANSI colours
_CYAN   = "\033[96m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

# Recording output folder
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")


# ─────────────────────────────────────────────────────────────────────────────
# Recorder — collects mic + agent audio, saves stereo WAV on stop()
#
# Both tracks are resampled to a common 16 kHz for the final file:
#   Left  channel = your mic (already 16 kHz)
#   Right channel = agent audio (downsampled from 24 kHz → 16 kHz)
#
# A mono mix (L+R averaged) is also saved as a separate file.
# ─────────────────────────────────────────────────────────────────────────────

class Recorder:
    RECORD_RATE = 16_000   # output WAV sample rate

    def __init__(self, label: str = ""):
        self._lock       = threading.Lock()
        self._mic_buf:   list[bytes] = []   # 16k PCM chunks from mic
        self._agent_buf: list[bytes] = []   # 24k PCM chunks from agent (resampled on save)
        self._label      = label
        self._resample_state = None         # audioop ratecv state for 24k→16k

    # ── Called from audio callbacks (thread-safe) ─────────────────────────

    def add_mic(self, pcm_16k: bytes):
        with self._lock:
            self._mic_buf.append(pcm_16k)

    def add_agent(self, pcm_24k: bytes):
        """Accepts raw 24 kHz PCM from Gemini and resamples to 16 kHz inline."""
        resampled, self._resample_state = audioop.ratecv(
            pcm_24k, 2, 1, 24000, self.RECORD_RATE, self._resample_state
        )
        with self._lock:
            self._agent_buf.append(resampled)

    # ── Save on session end ───────────────────────────────────────────────

    def save(self) -> tuple[str, str]:
        """
        Writes two WAV files:
          <timestamp>_<label>_stereo.wav  — left=mic, right=agent
          <timestamp>_<label>_mono.wav    — mixed mono
        Returns (stereo_path, mono_path).
        """
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug  = self._label.replace(" ", "_").lower() if self._label else "session"
        base  = os.path.join(RECORDINGS_DIR, f"{ts}_{slug}")

        with self._lock:
            mic_pcm   = b"".join(self._mic_buf)
            agent_pcm = b"".join(self._agent_buf)

        print(f"  [rec] mic={len(mic_pcm)//2} samples  agent={len(agent_pcm)//2} samples  "
              f"({len(mic_pcm)//2//self.RECORD_RATE:.1f}s mic / "
              f"{len(agent_pcm)//2//self.RECORD_RATE:.1f}s agent)")

        if not mic_pcm and not agent_pcm:
            raise RuntimeError("No audio captured")

        # Pad shorter track with silence so both are the same length
        if len(mic_pcm) < len(agent_pcm):
            mic_pcm   = mic_pcm   + bytes(len(agent_pcm) - len(mic_pcm))
        elif len(agent_pcm) < len(mic_pcm):
            agent_pcm = agent_pcm + bytes(len(mic_pcm) - len(agent_pcm))

        n_frames  = len(mic_pcm) // 2
        mic_arr   = np.frombuffer(mic_pcm,   dtype=np.int16).astype(np.float32)
        agent_arr = np.frombuffer(agent_pcm, dtype=np.int16).astype(np.float32)

        # Normalise each track independently so both are audible regardless
        # of mic gain — mic is often much quieter than the agent output
        def _normalise(arr: np.ndarray, headroom: float = 0.9) -> np.ndarray:
            peak = np.abs(arr).max()
            if peak > 0:
                arr = arr * (headroom * 32767 / peak)
            return arr.clip(-32768, 32767).astype(np.int16)

        mic_norm   = _normalise(mic_arr)
        agent_norm = _normalise(agent_arr)

        # ── Stereo WAV (interleaved L R L R …) ───────────────────────────
        stereo = np.empty(n_frames * 2, dtype=np.int16)
        stereo[0::2] = mic_norm    # left  = mic (you)
        stereo[1::2] = agent_norm  # right = agent
        stereo_path = base + "_stereo.wav"
        with wave.open(stereo_path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(self.RECORD_RATE)
            wf.writeframes(stereo.tobytes())

        # ── Mono mix — both tracks at equal volume ────────────────────────
        mono = ((mic_norm.astype(np.int32) + agent_norm.astype(np.int32)) // 2).astype(np.int16)
        mono_path = base + "_mono.wav"
        with wave.open(mono_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.RECORD_RATE)
            wf.writeframes(mono.tobytes())

        return stereo_path, mono_path


# ─────────────────────────────────────────────────────────────────────────────
# TerminalBridge — intercepts raw 24 kHz audio before the bridge downsamples
# ─────────────────────────────────────────────────────────────────────────────

class TerminalBridge(GeminiBridge):
    """
    Overrides _receive_loop to:
      1. Push raw 24 kHz PCM into raw_24k_deque (for the speaker stream)
      2. Set muted_event instantly on barge-in so audio callback stops within 20 ms
      3. Still handle transcripts and hangup detection exactly as the parent
    Also exposes send_audio_16k so we skip the 8k→16k upsample.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.raw_24k_deque: deque[bytes] = deque()
        # Threading event — checked by audio callback every 20 ms block
        self.muted_event = threading.Event()
        # Recorder — injected by run_session after construction
        self.recorder: Optional[Recorder] = None

    async def send_audio_16k(self, pcm_16k: bytes):
        if not self._active or not self._session:
            return
        from google import genai
        await self._session.send_realtime_input(
            audio=genai.types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
        )

    async def _receive_loop(self):
        """
        Identical to parent but pushes raw 24 kHz PCM into raw_24k_deque
        instead of downsampling to 8 kHz for Exotel.
        On barge-in: sets muted_event instantly so audio callback stops within 20 ms.
        """
        from google import genai as _genai

        try:
            while self._active:
                turn = self._session.receive()
                async for response in turn:
                    if not self._active:
                        break

                    # ── Barge-in ──────────────────────────────────────────────
                    if getattr(response, "server_content", None):
                        if getattr(response.server_content, "interrupted", False):
                            # INSTANT mute — audio callback sees this within 20 ms
                            self.muted_event.set()
                            self.raw_24k_deque.clear()
                            while not self.output_queue.empty():
                                self.output_queue.get_nowait()
                            logger.info(f"[{self.call_sid}] Barge-in — muted")
                            continue

                    # ── Raw 24 kHz audio → deque for speaker ─────────────────
                    if response.data:
                        # Unmute when new audio arrives (Gemini is speaking again)
                        if self.muted_event.is_set():
                            self.muted_event.clear()
                        raw = response.data
                        if isinstance(raw, str):
                            raw = base64.b64decode(raw)
                        raw_bytes = bytes(raw)
                        self.raw_24k_deque.append(raw_bytes)
                        # Feed recorder (resamples 24k→16k internally)
                        if self.recorder:
                            self.recorder.add_agent(raw_bytes)

                    # ── Transcripts + hangup (unchanged from parent) ──────────
                    if response.text:
                        text = response.text
                        logger.info(f"[{self.call_sid}] Agent: {text}")
                        import config as _cfg
                        self.transcript_parts.append(f"{_cfg.AGENT_NAME}: {text}")
                        if "[[HANGUP]]" in text:
                            self.on_hangup.set()

                    if getattr(response, "server_content", None):
                        sc = response.server_content
                        if getattr(sc, "output_transcription", None):
                            t = sc.output_transcription.text or ""
                            if t.strip():
                                import config as _cfg
                                if self.transcript_parts and self.transcript_parts[-1].startswith(_cfg.AGENT_NAME):
                                    self.transcript_parts[-1] += t
                                else:
                                    self.transcript_parts.append(f"{_cfg.AGENT_NAME}:{t}")
                                if "[[HANGUP]]" in t:
                                    self.on_hangup.set()
                                closing = ["dhanyawad","shukriya","aapka din achha rahe",
                                           "thank you","goodbye","bye","alvida"]
                                if any(p in t.lower() for p in closing):
                                    async def _delayed():
                                        await asyncio.sleep(3)
                                        if not self.on_hangup.is_set():
                                            self.on_hangup.set()
                                    asyncio.create_task(_delayed())
                        if getattr(sc, "input_transcription", None):
                            t = sc.input_transcription.text or ""
                            if t.strip():
                                if self.transcript_parts and self.transcript_parts[-1].startswith("Customer:"):
                                    self.transcript_parts[-1] += t
                                else:
                                    self.transcript_parts.append(f"Customer:{t}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.call_sid}] receive error: {e}", exc_info=True)
        finally:
            try:
                self.output_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Continuous output stream — sounddevice callback drains raw_24k_deque
# ─────────────────────────────────────────────────────────────────────────────

def make_output_callback(bridge: TerminalBridge):
    """
    Returns a sounddevice OutputStream callback.
    Checks bridge.muted_event on every 20 ms block — if set, outputs silence
    immediately so barge-in stops playback within one block (<20 ms).
    Uses a leftover buffer so partial chunks carry over between callbacks.
    """
    leftover = bytearray()

    def callback(outdata: np.ndarray, frames: int, time_info, status):
        nonlocal leftover
        needed = frames * 2  # 16-bit mono → 2 bytes per frame

        # Barge-in: output silence instantly, discard leftover
        if bridge.muted_event.is_set():
            leftover.clear()
            outdata[:] = 0
            return

        # Pull from deque until we have enough bytes
        while len(leftover) < needed and bridge.raw_24k_deque:
            leftover.extend(bridge.raw_24k_deque.popleft())

        if len(leftover) >= needed:
            chunk = bytes(leftover[:needed])
            del leftover[:needed]
        else:
            chunk = bytes(leftover) + bytes(needed - len(leftover))
            leftover.clear()

        arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        outdata[:, 0] = arr

    return callback


# ─────────────────────────────────────────────────────────────────────────────
# Mic capture — sounddevice InputStream callback → asyncio queue
# ─────────────────────────────────────────────────────────────────────────────

def make_mic_callback(mic_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop,
                      stop_flag: list, recorder: Optional["Recorder"] = None):
    def callback(indata, frames, time_info, status):
        if stop_flag[0]:
            raise sd.CallbackStop()
        pcm = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        if recorder:
            recorder.add_mic(pcm)
        asyncio.run_coroutine_threadsafe(mic_queue.put(pcm), loop)
    return callback


# ─────────────────────────────────────────────────────────────────────────────
# Transcript watcher
# ─────────────────────────────────────────────────────────────────────────────

async def transcript_watcher(bridge: TerminalBridge, stop_event: asyncio.Event):
    import config as _cfg
    last_len = 0
    while not stop_event.is_set():
        current = bridge.transcript_parts
        if len(current) > last_len:
            for part in current[last_len:]:
                if part.startswith(_cfg.AGENT_NAME):
                    text = part.split(":", 1)[-1].strip()
                    print(f"\n{_CYAN}{_BOLD}🤖 {_cfg.AGENT_NAME}:{_RESET} {_CYAN}{text}{_RESET}", flush=True)
                elif part.startswith("Customer:"):
                    text = part.split(":", 1)[-1].strip()
                    print(f"\n{_GREEN}{_BOLD}🎤 You:{_RESET}  {_GREEN}{text}{_RESET}", flush=True)
            last_len = len(current)
        await asyncio.sleep(0.1)


# ─────────────────────────────────────────────────────────────────────────────
# Main session
# ─────────────────────────────────────────────────────────────────────────────

async def run_session(prompt_type: PromptType, lead_name: str, send_greeting: bool,
                      custom_prompt_fn=None, custom_greeting: str = None, record: bool = True):
    from config import GEMINI_VOICE as _voice, GEMINI_SPEAKING_RATE as _rate, AGENT_NAME as _agent, COMPANY_NAME as _company
    print(f"\n{_BOLD}{'─'*60}{_RESET}")
    print(f"{_BOLD}  Voice Agent Terminal Tester{_RESET}")
    print(f"  Agent : {_CYAN}{_agent}{_RESET} ({_company})")
    print(f"  Model : {GEMINI_MODEL}")
    print(f"  Voice : {_CYAN}{_voice}{_RESET}  |  Rate: {_YELLOW}{_rate}×{_RESET}")
    print(f"  Mode  : {_YELLOW}{prompt_type}{_RESET}  |  Lead: {lead_name}")
    if record:
        print(f"  Rec   : {_YELLOW}ON{_RESET} → recordings/")
    print(f"{_BOLD}{'─'*60}{_RESET}")
    print(f"  {_YELLOW}Speak into your mic.  Press Ctrl+C to end.{_RESET}\n")

    bridge = TerminalBridge(
        call_sid="terminal-test",
        prompt_type=prompt_type,
    )

    # Inject custom prompt builder if a client override is active
    if custom_prompt_fn is not None:
        import gemini_bridge as _gb_mod

        # Set the greeting directly on the bridge
        if custom_greeting and send_greeting:
            bridge.outbound_intro = custom_greeting.replace("[lead_name]", lead_name)

        original_start = bridge.start
        async def patched_start(send_greeting=True):
            # Patch build_system_prompt in gemini_bridge's own namespace —
            # this is where GeminiBridge.start() actually calls it from
            _orig = _gb_mod.build_system_prompt
            _gb_mod.build_system_prompt = custom_prompt_fn
            try:
                await original_start(send_greeting=send_greeting)
            finally:
                _gb_mod.build_system_prompt = _orig
        bridge.start = patched_start

    stop_event = asyncio.Event()
    mic_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=50)
    stop_flag = [False]
    loop = asyncio.get_event_loop()

    # ── Recorder ──────────────────────────────────────────────────────────────
    recorder = Recorder(label=f"{lead_name}_{prompt_type}") if record else None
    bridge.recorder = recorder

    # ── Start Gemini session ──────────────────────────────────────────────────
    await bridge.start(send_greeting=send_greeting)
    print(f"  {_GREEN}✓ Gemini session open — listening...{_RESET}\n")

    # ── Open continuous output stream ─────────────────────────────────────────
    out_stream = sd.OutputStream(
        samplerate=OUT_RATE,
        channels=1,
        dtype="float32",
        blocksize=OUT_FRAMES,
        callback=make_output_callback(bridge),
    )
    out_stream.start()

    # ── Open mic input stream ─────────────────────────────────────────────────
    in_stream = sd.InputStream(
        samplerate=MIC_RATE,
        channels=1,
        dtype="float32",
        blocksize=MIC_FRAMES,
        callback=make_mic_callback(mic_queue, loop, stop_flag, recorder),
    )
    in_stream.start()

    # ── Transcript watcher task ───────────────────────────────────────────────
    transcript_task = asyncio.create_task(transcript_watcher(bridge, stop_event))

    # ── Mic sender task ───────────────────────────────────────────────────────
    async def mic_sender():
        while not stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(mic_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if chunk is None:
                break
            await bridge.send_audio_16k(chunk)

    mic_task = asyncio.create_task(mic_sender())

    # ── Wait for Ctrl+C or agent hangup ──────────────────────────────────────
    try:
        while not stop_event.is_set():
            if bridge.on_hangup and bridge.on_hangup.is_set():
                print(f"\n  {_YELLOW}[Agent ended the call]{_RESET}")
                await asyncio.sleep(1.5)   # let last audio drain
                break
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        pass

    # ── Teardown ──────────────────────────────────────────────────────────────
    stop_flag[0] = True
    stop_event.set()

    in_stream.stop()
    in_stream.close()

    # Let any queued audio finish playing (up to 1 s)
    drain_deadline = asyncio.get_event_loop().time() + 1.0
    while bridge.raw_24k_deque and asyncio.get_event_loop().time() < drain_deadline:
        await asyncio.sleep(0.05)

    out_stream.stop()
    out_stream.close()

    mic_task.cancel()
    transcript_task.cancel()
    await asyncio.gather(mic_task, transcript_task, return_exceptions=True)

    await bridge.stop()

    # ── Save recording ────────────────────────────────────────────────────────
    if recorder:
        print(f"\n  Saving recording...", end=" ", flush=True)
        try:
            stereo_path, mono_path = recorder.save()
            print(f"{_GREEN}done{_RESET}")
            print(f"  {_CYAN}Stereo{_RESET} (L=you, R=agent) : {stereo_path}")
            print(f"  {_CYAN}Mono{_RESET}   (mixed)          : {mono_path}")
        except Exception as e:
            print(f"{_YELLOW}failed — {e}{_RESET}")

    # ── Full transcript ───────────────────────────────────────────────────────
    import config as _cfg
    print(f"\n{_BOLD}{'─'*60}{_RESET}")
    print(f"{_BOLD}  Full Transcript{_RESET}")
    print(f"{_BOLD}{'─'*60}{_RESET}")
    if bridge.transcript_parts:
        for part in bridge.transcript_parts:
            if part.startswith(_cfg.AGENT_NAME):
                text = part.split(":", 1)[-1].strip()
                print(f"{_CYAN}{_cfg.AGENT_NAME}   :{_RESET} {text}")
            else:
                text = part.split(":", 1)[-1].strip()
                print(f"{_GREEN}You    :{_RESET} {text}")
    else:
        print("  (no transcript captured)")
    print(f"{_BOLD}{'─'*60}{_RESET}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

AVAILABLE_VOICES = [
    "Zephyr","Aoede","Leda","Callirrhoe","Achernar","Autonoe","Despina",
    "Erinome","Gacrux","Kore","Laomedeia","Pulcherrima","Sulafat","Vindemiatrix",
    "Puck","Charon","Fenrir","Orus","Umbriel","Enceladus","Algieba","Algenib",
    "Schedar","Achird","Sadachbia","Iapetus","Rasalgethi","Alnilam","Sadaltager","Zubenelgenubi",
]

# ─────────────────────────────────────────────────────────────────────────────
# CLIENT OVERRIDES — temporary per-client configs for testing
# Add a new dict here to test a different company without touching prompts.py
# ─────────────────────────────────────────────────────────────────────────────

_CLIENT_CONFIGS: dict[str, dict] = {

    "pinpro": {
        "agent_name":   "Anaya",
        "company_name": "Ayurveda wellness",
        "voice":        "Aoede",
        "rate":         0.92,
        # Custom greeting sent to Gemini to kick off the call
        "greeting": "Hi! I'm Anaya calling on behalf of PINPRO. Am I talking to Mr. Baba?",
        # Full business context injected into the prompt
        "business_context": """
## PINPRO ke baare mein
- Company: PINPRO PMS (Property Management Services)
- Founder: P. Baba | Website: www.pinpropms.com
- Headquarters: Bengaluru | Also operates in Goa and Mumbai
- Experience: 15+ saal real estate industry mein
- Model: ZERO brokerage property advisory — broker sirf advertising ke liye
- Specialisation: North & East Bangalore property experts

## Hum kya deal karte hain
- Residential: Apartments, Villas, Row Houses, Plots, Farm Plots
- Commercial: Investment properties, commercial spaces
- Primary sales focus: 'A', 'B' aur 'C' category builders & developers ke saath direct tie-ups

## Humara edge — yeh sirf hum de sakte hain
- Builders ke saath exclusive inside information — best price aur deals jo market mein available nahi hote
- End-to-end property services — search se registration tak sab hum handle karte hain
- Site visit ke liye cab facility — customer ko khud arrange nahi karna
- Extensive builder network aur internal contacts — best deals sirf hamare paas

## Hum kiske liye kaam karte hain
IT/BT professionals, CEOs, CFOs, corporate management, first-time home buyers,
investors, HNIs, NRIs, SMEs, startups, NGOs, working professionals, business owners,
manufacturers — jo bhi invest karna chahte hain ya end-use ke liye property lena chahte hain

## Key selling points
- Zero brokerage model — customer ko extra charge nahi
- Exclusive builder deals jo publicly available nahi hain
- Cab facility for site visits — hamare saath aao, hum arrange karte hain
- 15 saal ka experience — market ki poori samajh
- Bangalore mein North & East area ke specialists
- Pan-city coverage: Bangalore (primary), Goa, Mumbai
""",
        # Override the call structure for real estate
        "call_structure_override": """
## Call flow — Real Estate Advisory

1. GREETING — confirm you're speaking to the right person
   Say exactly: "Hi! I'm Priya calling on behalf of PINPRO. Am I talking to Mr./Ms. [lead_name]?"
   Once confirmed: "Great! PINPRO is a property advisory based in Bangalore — we help people find the right property. Do you have 2 minutes?"

2. HOOK — open-ended question
   "Are you looking at any property right now — residential or commercial?"
   or "Are you exploring options in Bangalore?"

3. QUALIFY — one question at a time, naturally
   - What are they looking for? (apartment / villa / plot / farm plot / commercial)
   - Which area? (North/East Bangalore, Goa, Mumbai)
   - Budget range?
   - End-use or investment?
   - Timeline?
   - Have they spoken to any builder or broker already?

4. PITCH — personalise to their interest
   - "We work on zero brokerage — no extra cost to you at all."
   - "We have exclusive deals with builders that aren't available in the open market — 15 years of network."
   - "We arrange cab for site visits — you don't have to worry about anything."
   - "We specialise in North and East Bangalore — I can personally show you the best options."

5. OBJECTIONS
   - "Already talking to a broker" → "Absolutely! We're not brokers — we're zero-brokerage advisors. And we have exclusive deals brokers don't have access to. Worth a quick comparison."
   - "Just exploring" → "Perfect timing! There are some really good deals in the market right now. Let me shortlist a few options for you — no commitment at all."
   - "Budget is tight" → "No problem at all — we work across A, B, and C category builders. Tell me your rough budget and I'll find the best fit."
   - "Not based in Bangalore" → "We work with NRIs and outstation clients all the time — we handle everything end-to-end, you don't need to be here personally."

6. CTA — one clear next step
   - Schedule a site visit (we arrange the cab)
   - Send property options on WhatsApp
   - Schedule a callback

7. CLOSE
   "It was great talking to you, [lead_name]! [Confirm next step]. Thank you for your time — you can also check us out at www.pinpropms.com."

## Outcome tracking
INTERESTED, SITE_VISIT_BOOKED, CALLBACK_REQUESTED, NOT_NOW, NOT_INTERESTED, WHATSAPP_SENT
""",
    },

}


def _apply_client_override(client_key: str):
    """
    Hot-patches config module and returns a custom build_system_prompt function
    for the given client. Returns None if client_key not found.
    """
    cfg = _CLIENT_CONFIGS.get(client_key.lower())
    if not cfg:
        return None, None

    import config as _cfg
    _cfg.AGENT_NAME   = cfg["agent_name"]
    _cfg.COMPANY_NAME = cfg["company_name"]
    os.environ["AGENT_NAME"]   = cfg["agent_name"]
    os.environ["COMPANY_NAME"] = cfg["company_name"]

    if cfg.get("voice"):
        _cfg.GEMINI_VOICE = cfg["voice"]
        os.environ["GEMINI_VOICE"] = cfg["voice"]
    if cfg.get("rate"):
        _cfg.GEMINI_SPEAKING_RATE = cfg["rate"]
        os.environ["GEMINI_SPEAKING_RATE"] = str(cfg["rate"])

    # Build a custom prompt function that injects the client's business context
    business_ctx   = cfg.get("business_context", "")
    call_structure = cfg.get("call_structure_override")
    agent_name     = cfg["agent_name"]
    company_name   = cfg["company_name"]
    greeting_line  = cfg.get("greeting")

    def custom_build_prompt(
        prompt_type="sales",
        lead_name="there",
        lead_company="",
        call_context="",
        collected_info=None,
    ) -> str:
        from prompts import _get_prompt_components, _build_info_section
        personality, default_structure, hard_rules = _get_prompt_components(prompt_type)

        structure   = call_structure if call_structure else default_structure
        company_ctx = f" ({lead_company})" if lead_company else ""
        ctx_note    = f"\n\nCall context: {call_context}" if call_context else ""
        info_section = ""
        if prompt_type in ("sales", "followup", "callback", "objection"):
            info_section = _build_info_section(collected_info)

        return f"""RESPOND PRIMARILY IN ENGLISH. Use a natural Indian English accent — warm, confident, conversational. Light Hindi words like "ji", "bilkul", "achha" are fine occasionally, but keep it mostly English throughout.

You are {agent_name}, a property advisor at {company_name}.
You are speaking with {lead_name}{company_ctx}.{ctx_note}
Always use "you" and "your" — polite and professional.

## Numbers & figures — ALWAYS say as digits, never in words
- Say "3 crores" not "teen crores", "50 lakhs" not "pachaas lakhs"
- Say "15 years" not "pandrah saal"
- Say "2 minutes" not "do minute"
- Say "North Bangalore" not "North Bengaluru" unless customer uses that
- Always use numerals when mentioning any price, budget, area, or time

## Call Type: {prompt_type.upper()}
{business_ctx}
{personality}
{structure}
{hard_rules}
{info_section}""".replace("GrabYourCar", company_name).replace("Anaya", agent_name).replace("grabyourcar.com", "pinpropms.com").replace("Anshdeep sir", "Mr. Baba").replace("Anshdeep@", "info@")

    return cfg, custom_build_prompt, greeting_line

def main():
    parser = argparse.ArgumentParser(description="Terminal speech-to-speech tester")
    parser.add_argument("--prompt", "-p", default="sales",
        choices=["sales","feedback","insurance_only","followup","objection","callback"])
    parser.add_argument("--name", "-n", default="Test User")
    parser.add_argument("--no-greeting", action="store_true")
    parser.add_argument("--voice", "-v", default=None,
        help=f"Override voice for this session. Available: {', '.join(AVAILABLE_VOICES)}")
    parser.add_argument("--rate", "-r", default=None, type=float,
        help="Speaking rate override (0.5 = slow/soft, 1.0 = normal, 1.5 = fast)")
    parser.add_argument("--client", "-c", default=None,
        help=f"Use a client-specific config. Available: {', '.join(_CLIENT_CONFIGS.keys())}")
    parser.add_argument("--no-record", action="store_true",
        help="Disable recording (recording is ON by default)")
    args = parser.parse_args()

    # Apply client override first (sets voice/rate/names)
    custom_prompt_fn = None
    custom_greeting  = None
    if args.client:
        result = _apply_client_override(args.client)
        if result[0] is None:
            print(f"\n  {_YELLOW}Unknown client '{args.client}'. Available: {', '.join(_CLIENT_CONFIGS.keys())}{_RESET}\n")
            return
        cfg, custom_prompt_fn, custom_greeting = result
        print(f"\n  {_GREEN}✓ Client override: {args.client.upper()}{_RESET}")

    # CLI voice/rate override takes priority over client defaults
    if args.voice:
        v = args.voice.strip().capitalize()
        if v not in AVAILABLE_VOICES:
            print(f"\n  {_YELLOW}Unknown voice '{v}'. Available voices:{_RESET}")
            for i, name in enumerate(AVAILABLE_VOICES):
                print(f"    {name}", end="\n" if (i+1) % 5 == 0 else "  ")
            print()
            return
        os.environ["GEMINI_VOICE"] = v
        import config as _cfg
        _cfg.GEMINI_VOICE = v

    if args.rate is not None:
        os.environ["GEMINI_SPEAKING_RATE"] = str(args.rate)
        import config as _cfg
        _cfg.GEMINI_SPEAKING_RATE = args.rate

    try:
        asyncio.run(run_session(
            prompt_type=args.prompt,
            lead_name=args.name,
            send_greeting=not args.no_greeting,
            custom_prompt_fn=custom_prompt_fn,
            custom_greeting=custom_greeting,
            record=not args.no_record,
        ))
    except KeyboardInterrupt:
        print(f"\n  {_YELLOW}Session ended by user.{_RESET}\n")


if __name__ == "__main__":
    main()
