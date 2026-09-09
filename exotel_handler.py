"""
ExotelCallHandler — manages one bidirectional Exotel WebSocket session.

Protocol summary (Exotel → Bot):
  connected  →  websocket handshake confirmed
  start      →  call metadata + custom_parameters
  media      →  base64-encoded 8 kHz PCM audio chunk
  dtmf       →  keypress from caller
  stop       →  call ended

Protocol summary (Bot → Exotel):
  media      →  base64-encoded 8 kHz PCM audio chunk to play to caller
  mark       →  optional milestone marker
"""
import asyncio
import json
import logging
from typing import Optional

from starlette.websockets import WebSocketDisconnect

from audio_utils import b64_to_pcm, pcm_to_b64
from gemini_bridge import GeminiBridge

logger = logging.getLogger(__name__)


class ExotelCallHandler:
    def __init__(self, websocket, on_call_end=None, lead_id: str = "", initial_info=None,
                 prompt_type: str = "sales", lead_name: str = "there", lead_company: str = "",
                 is_outbound: bool = False):
        self.ws            = websocket
        self.call_sid      = "unknown"
        self.stream_sid    = "unknown"
        self.bridge: Optional[GeminiBridge] = None
        self._sender_task  = None
        self._on_call_end  = on_call_end
        self._lead_id      = lead_id
        self._initial_info = initial_info
        # These come from WS query params — used as fallback if _on_start custom_parameters is empty
        self._prompt_type  = prompt_type
        self._lead_name    = lead_name
        self._lead_company = lead_company
        self._is_outbound  = is_outbound

    async def run(self):
        """Main loop: receive messages from Exotel, dispatch to bridge."""
        try:
            while True:
                try:
                    data = await self.ws.receive()
                except RuntimeError:
                    logger.info(f"[{self.call_sid}] WebSocket disconnected before receive.")
                    break
                if data.get("type") == "websocket.disconnect":
                    logger.info(f"[{self.call_sid}] Received disconnect frame.")
                    break
                if "text" in data:
                    raw = data["text"]
                elif "bytes" in data:
                    raw = data["bytes"].decode("utf-8")
                else:
                    continue
                msg   = json.loads(raw)
                event = msg.get("event", "")
                logger.info(f"[{self.call_sid}] Event: {event}")

                if event == "connected":
                    await self._on_connected(msg)
                elif event == "start":
                    await self._on_start(msg)
                elif event == "media":
                    await self._on_media(msg)
                elif event == "dtmf":
                    await self._on_dtmf(msg)
                elif event == "stop":
                    await self._on_stop(msg)
                    break
        except WebSocketDisconnect:
            logger.info(f"[{self.call_sid}] Connection closed normally.")
        except Exception as e:
            logger.exception(f"[{self.call_sid}] Unexpected error: {e}")
        finally:
            await self._cleanup()

    # ── Event handlers ────────────────────────────────────────────────────────

    async def _on_connected(self, msg: dict):
        logger.info(f"Exotel WebSocket connected. Protocol: {msg.get('protocol')}")

    async def _on_start(self, msg: dict):
        start  = msg.get("start", {})
        logger.info(f"START message: {json.dumps(msg)[:500]}")

        self.call_sid   = start.get("call_sid",   start.get("callSid",   "unknown"))
        self.stream_sid = start.get("stream_sid", start.get("streamSid", "unknown"))
        custom          = start.get("custom_parameters", start.get("customParameters", {}))

        import call_store

        # Try to pick up the pre-started bridge from /exoml
        pre_bridge = call_store.pop_bridge(self.call_sid)
        if pre_bridge:
            logger.info(f"[{self.call_sid}] Using pre-started Gemini session ✓ (greeting already sent)")
            self.bridge = pre_bridge
            self._sender_task = asyncio.create_task(self._audio_sender())
            asyncio.create_task(self._watch_hangup())
            return

        # Fallback: cold-start with stored params
        stored = call_store.pop(self.call_sid)
        lead_name    = stored.get("lead_name",    custom.get("lead_name",    self._lead_name))
        lead_company = stored.get("lead_company", custom.get("lead_company", self._lead_company))
        call_context = stored.get("call_context", custom.get("call_context", ""))
        prompt_type  = stored.get("prompt_type",  custom.get("prompt_type",  self._prompt_type))
        is_outbound  = stored.get("outbound",     custom.get("outbound", "true" if self._is_outbound else "false")).lower() == "true"

        logger.info(f"[{self.call_sid}] Cold-start fallback: lead={lead_name!r}, prompt_type={prompt_type!r}")

        outbound_intro = None
        if is_outbound:
            from prompts import build_outbound_intro
            outbound_intro = build_outbound_intro(lead_name, prompt_type)

        self.bridge = await _session_pool.acquire(
            call_sid=self.call_sid,
            lead_id=self._lead_id,
            lead_name=lead_name,
            lead_company=lead_company,
            call_context=call_context,
            outbound_intro=outbound_intro,
            initial_info=self._initial_info,
            prompt_type=prompt_type,
        )

        self._sender_task = asyncio.create_task(self._audio_sender())
        asyncio.create_task(self._watch_hangup())

    async def _on_media(self, msg: dict):
        if not self.bridge:
            return
        payload = msg.get("media", {}).get("payload", "")
        if payload:
            await self.bridge.send_audio(b64_to_pcm(payload))

    async def _on_dtmf(self, msg: dict):
        digit = msg.get("dtmf", {}).get("digit", "")
        logger.info(f"[{self.call_sid}] DTMF: {digit}")
        if digit == "0" and self.bridge:
            await self.bridge.send_interrupt()

    async def _on_stop(self, msg: dict):
        logger.info(f"[{self.call_sid}] Call stopped by Exotel.")

    # ── Audio sender (Gemini → Exotel) ────────────────────────────────────────

    async def _watch_hangup(self):
        """Wait for Gemini to signal end-of-call, then close the WebSocket."""
        if not self.bridge or not self.bridge.on_hangup:
            return
        await self.bridge.on_hangup.wait()
        # Give Gemini ~1.5s to finish playing the goodbye audio before closing
        await asyncio.sleep(1.5)
        logger.info(f"[{self.call_sid}] Agent hanging up — closing WebSocket")
        try:
            await self.ws.close()
        except Exception:
            pass

    async def _audio_sender(self):
        if not self.bridge:
            return
        try:
            while True:
                chunk = await self.bridge.output_queue.get()
                if chunk is None:
                    break
                await self.ws.send_text(json.dumps({
                    "event":      "media",
                    "stream_sid": self.stream_sid,
                    "media":      {"payload": pcm_to_b64(chunk)},
                }))
        except Exception as e:
            logger.error(f"[{self.call_sid}] Audio sender error: {e}")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def _cleanup(self):
        if self._sender_task:
            self._sender_task.cancel()
        transcript     = self.bridge.full_transcript() if self.bridge else ""
        collected_info = self.bridge.collected_info    if self.bridge else None
        if self.bridge:
            await self.bridge.stop()
        if self._on_call_end:
            if asyncio.iscoroutinefunction(self._on_call_end):
                await self._on_call_end(self.call_sid, transcript, collected_info)
            else:
                self._on_call_end(self.call_sid, transcript, collected_info)


