import asyncio
import base64
import json
import logging
import math
import struct
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from gemini_bridge import GeminiBridge
from call_recorder import CallRecorder
import schoolknot_api

logger = logging.getLogger(__name__)

_SILENCE_TIMEOUT_SECONDS = 15
_SILENCE_CHECK_INTERVAL_SECONDS = 2

# Bonvoice "Inbound Media Streams v3" spec: audio is ALWAYS raw PCM,
# 16-bit signed, 8000 Hz, mono — both directions — in exact 320-byte
# (20ms) frames. No a-law / mu-law / linear8 negotiation exists on this
# vendor; anything sent that isn't PCM16 or isn't a multiple of 320
# bytes "will fail" per their doc, so we no longer do any audio-format
# conversion here at all.
_CALL_SAMPLE_RATE = 8000
_BONVOICE_CHUNK_BYTES = 320          # 320 bytes = 160 samples = 20ms @ 8kHz/16-bit/mono
_TRANSFER_STAFF_NUMBER = "9550335589"

_RECORDINGS_DIR = r"D:\SchoolKnot\SchoolKnot Inbound\Addmission Gemini\Salezx-Voice-agent-main\voice_agent\recordings"
_CLEAR_EVENT_NAME = "clear"
_PCM_8K_BYTES_PER_MS = 16.0          # 8000 samples/s * 2 bytes / 1000 ms

_PACING_LOOKAHEAD_MS = 200
_TRANSFER_GRACE_PERIOD_SECONDS = 3.0
_HANGUP_WATCHDOG_GRACE_SECONDS = 8.0

_RINGBACK_FREQ_1_HZ = 440.0
_RINGBACK_FREQ_2_HZ = 480.0
_RINGBACK_ON_MS = 2000
_RINGBACK_OFF_MS = 4000
_RINGBACK_AMPLITUDE = 0.25          # 0.0-1.0, keep modest so it isn't jarring
_RINGBACK_CHUNK_MS = 20             # 20ms @ 8kHz/16-bit/mono == exactly 320 bytes,
                                     # matching Bonvoice's required frame size


def _normalize_datetime(raw: Optional[str], call_id: str = "") -> str:

    if not raw:
        return ""
    try:
        from dateutil import parser as dtparser
        dt = dtparser.parse(raw, fuzzy=True, default=datetime.now())
        normalized = dt.strftime("%Y-%m-%d %H:%M:%S")
        if normalized != raw:
            logger.info(
                f"[{call_id}] Normalized date {raw!r} -> {normalized!r} "
                f"before sending to SchoolKnot."
            )
        return normalized
    except Exception as e:
        logger.warning(
            f"[{call_id}] Could not parse date {raw!r} ({e}) — sending "
            f"empty string instead of an unparseable value."
        )
        return ""