# ── Session pool — keeps N Gemini sessions warm and ready ────────────────────

class _GeminiSessionPool:
    """
    Maintains a pool of pre-warmed GeminiBridge sessions.
    When a call comes in, we hand off a ready session instantly instead of
    waiting for Gemini's ~1-2s connection handshake.
    """
    POOL_SIZE = 2

    def __init__(self):
        self._ready: Optional[asyncio.Queue] = None  # created inside event loop
        self._refill_task: Optional[asyncio.Task] = None

    async def start(self):
        """Called once at server startup to begin filling the pool."""
        global _pool_task
        self._ready = asyncio.Queue()
        loop = asyncio.get_running_loop()
        self._refill_task = loop.create_task(self._keep_pool_full())
        _pool_task = self._refill_task  # module-level ref prevents GC
        print(f"[POOL] Gemini session pool started, task={self._refill_task}", flush=True)

    async def _keep_pool_full(self):
        """Pool keeper — disabled, fresh sessions created per call to avoid stale connections."""
        # Pre-warming causes sessions to expire before calls arrive (WinError 121 / APIError 1006).
        # We cold-start each call instead — Gemini Live connects in ~1-2s which is acceptable.
        print("[POOL] keeper: pre-warming disabled, cold-start mode active", flush=True)
        while True:
            await asyncio.sleep(60)  # idle — just keep the task alive

    async def _warm_one(self):
        """Create one pre-warmed Gemini session with the feedback system prompt baked in.
        The compact greeting override at acquire() time then just triggers speaking immediately
        without any processing delay."""
        try:
            bridge = GeminiBridge(call_sid="pool-warm", prompt_type="feedback")
            await bridge.start(send_greeting=False)
            await self._ready.put(bridge)
            print(f"[POOL] session warmed, pool size={self._ready.qsize()}", flush=True)
        except Exception as e:
            print(f"[POOL] warm failed: {e}", flush=True)
            logger.warning(f"Pool: failed to warm session: {e}", exc_info=True)

    async def acquire(
        self,
        call_sid: str,
        lead_id: str,
        lead_name: str,
        lead_company: str,
        call_context: str,
        outbound_intro: Optional[str],
        initial_info,
        prompt_type: str,
    ) -> GeminiBridge:
        """Always create a fresh Gemini session per call — avoids stale connection errors."""
        logger.info(f"[{call_sid}] Cold-starting fresh Gemini session, prompt_type={prompt_type!r}, lead={lead_name!r}")
        bridge = GeminiBridge(
            call_sid=call_sid,
            lead_id=lead_id,
            lead_name=lead_name,
            lead_company=lead_company,
            call_context=call_context,
            outbound_intro=outbound_intro,
            initial_info=initial_info,
            prompt_type=prompt_type,
        )
        await bridge.start(send_greeting=False)

        if outbound_intro:
            trigger = (
                f"IMPORTANT: The lead's name is {lead_name!r}. Call type: {prompt_type}.\n"
                f"Say exactly and only: \"{outbound_intro}\" — nothing else. Speak now."
            )
        else:
            from config import AGENT_NAME, COMPANY_NAME
            trigger = (
                f"IMPORTANT: The lead's name is {lead_name!r}. Call type: {prompt_type}.\n"
                f"Introduce yourself as {AGENT_NAME} from {COMPANY_NAME} and begin immediately."
            )

        await bridge._session.send_realtime_input(text=trigger)
        logger.info(f"[{call_sid}] Greeting sent, lead={lead_name!r}")
        return bridge


_session_pool = _GeminiSessionPool()
# Module-level reference to prevent GC of the background task
_pool_task: Optional[asyncio.Task] = None