class WsCallHandler:
    def __init__(
        self,
        websocket: WebSocket,
        on_call_end=None,
        lead_id: str = "",
        initial_info=None,
        prompt_type: str = "sales",
        lead_name: str = "there",
        lead_company: str = "",
        call_context: str = "",
        is_outbound: bool = False,
        outbound_intro: Optional[str] = None,
    ):
        self.ws                = websocket
        self.call_id            = f"unknown-{uuid.uuid4().hex[:12]}"
        self.bridge: Optional[GeminiBridge] = None
        self.recorder: Optional[CallRecorder] = None
        self._sender_task        = None
        self._silence_watcher_task = None
        self._on_call_end        = on_call_end
        self._lead_id            = lead_id
        self._initial_info       = initial_info
        self._prompt_type        = prompt_type
        self._lead_name          = lead_name
        self._lead_company       = lead_company
        self._call_context       = call_context
        self._is_outbound        = is_outbound
        self._outbound_intro     = outbound_intro
        self._started            = False
        self._caller_number      = ""
        self._channel_id         = ""
        self._caller_context: dict = {}
        self._enquiry_id: Optional[int] = None
        self._call_start_time: Optional[datetime] = None
        self._transfer_requested = False
        self._transfer_reason    = ""
        self._transfer_notified_at: Optional[float] = None
        self._transfer_event_sent = False
        self._pending_transfer_note: Optional[str] = None
        self._hangup_watchdog_task = None
        self._clear_generation = 0
        self._playback_started_at: Optional[float] = None
        self._playback_ms_scheduled = 0.0
        self._resolved_api_key: Optional[str] = None

        # Bonvoice identifies a call's media stream by "stream_id" (sent
        # to us on the 'start' event). Every outgoing 'media'/'clear'
        # event we send back MUST carry this exact stream_id — it is NOT
        # the same thing as call_id, and Bonvoice's platform will not
        # know which stream a message belongs to without it.
        self._stream_id          = ""

        # Bonvoice requires every outgoing audio frame to be EXACTLY (a
        # multiple of) 320 bytes. Whatever comes out of Gemini's output
        # queue won't naturally be aligned to that, so we buffer any
        # leftover partial frame here and prepend it to the next chunk.
        self._outgoing_leftover  = b""
        self._outgoing_packet_id = 0

        # Ringback tone (see _ringback_sender): plays from the moment the
        # call connects until the agent's first real audio chunk is ready,
        # so the caller hears normal ringing instead of silence during
        # CRM lookup / LLM session setup.
        self._ringback_task = None
        self._ringback_stop_event = asyncio.Event()
        self._real_audio_started = False

        # Tracks when call_should_end first flipped True, so the hangup
        # watchdog can give _audio_sender a grace window to finish
        # streaming the agent's closing line before forcing the socket
        # closed (see _hangup_watchdog / _HANGUP_WATCHDOG_GRACE_SECONDS).
        self._call_should_end_seen_at: Optional[float] = None

    def _generate_ringback_chunk_pcm16(self, elapsed_ms: float, chunk_ms: int = _RINGBACK_CHUNK_MS) -> bytes:
        """Generate one chunk of standard dual-frequency ringback tone as
        PCM16 mono samples at _CALL_SAMPLE_RATE, gated on/off per the
        _RINGBACK_ON_MS / _RINGBACK_OFF_MS cadence. `elapsed_ms` is the
        time since the ringback started, used to decide tone-on vs
        tone-off and to keep the waveform phase-continuous across chunks.

        With chunk_ms=20 this always returns exactly 320 bytes (160
        samples * 2 bytes), matching Bonvoice's required frame size
        exactly — no extra chunking needed for ringback frames.
        """
        cycle_ms = _RINGBACK_ON_MS + _RINGBACK_OFF_MS
        position_in_cycle = elapsed_ms % cycle_ms
        is_tone_on = position_in_cycle < _RINGBACK_ON_MS

        n_samples = int(_CALL_SAMPLE_RATE * chunk_ms / 1000.0)
        samples = bytearray()

        if not is_tone_on:
            # silence during the "off" part of the cadence
            return bytes(n_samples * 2)

        start_t = elapsed_ms / 1000.0
        for i in range(n_samples):
            t = start_t + (i / _CALL_SAMPLE_RATE)
            value = (
                math.sin(2 * math.pi * _RINGBACK_FREQ_1_HZ * t)
                + math.sin(2 * math.pi * _RINGBACK_FREQ_2_HZ * t)
            ) / 2.0
            sample = int(value * _RINGBACK_AMPLITUDE * 32767)
            sample = max(-32768, min(32767, sample))
            samples += struct.pack("<h", sample)

        return bytes(samples)

    async def _ringback_sender(self):
        """Streams standard ringback tone to the caller from call-connect
        time until the real agent audio is ready (see _real_audio_started,
        set by _audio_sender as soon as it gets the first real chunk)."""
        elapsed_ms = 0.0
        try:
            while not self._ringback_stop_event.is_set():
                if self.ws.client_state != WebSocketState.CONNECTED:
                    break

                pcm_chunk = self._generate_ringback_chunk_pcm16(elapsed_ms)
                sent_ok = await self._send_media_frame(pcm_chunk)
                if not sent_ok:
                    break

                elapsed_ms += _RINGBACK_CHUNK_MS
                await asyncio.sleep(_RINGBACK_CHUNK_MS / 1000.0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.call_id}] Ringback sender error: {e}")
        finally:
            logger.info(f"[{self.call_id}] Ringback sender stopped after {elapsed_ms:.0f}ms.")

    def _next_packet_id(self) -> int:
        self._outgoing_packet_id += 1
        return self._outgoing_packet_id

    async def _send_media_frame(self, pcm16_frame: bytes) -> bool:
        """Send exactly one Bonvoice 'media' event. `pcm16_frame` must
        already be sized to a multiple of _BONVOICE_CHUNK_BYTES (320
        bytes) — callers are responsible for chunking/buffering before
        calling this (see _send_pcm16_media for the buffered path used
        for real agent audio). Returns False if the socket is closed.
        """
        try:
            await self.ws.send_text(json.dumps({
                "event": "media",
                "stream_id": self._stream_id,
                "media": {
                    "packet_id": self._next_packet_id(),
                    "timestamp": int(time.time() * 1000),
                    "payload": base64.b64encode(pcm16_frame).decode("ascii"),
                },
            }))
            return True
        except (WebSocketDisconnect, RuntimeError) as e:
            logger.info(f"[{self.call_id}] Socket closed while sending media ({e}).")
            return False
        except Exception as e:
            logger.error(f"[{self.call_id}] Failed to send media frame: {e}")
            return False

    async def _send_pcm16_media(self, pcm16_bytes: bytes) -> bool:
        """Buffer + split arbitrary-length PCM16 audio into Bonvoice's
        required 320-byte (20ms @ 8kHz/16-bit/mono) frames and send each
        as its own 'media' event. Any leftover bytes that don't fill a
        full 320-byte frame are held in self._outgoing_leftover and
        prepended to the next call. Returns False if the socket closed
        mid-send (caller should stop sending).
        """
        data = self._outgoing_leftover + pcm16_bytes
        n_full_frames = len(data) // _BONVOICE_CHUNK_BYTES

        for i in range(n_full_frames):
            frame = data[i * _BONVOICE_CHUNK_BYTES: (i + 1) * _BONVOICE_CHUNK_BYTES]
            if not await self._send_media_frame(frame):
                return False

        self._outgoing_leftover = data[n_full_frames * _BONVOICE_CHUNK_BYTES:]
        return True

    async def run(self):
        """Main loop: receive JSON messages over the WebSocket, dispatch to Gemini."""
        try:
            while True:
                try:
                    raw = await self.ws.receive_text()
                except WebSocketDisconnect:
                    logger.info(f"[{self.call_id}] WebSocket disconnected.")
                    break
                except RuntimeError as e:
                    logger.info(f"[{self.call_id}] WebSocket runtime error (connection closed): {e}")
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(f"[{self.call_id}] Ignoring non-JSON message.")
                    continue

                event = msg.get("event")

                if event == "start":
                    logger.info(f"[RAW START EVENT] {json.dumps(msg)}")
                    await self._handle_start(msg)

                elif event == "media":
                    if not self._started:
                        logger.warning(f"[{self.call_id}] Got media before start — ignoring.")
                        continue

                    # Bonvoice shape: {"event":"media","stream_id":...,
                    # "media":{"packet_id":...,"timestamp":...,"payload":...}}
                    audio_b64 = ""
                    if isinstance(msg.get("media"), dict):
                        audio_b64 = msg["media"].get("payload", "")
                    if not audio_b64:
                        audio_b64 = msg.get("audio", "")

                    if audio_b64 and self.bridge:
                        try:
                            audio_bytes = base64.b64decode(audio_b64)
                        except Exception:
                            logger.warning(f"[{self.call_id}] Bad base64 audio payload.")
                            continue

                        # Already raw PCM16 8kHz mono per Bonvoice spec —
                        # no format conversion needed.
                        await self.bridge.send_audio(audio_bytes)

                        if self.recorder:
                            await self.recorder.add_caller_audio(audio_bytes)

                elif event == "stop":
                    logger.info(f"[{self.call_id}] Stop event received.")
                    break

                elif event == "connected":
                    logger.info(f"[{self.call_id}] 'connected' event received, waiting for 'start'.")

                elif event == "transfer":
                    logger.info(f"[{self.call_id}] Received 'transfer' event: {msg}")

                elif event == "clear":

                    logger.info(f"[{self.call_id}] Received 'clear' event — resetting playback state.")
                    if self.bridge:
                        self.bridge._interrupted_flag = True
                    self._playback_started_at = None
                    self._playback_ms_scheduled = 0.0
                    self._outgoing_leftover = b""

                else:
                    logger.warning(f"[{self.call_id}] Unknown event type: {event!r}")

        except asyncio.CancelledError:
            logger.warning(f"[{self.call_id}] run() task was CANCELLED (this is usually why nothing else logs).")
            raise
        except Exception as e:
            logger.exception(f"[{self.call_id}] Unexpected error: {e}")
        finally:
            await self._cleanup()

    async def _handle_start(self, msg: dict):
        if self._started:
            return

        # Bonvoice shape: {"event":"start","data":{"stream_id":...,
        # "call_id":...,"from":...,"to":...}}
        start_data = msg.get("data", {}) or {}

        self._stream_id = start_data.get("stream_id") or msg.get("stream_id") or ""
        if not self._stream_id:
            logger.warning(
                f"[{self.call_id}] No stream_id in start event — outgoing "
                f"media/clear events won't be attributable to a stream. "
                f"Raw start event: {json.dumps(msg)}"
            )

        incoming_call_id = start_data.get("call_id") or msg.get("call_id")
        if incoming_call_id:
            self.call_id = incoming_call_id
            logger.info(f"[{self.call_id}] call_id received from start event.")
        else:
            logger.warning(
                f"[{self.call_id}] No call_id in start event — using generated "
                f"fallback ID. Raw start event: {json.dumps(msg)}"
            )

        self._lead_name     = msg.get("lead_name") or self._lead_name
        self._lead_company  = msg.get("lead_company") or self._lead_company
        self._prompt_type   = msg.get("prompt_type") or self._prompt_type
        self._is_outbound   = msg.get("is_outbound", self._is_outbound)

        # Start ringback tone RIGHT NOW — before the CRM lookup and Gemini
        # bridge setup below, which can take a moment. This fills that gap
        # with normal ringing instead of silence. It auto-stops the moment
        # the agent's first real audio chunk is ready (see _audio_sender).
        logger.info(f"[{self.call_id}] Starting ringback tone while the call is being set up.")
        self._ringback_task = asyncio.create_task(self._ringback_sender())

        def _looks_like_phone_number(value: str) -> bool:
            if not value:
                return False
            digits = value.lstrip("+").replace(" ", "").replace("-", "")
            return digits.isdigit() and len(digits) >= 7

        raw_lead_name = msg.get("lead_name") or ""
        self._caller_number = (
            start_data.get("from")
            or msg.get("caller_number")
            or msg.get("from")
            or msg.get("ani")
            or (raw_lead_name if _looks_like_phone_number(raw_lead_name) else "")
        )
        self._channel_id = (
            start_data.get("to")
            or msg.get("channel_id")
            or msg.get("did")
            or schoolknot_api.SCHOOLKNOT_CHANNEL_ID
        )

        self._call_start_time = datetime.now(timezone.utc)
        if self._caller_number:
            logger.info(f"[{self.call_id}] Calling get_enquiry_details for {self._caller_number}...")
            try:
                result = await schoolknot_api.get_enquiry_details(self._caller_number)
                logger.info(f"[{self.call_id}] get_enquiry_details response: {result}")
            except Exception as e:
                logger.exception(f"[{self.call_id}] get_enquiry_details FAILED")
                result = None

            if result is None:
                self._enquiry_id = None
                self._caller_context = {"caller_status": "new"}
                logger.warning(
                    f"[{self.call_id}] Enquiry lookup failed for "
                    f"{self._caller_number!r} — proceeding as new caller "
                    f"so call data isn't lost."
                )
            elif result.get("type") == 2 and result.get("data"):
                records = result["data"]
                primary = records[0]
                self._enquiry_id = primary.get("enquiry_id")
                self._caller_context = {
                    "caller_status": "existing",
                    "parent_name": primary.get("father_name") or primary.get("mother_name"),
                    "father_name": primary.get("father_name"),
                    "mother_name": primary.get("mother_name"),
                    "student_name": primary.get("student_name"),
                    "grade": primary.get("class_opted_for"),
                    "branch_name": primary.get("branch_name"),
                    "enquiry_status": primary.get("probability_name"),
                    "enquiry_created_date": primary.get("enquiry_created_date"),
                    "enquiry_academic_year": primary.get("enquiry_academic_year"),
                    "all_enquiries": records,  # full list, for multi-child callers
                }
            else:
                self._enquiry_id = None
                self._caller_context = {"caller_status": "new"}
        else:
            logger.warning(f"[{self.call_id}] No caller number available on start event — skipping lookup.")
            self._enquiry_id = None
            self._caller_context = {"caller_status": "new"}

        outbound_intro = self._outbound_intro
        if self._is_outbound and not outbound_intro:
            from prompts import build_outbound_intro
            outbound_intro = build_outbound_intro(self._lead_name, self._prompt_type)

        self.recorder = CallRecorder(
            call_sid=self.call_id,
            sample_rate=_CALL_SAMPLE_RATE,
            output_dir=_RECORDINGS_DIR,
        )

        logger.info(f"[{self.call_id}] Creating GeminiBridge instance...")
        self.bridge = GeminiBridge(
            call_sid=self.call_id,
            lead_id=self._lead_id,
            outbound_intro=outbound_intro,
            initial_info=self._initial_info,
            prompt_type=self._prompt_type,
            org_config=self._caller_context,
        )

        try:
            logger.info(f"[{self.call_id}] Calling bridge.start()...")
            await self.bridge.start(send_greeting=False)
            logger.info(f"[{self.call_id}] bridge.start() returned successfully.")
        except BaseException as e:
            # Catch BaseException (not just Exception) so that
            # asyncio.CancelledError and similar don't fail silently.
            logger.exception(f"[{self.call_id}] bridge.start() FAILED: {type(e).__name__}: {e}")
            raise

        if outbound_intro:
            trigger = (
                f"IMPORTANT: The lead's name is {self._lead_name!r}. Call type: {self._prompt_type}.\n"
                f"Say exactly and only: \"{outbound_intro}\" — nothing else. Speak now."
            )
        else:
            from config import AGENT_NAME, COMPANY_NAME
            if self._caller_context.get("caller_status") == "existing":
                parent_name = self._caller_context.get("parent_name") or ""
                trigger = (
                    f"IMPORTANT: This is a RETURNING caller — see the "
                    f"'RETURNING CALLER — CRM MATCH FOUND' section in your "
                    f"instructions for exactly who they are and what is "
                    f"already known about them. Greet them personally by "
                    f"name" + (f" ({parent_name})" if parent_name else "") +
                    f" instead of the standard first-time greeting, and "
                    f"begin immediately. Do not re-ask anything already "
                    f"listed as known in that section."
                )
            else:
                trigger = (
                    f"IMPORTANT: The lead's name is {self._lead_name!r}. Call type: {self._prompt_type}.\n"
                    f"Introduce yourself as {AGENT_NAME} from {COMPANY_NAME} and begin immediately."
                )

        try:
            logger.info(f"[{self.call_id}] Sending trigger message to Gemini...")
            await self.bridge._session.send_realtime_input(text=trigger)
            logger.info(f"[{self.call_id}] Gemini session started, greeting triggered.")
        except BaseException as e:
            logger.exception(f"[{self.call_id}] send_realtime_input FAILED: {type(e).__name__}: {e}")
            raise

        self._started = True
        self._sender_task = asyncio.create_task(self._audio_sender())
        self._silence_watcher_task = asyncio.create_task(self._silence_watcher())
        self._hangup_watchdog_task = asyncio.create_task(self._hangup_watchdog())

        logger.info(f"[{self.call_id}] Audio sender + silence watcher + hangup watchdog tasks created.")

    async def _close_socket(self):
        """Bonvoice's spec defines no client-to-platform 'stop'/end-call
        event — the only documented events are start/media/clear/transfer,
        all of which are either inbound-only (start) or unrelated to
        ending the call. Ending the call is therefore just: close this
        WebSocket connection.
        """
        try:
            if self.ws.client_state == WebSocketState.CONNECTED:
                await self.ws.close()
        except Exception:
            pass

    async def _hangup_watchdog(self):
        """
        Safety-net fallback only. The PRIMARY, correct way a normal call
        ends is via _audio_sender: it waits until the agent's output
        queue is genuinely empty (i.e. the closing line has actually been
        generated AND streamed to the caller) before closing the socket.

        This watchdog used to close the socket the instant
        `call_should_end` flipped True, checked every 0.25s, with NO
        regard for whether the agent had actually finished speaking its
        closing line yet. Since `call_should_end` is set the moment the
        `end_call` tool is invoked — which can happen before or while the
        closing audio is still being generated/streamed — that raced
        ahead of _audio_sender and cut the agent off mid-sentence (or
        before it spoke at all). That was the root cause of calls ending
        abruptly right after the caller said "thank you".

        Fix: give _audio_sender first right of way. Only step in here as
        a fallback, after _HANGUP_WATCHDOG_GRACE_SECONDS have passed
        since call_should_end first became True — long enough for a
        short closing line to be generated, streamed, and played, but
        short enough to guarantee the call still ends if something else
        goes wrong.
        """
        if not self.bridge:
            return
        try:
            while True:
                await asyncio.sleep(0.25)

                if self.ws.client_state != WebSocketState.CONNECTED:
                    break

                if getattr(self.bridge, "call_should_end", False):
                    if self._call_should_end_seen_at is None:
                        self._call_should_end_seen_at = time.monotonic()
                        logger.info(
                            f"[{self.call_id}] call_should_end observed — starting "
                            f"{_HANGUP_WATCHDOG_GRACE_SECONDS:.0f}s grace period so the "
                            f"agent's closing line can finish streaming before this "
                            f"fallback watchdog would step in."
                        )

                    # Already finished draining on its own (audio_sender's
                    # queue-aware close already ran) — nothing left to do.
                    queue_drained = (
                        self.bridge.output_queue.empty()
                        if self.bridge and hasattr(self.bridge, "output_queue")
                        else True
                    )
                    elapsed = time.monotonic() - self._call_should_end_seen_at

                    if elapsed < _HANGUP_WATCHDOG_GRACE_SECONDS and not queue_drained:
                        # Give the sender more time — audio is still queued.
                        continue
                    if elapsed < 1.0:
                        # Even if the queue looks empty, give at least a
                        # beat for the last chunk to actually finish
                        # playing out (pacing sleep in _audio_sender).
                        continue

                    logger.info(
                        f"[{self.call_id}] Hangup watchdog fallback firing "
                        f"({elapsed:.1f}s after call_should_end, queue_drained="
                        f"{queue_drained}) — closing call now."
                    )
                    await self._close_socket()
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.call_id}] Hangup watchdog error: {e}")

    async def _silence_watcher(self):

        if not self.bridge:
            return
        try:
            while True:
                await asyncio.sleep(_SILENCE_CHECK_INTERVAL_SECONDS)

                if self.ws.client_state != WebSocketState.CONNECTED:
                    break

                if getattr(self.bridge, "call_should_end", False):
                    break

                idle = self.bridge.seconds_since_speech()
                if idle >= _SILENCE_TIMEOUT_SECONDS:
                    logger.info(
                        f"[{self.call_id}] {idle:.1f}s of silence detected "
                        f"(threshold {_SILENCE_TIMEOUT_SECONDS}s) — treating as "
                        f"an abandoned call and ending it."
                    )
                    await self._close_socket()
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.call_id}] Silence watcher error: {e}")

    @staticmethod
    def _to_transfer_target(staff_number: str) -> str:
        if not staff_number:
            return ""
        digits = "".join(ch for ch in staff_number if ch.isdigit())
        return digits or staff_number

    async def _send_transfer_event(self, staff_number: str):
        if self._transfer_event_sent:
            logger.info(f"[{self.call_id}] Transfer event already sent for this call — skipping duplicate.")
            return

        target = self._to_transfer_target(staff_number)
        if not target:
            logger.warning(
                f"[{self.call_id}] No usable staff number to build a "
                f"'transfer' target from ({staff_number!r}) — not sending."
            )
            return

        # Bonvoice shape: {"event":"transfer","transferTo":"{phone_number}"}
        payload = {
            "event": "transfer",
            "transferTo": target,
        }
        try:
            await self.ws.send_text(json.dumps(payload))
            self._transfer_event_sent = True
            logger.info(f"[{self.call_id}] Sent 'transfer' event to Bonvoice — payload={payload}")
        except (WebSocketDisconnect, RuntimeError) as e:
            logger.info(f"[{self.call_id}] Could not send transfer event (socket closed): {e}")
        except Exception as e:
            logger.error(f"[{self.call_id}] Failed to send transfer event: {e}")

    async def _maybe_request_warm_transfer(self):
        from datetime import datetime, timezone

        reason = self._transfer_reason or "caller_requested_human"
        staff_number = (
            getattr(self.bridge, "_transfer_destination", "") or _TRANSFER_STAFF_NUMBER
        )
        note = f"Live transfer requested — reason: {reason}"

        try:
            await self.ws.send_text(json.dumps({
                "event": "transfer_requested",
                "call_id": self.call_id,
                "reason": reason,
                "staff_number": staff_number,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }))
            self._transfer_notified_at = time.monotonic()
            logger.info(
                f"[{self.call_id}] transfer_requested sent over WebSocket → "
                f"staff_number={staff_number!r}, reason={reason!r}"
            )
        except Exception as e:
            logger.error(f"[{self.call_id}] Failed to send transfer event: {e}")

        await self._send_transfer_event(staff_number)
        if self._enquiry_id:
            try:
                block = schoolknot_api.build_other_request_block(
                    requested_for=note,
                    enquiry_id=self._enquiry_id,
                )
                result = await schoolknot_api.insert_enquiry_service([block])
                logger.info(f"[{self.call_id}] Transfer note logged to SchoolKnot: {result}")
            except Exception as e:
                logger.error(
                    f"[{self.call_id}] insert_enquiry_service FAILED while logging "
                    f"transfer note (queuing for retry at call end): {e}"
                )
                self._pending_transfer_note = note
        else:
            self._pending_transfer_note = note
            logger.info(
                f"[{self.call_id}] Transfer queued — will be sent with new-enquiry batch at call end."
            )

    async def _send_clear_event(self):
        self._clear_generation += 1
        try:
            # Bonvoice shape: {"event":"clear","stream_id":...}
            await self.ws.send_text(json.dumps({
                "event": _CLEAR_EVENT_NAME,
                "stream_id": self._stream_id,
            }))
            logger.info(
                f"[{self.call_id}] Sent '{_CLEAR_EVENT_NAME}' event to "
                f"Bonvoice — caller interruption (generation {self._clear_generation})."
            )
        except (WebSocketDisconnect, RuntimeError) as e:
            logger.info(f"[{self.call_id}] Could not send clear event (socket closed): {e}")
        except Exception as e:
            logger.error(f"[{self.call_id}] Failed to send clear event: {e}")

    async def _audio_sender(self):
        """Pulls audio chunks from Gemini's output queue and streams them to the client."""
        if not self.bridge:
            return
        try:
            while True:
                if getattr(self.bridge, "_interrupted_flag", False):
                    self.bridge._interrupted_flag = False
                    await self._send_clear_event()
                    self._playback_started_at = None
                    self._playback_ms_scheduled = 0.0
                    self._outgoing_leftover = b""
                try:
                    chunk = await asyncio.wait_for(
                        self.bridge.output_queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    self._playback_started_at = None
                    self._playback_ms_scheduled = 0.0

                    if getattr(self.bridge, "call_should_end", False):
                        logger.info(f"[{self.call_id}] call_should_end detected (idle queue) — closing gracefully.")
                        await self._close_socket()
                        break
                    if (
                        self._transfer_requested
                        and getattr(self.bridge, "_caller_has_spoken", False)
                    ):
                        if self._transfer_notified_at is None:
                            continue
                        elapsed = time.monotonic() - self._transfer_notified_at
                        if elapsed < _TRANSFER_GRACE_PERIOD_SECONDS:
                            continue
                        logger.info(
                            f"[{self.call_id}] Transfer requested (idle queue) — "
                            f"grace period elapsed, closing socket."
                        )
                        await self._close_socket()
                        break
                    continue

                if chunk is None:
                    break

                if not self._real_audio_started:
                    # First real agent audio chunk is ready — stop the
                    # ringback tone right now so it doesn't overlap with
                    # the agent starting to speak.
                    self._real_audio_started = True
                    self._ringback_stop_event.set()
                    if self._ringback_task and not self._ringback_task.done():
                        self._ringback_task.cancel()
                        try:
                            await self._ringback_task
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            logger.error(f"[{self.call_id}] Error awaiting ringback task: {e}")
                    logger.info(f"[{self.call_id}] Ringback stopped — real audio starting.")

                if getattr(self.bridge, "_interrupted_flag", False):
                    self.bridge._interrupted_flag = False
                    await self._send_clear_event()
                    self._playback_started_at = None
                    self._playback_ms_scheduled = 0.0
                    self._outgoing_leftover = b""
                    continue

                chunk_ms = len(chunk) / _PCM_8K_BYTES_PER_MS
                now = time.monotonic()
                if self._playback_started_at is None:
                    self._playback_started_at = now
                    self._playback_ms_scheduled = 0.0

                target_time = self._playback_started_at + (self._playback_ms_scheduled / 1000.0)
                sleep_needed = target_time - now - (_PACING_LOOKAHEAD_MS / 1000.0)
                if sleep_needed > 0:
                    await asyncio.sleep(sleep_needed)

                self._playback_ms_scheduled += chunk_ms
                if self.recorder:
                    await self.recorder.add_agent_audio(chunk)

                if self.ws.client_state != WebSocketState.CONNECTED:
                    logger.info(f"[{self.call_id}] Socket no longer connected, stopping sender.")
                    break

                # chunk is already raw PCM16 8kHz mono — split/pad into
                # Bonvoice's required 320-byte frames and send.
                if not await self._send_pcm16_media(chunk):
                    logger.info(f"[{self.call_id}] Socket closed while sending; stopping sender.")
                    break

                if getattr(self.bridge, "transfer_requested", False) and not self._transfer_requested:
                    self._transfer_requested = True
                    self._transfer_reason = getattr(self.bridge, "transfer_reason", "")
                    asyncio.create_task(self._maybe_request_warm_transfer())

                # Also check on every chunk in case queue drains fast
                if (
                    self._transfer_requested
                    and getattr(self.bridge, "_caller_has_spoken", False)
                    and self.bridge.output_queue.empty()
                    and self._transfer_notified_at is not None
                    and (time.monotonic() - self._transfer_notified_at) >= _TRANSFER_GRACE_PERIOD_SECONDS
                ):
                    logger.info(f"[{self.call_id}] Closing socket — transfer handoff (grace period elapsed).")
                    await self._close_socket()
                    break

                if getattr(self.bridge, "call_should_end", False) and self.bridge.output_queue.empty():
                    logger.info(f"[{self.call_id}] Closing socket — call ending naturally.")
                    await self._close_socket()
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.call_id}] Audio sender error: {e}")

    def _build_insert_enquiry_blocks(self, transcript: str, collected_info) -> list[dict]:
        """
        Assemble the batch of r_type blocks to send to insert_enquiry_service.

        FIX (see call log analysis): previously, follow-up / walk-in /
        pending-transfer-note blocks for NEW callers were nested inside
        `if child_name:`, so if the caller never gave their child's name
        (e.g. they only asked for a callback, or hung up early), ALL of
        that captured info — including callback times and transfer
        notes — was silently discarded, not just the enquiry insert.

        FIX (this pass): schedule_walkin_date / follow_up_date were going
        out either empty or as a raw, unparsed string (e.g. "Friday")
        because callback_time was used as-is. Every use of callback_time
        below is now routed through _normalize_datetime(), which converts
        it to SchoolKnot's required 'YYYY-MM-DD HH:MM:SS' format (or logs
        a warning and falls back to '' if it truly can't be parsed).
        gemini_bridge.py already normalizes callback_time at the point
        it's captured via the LLM tool call, so in the common case this
        is a no-op re-format; this is the safety net for the regex
        fallback path and any other/older captures that bypass that.

        FIX (branch/school_id): the caller states which branch they want
        (e.g. "Attapur", "Katedan") during the call; this is resolved
        here to that branch's school_id + api_key via
        schoolknot_api.resolve_branch(), so the new-enquiry insert below
        carries the correct school_id and — via self._resolved_api_key,
        read by _cleanup() when it calls insert_enquiry_service() — the
        correct branch-specific api_key, instead of one global
        key/no-school_id being used for every branch.

        Now:
          - The new-enquiry insert (r_type=1) still requires child_name,
            since school_id/child_name are non-nullable DB columns.
          - If child_name is missing but *other* info was captured
            (callback time, visit request, pending transfer note), we
            log it as a free-text r_type=4 note instead of dropping it.
          - The requests/tertiary-signals summary note for new callers
            no longer requires child_name either.
        """

        blocks: list[dict] = []

        if collected_info is None:
            logger.info(f"[{self.call_id}] No collected_info on bridge — skipping insert_enquiry_service.")
            return blocks

        child_name = getattr(collected_info, "child_name", None)
        father_name = getattr(collected_info, "father_name", None)
        mother_name = getattr(collected_info, "mother_name", None)
        dob = getattr(collected_info, "dob", None)
        grade = getattr(collected_info, "admission_opted_for", None)
        email = getattr(collected_info, "email", None)
        mother_mobile = getattr(collected_info, "mother_mobile", None)
        raw_callback_time = getattr(collected_info, "callback_time", None)
        callback_time = _normalize_datetime(raw_callback_time, self.call_id)
        visit_requested = getattr(collected_info, "visit_requested", False)
        requests_list = getattr(collected_info, "requests", []) or []
        tertiary_list = getattr(collected_info, "tertiary_signals", []) or []

        branch_name = getattr(collected_info, "branch_name", None)
        branch_cfg = schoolknot_api.resolve_branch(branch_name)
        self._resolved_api_key = branch_cfg["api_key"] if branch_cfg else None
        school_id = branch_cfg["school_id"] if branch_cfg else ""

        if branch_name and not branch_cfg:
            logger.warning(
                f"[{self.call_id}] Caller mentioned branch {branch_name!r} but it "
                f"didn't match any known branch — using default api_key, no school_id."
            )

        caller_status = self._caller_context.get("caller_status")

        # ── existing caller — unchanged, gated on enquiry_id ────────────
        if caller_status == "existing" and self._enquiry_id:

            if callback_time:
                blocks.append(schoolknot_api.build_followup_block(
                    follow_up_date=callback_time,
                    enquiry_id=self._enquiry_id,
                ))

            if visit_requested:
                blocks.append(schoolknot_api.build_walkin_block(
                    schedule_walkin_date=callback_time or "",
                    comments="Campus visit requested during AI call.",
                    enquiry_id=self._enquiry_id,
                ))

        # ── new caller ───────────────────────────────────────────────
        elif caller_status == "new":

            if child_name:
                enquiry_date = datetime.now().strftime("%Y-%m-%d")
                # probability: 2 = "Enquired / School Visit" if the caller
                # asked for a campus visit, else 1 = "Interested / Online /
                # Phone Enquiry" for a plain phone enquiry.
                probability = "2" if visit_requested else "1"

                blocks.append(schoolknot_api.build_new_enquiry_block(
                    child_name=child_name,
                    father_name=father_name or "",
                    mother_name=mother_name or "",
                    mobile=self._caller_number,
                    mother_mobile=mother_mobile or "",
                    email=email or "",
                    dob=dob or "",
                    admission_opted_for=grade or "",
                    enquiry_date=enquiry_date,
                    probability=probability,
                    school_id=school_id,
                ))

                if callback_time:
                    blocks.append(schoolknot_api.build_followup_block(
                        follow_up_date=callback_time,
                    ))

                if visit_requested:
                    blocks.append(schoolknot_api.build_walkin_block(
                        schedule_walkin_date=callback_time or "",
                        comments="Campus visit requested during AI call.",
                    ))

                if self._pending_transfer_note:
                    blocks.append(schoolknot_api.build_other_request_block(
                        requested_for=self._pending_transfer_note,
                    ))

            else:

                note_parts = []
                if callback_time:
                    note_parts.append(f"Callback requested: {callback_time}")
                if visit_requested:
                    note_parts.append("Campus visit requested")
                if self._pending_transfer_note:
                    note_parts.append(self._pending_transfer_note)
                if father_name or mother_name or self._caller_number:
                    who = father_name or mother_name or ""
                    note_parts.append(
                        f"Caller info (no child name given): {who} "
                        f"{self._caller_number}".strip()
                    )

                if note_parts:
                    note = "Incomplete new-caller enquiry — " + " | ".join(note_parts)
                    blocks.append(schoolknot_api.build_other_request_block(
                        requested_for=note,
                    ))
                    logger.info(
                        f"[{self.call_id}] No child_name captured — logging "
                        f"partial info as a free-text note instead of an enquiry."
                    )

        # ── requests / tertiary signals — no longer gated on child_name ──
        if requests_list or tertiary_list:
            summary_parts = []
            if requests_list:
                summary_parts.append("Requested: " + ", ".join(requests_list))
            if tertiary_list:
                summary_parts.append("Insights: " + ", ".join(tertiary_list))
            summary_note = " | ".join(summary_parts)

            if caller_status == "existing" and self._enquiry_id:
                blocks.append(schoolknot_api.build_other_request_block(
                    requested_for=summary_note,
                    enquiry_id=self._enquiry_id,
                ))
            elif caller_status == "new":
                blocks.append(schoolknot_api.build_other_request_block(
                    requested_for=summary_note,
                ))

        if not blocks:
            logger.info(
                f"[{self.call_id}] No structured enquiry data captured this call — "
                f"skipping insert_enquiry_service (nothing new to write back)."
            )

        return blocks

    async def _cleanup(self):
        if self._ringback_task and not self._ringback_task.done():
            self._ringback_stop_event.set()
            self._ringback_task.cancel()
            try:
                await self._ringback_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[{self.call_id}] Error awaiting ringback task during cleanup: {e}")

        if self._sender_task:
            self._sender_task.cancel()
            try:
                await self._sender_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[{self.call_id}] Error awaiting sender task during cleanup: {e}")

        if self._silence_watcher_task:
            self._silence_watcher_task.cancel()
            try:
                await self._silence_watcher_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[{self.call_id}] Error awaiting silence watcher during cleanup: {e}")

        if self._hangup_watchdog_task:
            self._hangup_watchdog_task.cancel()
            try:
                await self._hangup_watchdog_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[{self.call_id}] Error awaiting hangup watchdog during cleanup: {e}")

        transcript             = self.bridge.full_transcript() if self.bridge else ""
        structured_transcript  = self.bridge.structured_transcript() if self.bridge else []
        collected_info         = self.bridge.collected_info    if self.bridge else None

        # Diagnostic: dump what was actually captured this call, so a
        # "no blocks to send" skip can be traced back to which specific
        # fields came back empty (e.g. child_name never extracted) rather
        # than just seeing the skip with no context.
        logger.info(
            f"[{self.call_id}] collected_info dump: "
            f"{vars(collected_info) if collected_info else None}"
        )

        if self.bridge:
            await self.bridge.stop()
        recording_path = None
        if self.recorder:
            try:
                local_path = self.recorder.save()
                logger.info(f"[{self.call_id}] Recording saved locally: {local_path}")
                try:
                    from mongo_recording_store import upload_recording
                    upload_recording(self.call_id, local_path)
                    recording_path = self.call_id  # reference key, not a filesystem path
                except Exception as e:
                    logger.error(f"[{self.call_id}] MongoDB upload failed, local copy kept: {e}")
                    recording_path = local_path
                else:
                    try:
                        import os
                        os.remove(local_path)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"[{self.call_id}] Failed to save recording: {e}")
        try:
            blocks = self._build_insert_enquiry_blocks(transcript, collected_info)
            if blocks:

                # self._resolved_api_key is set inside
                # _build_insert_enquiry_blocks() above based on the
                # caller-stated branch (None if no branch was resolved,
                # in which case insert_enquiry_service() falls back to
                # the default global SCHOOLKNOT_INSERT_API_KEY).
                result = await schoolknot_api.insert_enquiry_service(
                    blocks, api_key=self._resolved_api_key
                )
                logger.info(f"[{self.call_id}] insert_enquiry_service SUCCESS — response: {result}")
            else:
                logger.info(f"[{self.call_id}] insert_enquiry_service SKIPPED — no blocks to send.")
        except Exception as e:
            logger.error(f"[{self.call_id}] Failed to call insert_enquiry_service: {e}")

        # Save the full call record (structured transcript, enquiry
        # details, recording reference) to MongoDB as one document per calls.
        try:
            from mongo_call_store import save_call_record
            save_call_record(
                call_id=self.call_id,
                caller_number=self._caller_number,
                channel_id=self._channel_id,
                caller_context=self._caller_context,
                enquiry_id=self._enquiry_id,
                transcript=structured_transcript,
                collected_info=collected_info,
                recording_reference=recording_path,
                call_start_time=self._call_start_time,
                transfer_requested=self._transfer_requested,
                transfer_reason=self._transfer_reason,
                prompt_type=self._prompt_type,
                is_outbound=self._is_outbound,
            )
        except Exception as e:
            logger.error(f"[{self.call_id}] Failed to save call record to MongoDB: {e}")

        await self._close_socket()

        if self._on_call_end:
            if asyncio.iscoroutinefunction(self._on_call_end):
                await self._on_call_end(self.call_id, transcript, collected_info, recording_path)
            else:
                self._on_call_end(self.call_id, transcript, collected_info, recording_path)