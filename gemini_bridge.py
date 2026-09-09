# """
# GeminiBridge -- manages a single Gemini Live API session for one phone call.
# """

# import asyncio
# import base64
# import logging
# from typing import Optional

# from google import genai

# from audio_utils import upsample_8k_to_16k, downsample_24k_to_8k

# from config import (
#     GEMINI_API_KEY,
#     GEMINI_MODEL,
#     GEMINI_VOICE,
#     USE_VERTEX_AI,
#     VERTEX_PROJECT_ID,
#     VERTEX_LOCATION,
#     GOOGLE_APPLICATION_CREDENTIALS,
#     AGENT_NAME,
#     COMPANY_NAME,
#     AGENT_LANGUAGE,
# )

# from prompts import build_system_prompt, PromptType

# from extractor import extract_from_chunk
# from lead_info import LeadInfo, upsert as upsert_info

# logger = logging.getLogger(__name__)

# _OUTPUT_QUEUE_MAXSIZE = 100


# class GeminiBridge:
#     def __init__(
#         self,
#         call_sid: str,
#         outbound_intro: Optional[str] = None,
#         prompt_type: "PromptType" = "sales",
#         org_config: Optional[dict] = None,
#         # ✅ Keep these for internal DB tracking only — never passed to prompt
#         lead_id: str = "",
#         initial_info: Optional[LeadInfo] = None,
#     ):

#         self.call_sid = call_sid
#         self.lead_id = lead_id          # internal tracking only
#         self.outbound_intro = outbound_intro
#         self.prompt_type = prompt_type
#         self.org_config = org_config

#         self.collected_info: LeadInfo = (
#             initial_info or LeadInfo(lead_id=lead_id)
#         )

#         # Gemini Client
#         if USE_VERTEX_AI:

#             if GOOGLE_APPLICATION_CREDENTIALS:
#                 import os
#                 os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

#             self._client = genai.Client(
#                 vertexai=True,
#                 project=VERTEX_PROJECT_ID,
#                 location=VERTEX_LOCATION
#             )

#             logger.info(f"[{call_sid}] Using Vertex AI")

#         else:

#             self._client = genai.Client(
#                 api_key=GEMINI_API_KEY,
#                 http_options={"api_version": "v1beta"},
#             )

#             logger.info(f"[{call_sid}] Using Gemini API Key")

#         self._session = None
#         self._task = None

#         self.output_queue: asyncio.Queue[
#             Optional[bytes]
#         ] = asyncio.Queue(maxsize=_OUTPUT_QUEUE_MAXSIZE)

#         self._active = False
#         self.transcript_parts: list[str] = []
#         self.on_hangup: Optional[asyncio.Event] = asyncio.Event()

#     async def start(self, send_greeting: bool = True):

#         # ✅ Single clean prompt — no lead/test distinction
#         system_prompt = build_system_prompt(
#             prompt_type=self.prompt_type,
#             org_config=self.org_config,
#         )

#         _types = genai.types

#         config = _types.LiveConnectConfig(
#             response_modalities=["AUDIO"],

#             system_instruction=_types.Content(
#                 role="user",
#                 parts=[_types.Part(text=system_prompt)],
#             ),

#             speech_config=_types.SpeechConfig(
#                 voice_config=_types.VoiceConfig(
#                     prebuilt_voice_config=_types.PrebuiltVoiceConfig(
#                         voice_name=GEMINI_VOICE
#                     )
#                 ),
#                 language_code=AGENT_LANGUAGE,
#             ),

#             output_audio_transcription=_types.AudioTranscriptionConfig(),
#             input_audio_transcription=_types.AudioTranscriptionConfig(),
#         )

#         self._ctx = self._client.aio.live.connect(
#             model=GEMINI_MODEL,
#             config=config,
#         )

#         self._session = await self._ctx.__aenter__()
#         self._active = True

#         logger.info(f"[{self.call_sid}] Gemini session opened.")

#         self._task = asyncio.create_task(self._receive_loop())

#         if send_greeting:

#             if self.outbound_intro:
#                 msg = (
#                     f'(Start the call. Say exactly and only: '
#                     f'"{self.outbound_intro}")'
#                 )
#             else:
#                 msg = '(Start the call. Say exactly and only: "Hello.")'

#             await self._session.send_realtime_input(text=msg)

#     async def stop(self):

#         self._active = False

#         try:
#             self.output_queue.put_nowait(None)
#         except asyncio.QueueFull:
#             pass

#         if self._task:
#             self._task.cancel()
#             try:
#                 await self._task
#             except asyncio.CancelledError:
#                 pass

#         if self._session:
#             try:
#                 await self._ctx.__aexit__(None, None, None)
#             except Exception:
#                 pass

#         logger.info(f"[{self.call_sid}] Gemini session closed.")

#     async def send_audio(self, pcm_8k: bytes):

#         if not self._active or not self._session:
#             return

#         pcm_16k = await upsample_8k_to_16k(pcm_8k)

#         await self._session.send_realtime_input(
#             audio=genai.types.Blob(
#                 data=pcm_16k,
#                 mime_type="audio/pcm;rate=16000"
#             )
#         )

#     async def _receive_loop(self):

#         try:

#             while self._active:

#                 turn = self._session.receive()

#                 async for response in turn:

#                     if not self._active:
#                         break

#                     if response.data:

#                         raw_pcm = response.data

#                         if isinstance(raw_pcm, str):
#                             raw_pcm = base64.b64decode(raw_pcm)

#                         pcm_8k = await downsample_24k_to_8k(bytes(raw_pcm))

#                         try:
#                             self.output_queue.put_nowait(pcm_8k)
#                         except asyncio.QueueFull:
#                             logger.warning("Audio queue full")

#                     if response.text:

#                         text = response.text
#                         logger.info(f"[{self.call_sid}] Agent: {text}")
#                         self.transcript_parts.append(f"{AGENT_NAME}: {text}")

#                         # ✅ Extract & save info internally (no prompt leakage)
#                         chunk_info = await extract_from_chunk(text)
#                         if chunk_info:
#                             self._merge_info(chunk_info)
#                             upsert_info(self.collected_info)

#         except asyncio.CancelledError:
#             pass

#         except Exception as e:
#             logger.error(
#                 f"[{self.call_sid}] Gemini receive error: {e}",
#                 exc_info=True
#             )

#         finally:
#             try:
#                 self.output_queue.put_nowait(None)
#             except asyncio.QueueFull:
#                 pass

#     def full_transcript(self) -> str:
#         return " ".join(self.transcript_parts)

#     def _merge_info(self, chunk: LeadInfo):

#         info = self.collected_info

#         if chunk.budget_min is not None:
#             info.budget_min = chunk.budget_min
#         if chunk.budget_max is not None:
#             info.budget_max = chunk.budget_max
#         if chunk.location is not None:
#             info.location = chunk.location
#         if chunk.timeline is not None:
#             info.timeline = chunk.timeline
#         if chunk.property_type is not None:
#             info.property_type = chunk.property_type
#         if chunk.bhk is not None:
#             info.bhk = chunk.bhk
#         if chunk.team_size is not None:
#             info.team_size = chunk.team_size
#         if chunk.current_crm is not None:
#             info.current_crm = chunk.current_crm
#         if chunk.callback_time is not None:
#             info.callback_time = chunk.callback_time
#         if chunk.demo_requested:
#             info.demo_requested = True
"""
GeminiBridge -- manages a single Gemini Live API session for one phone call.
"""

import asyncio
import base64
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from google import genai

from audio_utils import StreamResampler, resample_stream_async

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_VOICE,
    USE_VERTEX_AI,
    VERTEX_PROJECT_ID,
    VERTEX_LOCATION,
    GOOGLE_APPLICATION_CREDENTIALS,
    AGENT_NAME,
    COMPANY_NAME,
    AGENT_LANGUAGE,
)

from prompts import build_system_prompt, PromptType
from school_extractor import extract_from_chunk, grade_to_code
from enquiry_info import EnquiryInfo, upsert as upsert_info

logger = logging.getLogger(__name__)

_OUTPUT_QUEUE_MAXSIZE = 100

# 8kHz, 16-bit mono PCM => 16000 bytes/sec => 16 bytes/ms
_PCM_8K_BYTES_PER_MS = 16.0


_CALL_ENDING_PHRASES = [
    "thank you for your time",
    "reach out to us anytime",
    "please do reach out",
    "aapke time ke liye dhanyawad",
    "humse contact kar sakte hain",
]
_TRANSFER_PHRASES = [
    "transferring your call",
    "i am transferring your call",
    "i am connecting you with our",
    "connecting you with our admissions",
    "connecting you with the right team",
    "call transfer kar rahi hoon",
    "right team se connect kar rahi hoon",
]


class GeminiBridge:
    def __init__(
        self,
        call_sid: str,
        outbound_intro: Optional[str] = None,
        prompt_type: "PromptType" = "sales",
        org_config: Optional[dict] = None,
        lead_id: str = "",
        initial_info: Optional[EnquiryInfo] = None,
    ):

        self.call_sid = call_sid
        self.lead_id = lead_id         
        self.outbound_intro = outbound_intro
        self.prompt_type = prompt_type
        self.org_config = org_config
        self.collected_info: EnquiryInfo = (
            initial_info or EnquiryInfo(lead_id=lead_id or call_sid)
        )

        # --- Stateful resamplers, one per direction, reused for the
        # entire lifetime of this call. Creating a fresh audioop state
        # on every chunk (the old behaviour) causes an audible click at
        # every chunk boundary, which on a real streaming call (chunks
        # every ~20-100ms) sounds like continuous background crackling.
        self._upsampler = StreamResampler(from_rate=8000, to_rate=16000)
        self._downsampler = StreamResampler(from_rate=24000, to_rate=8000)

        # Gemini Client
        if USE_VERTEX_AI:

            if GOOGLE_APPLICATION_CREDENTIALS:
                import os
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

            self._client = genai.Client(
                vertexai=True,
                project=VERTEX_PROJECT_ID,
                location=VERTEX_LOCATION
            )

            logger.info(f"[{call_sid}] Using Vertex AI")

        else:

            self._client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options={"api_version": "v1beta"},
            )

            logger.info(f"[{call_sid}] Using Gemini API Key")

        self._session = None
        self._task = None

        self.output_queue: asyncio.Queue[
            Optional[bytes]
        ] = asyncio.Queue(maxsize=_OUTPUT_QUEUE_MAXSIZE)

        self._active = False
        self.transcript_parts: list[str] = []

        # structured, turn-by-turn transcript. Each entry:
        #   {"speaker": "agent" | "caller", "text": str, "timestamp": datetime}
        self.transcript_turns: list[dict] = []

        self.on_hangup: Optional[asyncio.Event] = asyncio.Event()
        self._last_speech_time: float = time.monotonic()
        self.call_should_end: bool = False
        # Guard: don't allow call to end until the caller has spoken at least once
        self._caller_has_spoken: bool = False

        # read by ws_call_handler for the SchoolKnot API 2 /
        # insert_enquiry_service(r_type=4) transfer hook.
        self.transfer_requested: bool = False
        self.transfer_reason: str = ""
        self._transfer_destination: str = ""
        self._interrupted_flag: bool = False

        self._speech_generation: int = 0

        # --- Playback-position tracking ---
        # Wall-clock time the CURRENT agent response started playing out
        # (i.e. when the first audio chunk of this response was queued).
        # Used to estimate how much of the response the caller actually
        # heard before an interruption, instead of relying on the
        # queue-drain count (which only reflects *unsent* chunks and is
        # frequently 0 even when the caller clearly barged in mid-sentence).
        self._response_started_at: Optional[float] = None
        # Total duration (ms) of audio queued for the current response so far.
        self._audio_ms_sent: float = 0.0

    def _append_turn(self, speaker: str, text: str):
        """Appends one turn to the structured transcript, merging
        into the previous entry if it's from the same speaker back-to-back
        (mirrors the merge behaviour transcript_parts already does for
        consecutive caller chunks)."""
        if not text:
            return
        if self.transcript_turns and self.transcript_turns[-1]["speaker"] == speaker:
            self.transcript_turns[-1]["text"] += text
        else:
            self.transcript_turns.append({
                "speaker": speaker,
                "text": text,
                "timestamp": datetime.now(timezone.utc),
            })

    async def start(self, send_greeting: bool = True):
        system_prompt = build_system_prompt(
            prompt_type=self.prompt_type,
            org_config=self.org_config,
        )

        # FIX: capture_enquiry_info's callback_time field needs to come
        # back as an absolute 'YYYY-MM-DD HH:MM:SS' string so it can be
        # sent straight through to SchoolKnot's schedule_walkin_date /
        # follow_up_date fields. The model can only resolve relative
        # terms like "Friday" or "tomorrow 5pm" into an actual date if
        # it knows what "today" is — build_system_prompt() has no way to
        # know that on its own, so inject it here, right before the
        # session is opened, using the real current date for this call.
        today = datetime.now()
        date_context = (
            f"\n\nToday's date and time is {today.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({today.strftime('%A')}). Whenever you call capture_enquiry_info with "
            f"a callback_time, resolve any relative day/time the caller gives "
            f"(e.g. 'tomorrow', 'Friday', 'next Monday 11am', 'kal', 'parso') "
            f"against this date and report it as an absolute value in the exact "
            f"format 'YYYY-MM-DD HH:MM:SS'. If the caller gave no specific time, "
            f"default to 11:00:00."
        )
        system_prompt = system_prompt + date_context

        _types = genai.types

        end_call_tool = _types.Tool(
            function_declarations=[
                _types.FunctionDeclaration(
                    name="end_call",
                    description=(
                        "End the phone call. Call this exactly once after "
                        "speaking the closing line, when the conversation is "
                        "fully complete or the caller has asked to disconnect."
                    ),
                    parameters=_types.Schema(
                        type="OBJECT",
                        properties={
                            "reason": _types.Schema(
                                type="STRING",
                                description=(
                                    "Short reason code, e.g. 'call_completed', "
                                    "'caller_said_bye', 'caller_requested_disconnect'."
                                ),
                            )
                        },
                        required=[],
                    ),
                ),
                _types.FunctionDeclaration(
                    name="transfer_call",
                    description=(
                        "Transfer the call to a human representative. "
                        "Speak one short handoff line first, then call this tool. "
                        "Do NOT call end_call after this — the transfer ends the AI leg."
                    ),
                    parameters=_types.Schema(
                        type="OBJECT",
                        properties={
                            "destination": _types.Schema(
                                type="STRING",
                                description="The phone number to transfer to, e.g. '9550335589'.",
                            ),
                            "reason": _types.Schema(
                                type="STRING",
                                description=(
                                    "Short reason code, e.g. 'admissions_enquiry', "
                                    "'fee_discussion', 'safety_concern', 'complaint'."
                                ),
                            ),
                        },
                        required=["destination"],
                    ),
                ),
                # ── NEW: capture_enquiry_info ──────────────────────────
                # WHY THIS TOOL EXISTS:
                # The old pipeline extracted child_name / father_name /
                # dob / grade etc. purely with regex over the caller's
                # ASR transcript (school_extractor.py). That regex only
                # matches Latin-script text ([A-Z][a-zA-Z]+...). Gemini's
                # input_audio_transcription does NOT reliably transcribe
                # every call in the same script — a Hindi/Hinglish caller
                # can come back as Devanagari ("राहुल"), Latin ("Rahul"),
                # or mixed, and this varies turn-to-turn, not just
                # call-to-call. Whenever the transcript came back in
                # Devanagari, the regex silently found nothing and the
                # field stayed None — even though the caller clearly said
                # it and the agent's own next line proved it "heard" the
                # name.
                #
                # Rather than trying to keep extending the regex to cover
                # every script/spelling permutation (a losing battle),
                # the model itself — which already understands the
                # conversation regardless of script/language — now
                # reports each field directly via this tool the moment
                # the caller states it. This is fully script-independent:
                # the model can hear "राहुल", "Rahul", or "rahul" and
                # report the same normalized value.
                #
                # The regex extractor (school_extractor.py) is NOT
                # removed — it still runs on every caller chunk as a
                # fallback/safety net. Both write into the same
                # EnquiryInfo via the same COALESCE-style _merge_info(),
                # so whichever source captures a field first "wins" and
                # neither can overwrite an already-known value with None.
                _types.FunctionDeclaration(
                    name="capture_enquiry_info",
                    description=(
                        "Report any admission-enquiry detail the caller has just stated, "
                        "in English/Latin script regardless of what script or language the "
                        "caller actually spoke in (e.g. if the caller says the child's name "
                        "in Hindi or Devanagari, transliterate it into a normal Latin-script "
                        "name here). Call this IMMEDIATELY every time the caller gives a new "
                        "piece of information — do not wait until the end of the call, and do "
                        "not batch multiple turns together. Only include the field(s) that "
                        "were just stated in this turn; omit everything else. Never guess or "
                        "fill in a field the caller has not actually said."
                    ),
                    parameters=_types.Schema(
                        type="OBJECT",
                        properties={
                            "child_name": _types.Schema(
                                type="STRING",
                                description="The student/child's name, transliterated into Latin script.",
                            ),
                            "father_name": _types.Schema(
                                type="STRING",
                                description="Father's name, transliterated into Latin script.",
                            ),
                            "mother_name": _types.Schema(
                                type="STRING",
                                description="Mother's name, transliterated into Latin script.",
                            ),
                            "dob": _types.Schema(
                                type="STRING",
                                description="Child's date of birth in YYYY-MM-DD format.",
                            ),
                            "grade": _types.Schema(
                                type="STRING",
                                description=(
                                    "Grade/class the child is being enrolled for, e.g. "
                                    "'Nursery', 'LKG', 'UKG', '1', '2', ... '12'."
                                ),
                            ),
                            "email": _types.Schema(
                                type="STRING",
                                description="Parent's email address, if given.",
                            ),
                            "mother_mobile": _types.Schema(
                                type="STRING",
                                description="Mother's mobile number, if given separately from caller ID.",
                            ),
                            "branch": _types.Schema(
                                type="STRING",
                                description="School branch/location the caller wants, e.g. 'Attapur', 'Katedan', if mentioned.",
                            ),
                            # FIX: previously described as a free-form
                            # example ("e.g. 'tomorrow 5pm'"), which is
                            # exactly what the model reported back verbatim
                            # — "tomorrow 5pm" / "Friday" / etc. That raw
                            # string then flowed straight into
                            # schedule_walkin_date / follow_up_date in
                            # ws_call_handler._build_insert_enquiry_blocks()
                            # with no conversion, so SchoolKnot either
                            # rejected it or silently stored nothing
                            # useful. Now explicitly require the absolute
                            # 'YYYY-MM-DD HH:MM:SS' format, resolved
                            # against the "today's date" context injected
                            # into the system prompt above.
                            "callback_time": _types.Schema(
                                type="STRING",
                                description=(
                                    "The requested callback or campus-visit date and time, "
                                    "resolved to an ABSOLUTE value in the exact format "
                                    "'YYYY-MM-DD HH:MM:SS'. Convert whatever relative day/time "
                                    "the caller gave (e.g. 'Friday', 'tomorrow 5pm', 'kal', "
                                    "'next Monday morning') using today's date from the system "
                                    "instructions. If the caller gave a day but no time, use "
                                    "11:00:00. Never report a relative phrase like 'Friday' or "
                                    "'tomorrow' directly — always convert it first. "
                                    "Example: today is 2026-08-24 (Monday) and caller says "
                                    "'Friday around 11' -> '2026-08-28 11:00:00'."
                                ),
                            ),
                            "visit_requested": _types.Schema(
                                type="BOOLEAN",
                                description="True if the caller asked to visit the campus / a walk-in.",
                            ),
                        },
                        required=[],
                    ),
                ),
            ]
        )

        config = _types.LiveConnectConfig(
            response_modalities=["AUDIO"],

            tools=[end_call_tool],

            system_instruction=_types.Content(
                role="user",
                parts=[_types.Part(text=system_prompt)],
            ),

            speech_config=_types.SpeechConfig(
                voice_config=_types.VoiceConfig(
                    prebuilt_voice_config=_types.PrebuiltVoiceConfig(
                        voice_name=GEMINI_VOICE
                    )
                ),
                language_code=AGENT_LANGUAGE,
            ),

            output_audio_transcription=_types.AudioTranscriptionConfig(),
            input_audio_transcription=_types.AudioTranscriptionConfig(),

            # Explicitly enable automatic VAD-based interruption
            # detection on Gemini's side. This is what makes Gemini emit
            # server_content.interrupted when the caller barges in while
            # the agent is still speaking. Some SDK versions default this
            # to on already, but setting it explicitly avoids silently
            # losing barge-in detection if a library upgrade changes the
            # default.
            realtime_input_config=_types.RealtimeInputConfig(
                automatic_activity_detection=_types.AutomaticActivityDetection(
                    disabled=False,
                ),
            ),
        )

        self._ctx = self._client.aio.live.connect(
            model=GEMINI_MODEL,
            config=config,
        )

        self._session = await self._ctx.__aenter__()
        self._active = True

        logger.info(f"[{self.call_sid}] Gemini session opened.")

        self._task = asyncio.create_task(self._receive_loop())

        if send_greeting:

            if self.outbound_intro:
                msg = (
                    f'(Start the call. Say exactly and only: '
                    f'"{self.outbound_intro}")'
                )
            else:
                msg = '(Start the call. Say exactly and only: "Hello.")'

            await self._session.send_realtime_input(text=msg)

    async def stop(self):

        self._active = False

        try:
            self.output_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._session:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception:
                pass

        logger.info(f"[{self.call_sid}] Gemini session closed.")

    async def send_audio(self, pcm_8k: bytes):

        if not self._active or not self._session:
            return

        self._caller_has_spoken = True  # caller has sent audio — safe to end later
        self._last_speech_time = time.monotonic()

        pcm_16k = await resample_stream_async(self._upsampler, pcm_8k)

        await self._session.send_realtime_input(
            audio=genai.types.Blob(
                data=pcm_16k,
                mime_type="audio/pcm;rate=16000"
            )
        )

    def seconds_since_speech(self) -> float:
        """Used by ws_call_handler._silence_watcher() to end the
        call after a period of caller silence."""
        return time.monotonic() - self._last_speech_time

    @staticmethod
    def _chunk_duration_ms(pcm_8k: bytes) -> float:
        """Duration in ms of an 8kHz, 16-bit mono PCM chunk."""
        return len(pcm_8k) / _PCM_8K_BYTES_PER_MS

    def _handle_interruption(self):

        self._speech_generation += 1

        # --- Estimate how much of the current response the caller
        # actually heard, based on wall-clock elapsed time since the
        # response started playing, capped at how much audio we'd
        # actually queued (we can't have played more than we sent).
        played_ms = 0.0
        if self._response_started_at is not None:
            elapsed_ms = (time.monotonic() - self._response_started_at) * 1000
            played_ms = min(elapsed_ms, self._audio_ms_sent)

        drained = 0
        while True:
            try:
                self.output_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break

        self._interrupted_flag = True

        # The response that was just cut off is being discarded entirely —
        # its resampler filter state no longer corresponds to anything
        # we're going to play. Reset it so the NEXT response's downsampling
        # starts clean instead of dragging in leftover state from audio
        # that will never be heard.
        self._downsampler.reset()

        logger.info(
            f"[{self.call_sid}] Interruption handled — caller likely heard "
            f"~{played_ms:.0f}ms of agent audio ({self._audio_ms_sent:.0f}ms "
            f"was queued), drained {drained} unsent chunk(s), generation now "
            f"{self._speech_generation}."
        )

        # Reset playback tracking — the next response (if any) starts fresh.
        self._response_started_at = None
        self._audio_ms_sent = 0.0

    async def _receive_loop(self):

        try:

            while self._active:

                turn = self._session.receive()

                # Capture which "generation" this turn belongs to. If an
                # interruption bumps the generation counter while we're
                # mid-turn, any further chunks from *this* turn are stale
                # and must be dropped instead of queued.
                turn_generation = self._speech_generation

                # accumulate this turn's agent text and only run
                # the closing/transfer phrase check ONCE, on the FULL
                # utterance, after the turn is complete. Checking on every
                # individual streamed chunk (the old behaviour) could
                # false-fire on a phrase split across two chunks, or match
                # too early before the agent had actually finished the
                # thought — which is very likely what was causing calls to
                # be cut off mid-conversation.
                turn_text_parts: list[str] = []

                async for response in turn:

                    if not self._active:
                        break

                    # handle caller barge-in / interruption.
                    # Gemini sets server_content.interrupted = True the
                    # moment its VAD detects the caller started speaking
                    # while the agent's audio was still playing out.
                    sc = getattr(response, "server_content", None)
                    if sc and getattr(sc, "interrupted", False):
                        logger.info(
                            f"[{self.call_sid}] Caller interrupted the agent — "
                            f"clearing pending audio."
                        )
                        self._handle_interruption()

                        # 🔧 FIX: break out of THIS turn's async-for instead
                        # of trying to keep consuming it with a stale-
                        # generation check on every subsequent chunks.
                        #
                        # Previously we relied purely on
                        # `turn_generation != self._speech_generation` to
                        # drop stale audio/text for the rest of this turn.
                        # That's correct for *trailing/buffered* audio from
                        # the interrupted response — but if Gemini's SDK
                        # ever continues streaming a genuinely NEW response
                        # (e.g. answering the caller's new question) inside
                        # this same `turn` async-generator, that new content
                        # would ALSO get silently dropped, because
                        # turn_generation was captured before the bump and
                        # never gets resynced.
                        #
                        # Breaking here ends this turn's iteration
                        # immediately. The outer `while self._active` loop
                        # then calls `self._session.receive()` again,
                        # starting a brand new turn whose `turn_generation`
                        # is captured fresh (== the post-bump value), so any
                        # real new response is no longer misclassified as
                        # stale.
                        break

                    if response.data:

                        # Stale turn — an interruption happened after this
                        # turn started, so this audio must not be sent.
                        if turn_generation != self._speech_generation:
                            continue

                        raw_pcm = response.data

                        if isinstance(raw_pcm, str):
                            raw_pcm = base64.b64decode(raw_pcm)

                        pcm_8k = await resample_stream_async(
                            self._downsampler, bytes(raw_pcm)
                        )

                        # Playback tracking: mark when this response's audio
                        # started, and accumulate how much we've queued.
                        if self._response_started_at is None:
                            self._response_started_at = time.monotonic()
                        self._audio_ms_sent += self._chunk_duration_ms(pcm_8k)

                        try:
                            self.output_queue.put_nowait(pcm_8k)
                        except asyncio.QueueFull:
                            logger.warning("Audio queue full")

                    if response.text:

                        text = response.text
                        logger.info(f"[{self.call_sid}] Agent: {text}")
                        self.transcript_parts.append(f"{AGENT_NAME}: {text}")
                        turn_text_parts.append(text)
                        self._append_turn("agent", text)

                        # NOTE: we intentionally do NOT run
                        # extract_from_chunk() on the agent's own text.
                        # The agent mostly asks questions ("What's your
                        # child's name?"); the actual answers (name, grade,
                        # DOB, etc.) come from the CALLER, and are extracted
                        # below from input_transcription instead. Running
                        # extraction here too is harmless but rarely finds
                        # anything, since the agent doesn't usually restate
                        # facts back verbatim.

                    # Check server_content for both input and output transcription
                    if sc:
                        # Output transcription — agent's spoken closing words
                        ot = getattr(sc, "output_transcription", None)
                        if ot:
                            agent_text = (ot.text or "").strip().lower()
                            if agent_text and self._caller_has_spoken and not self.call_should_end:
                                if any(p in agent_text for p in _CALL_ENDING_PHRASES):
                                    logger.info(
                                        f"[{self.call_sid}] Closing phrase in output_transcription "
                                        f"({agent_text!r}) — ending call."
                                    )
                                    self.call_should_end = True

                        # Input transcription — caller's spoken words
                        it = getattr(sc, "input_transcription", None)
                        if it:
                            caller_text = (it.text or "").strip()
                            if caller_text:
                                logger.info(f"[{self.call_sid}] Caller: {caller_text}")
                                if (
                                    self.transcript_parts
                                    and self.transcript_parts[-1].startswith("Customer:")
                                ):
                                    self.transcript_parts[-1] += caller_text
                                else:
                                    self.transcript_parts.append(f"Customer:{caller_text}")
                                self._append_turn("caller", caller_text)

                                # FALLBACK / safety-net extraction: structured
                                # admission info (ward name, grade, DOB, etc.)
                                # from what the CALLER said via regex. This is
                                # NOT the primary path anymore — it only
                                # catches fields the LLM's capture_enquiry_info
                                # tool call (below, in the tool_call handling
                                # block) misses. _merge_info() is COALESCE-
                                # style, so whichever source (LLM tool call or
                                # this regex) reports a field FIRST wins, and
                                # neither can blank out a value the other
                                # already captured. Kept because it's script-
                                # independent-input-agnostic in the sense that
                                # it costs nothing extra and adds resilience
                                # if the LLM ever skips calling the tool for a
                                # turn (e.g. mid-interruption).
                                chunk_info = extract_from_chunk(self.call_sid, caller_text)
                                if chunk_info:
                                    self._merge_info(chunk_info)
                                    upsert_info(self.collected_info)

                                caller_closing = [
                                    "thank you", "thanks", "bye", "ok bye",
                                    "goodbye", "dhanyawad", "shukriya",
                                    "alvida", "that's all", "thats all",
                                ]
                                lowered_caller = caller_text.lower()
                                if (
                                    self._caller_has_spoken
                                    and not self.call_should_end
                                    and any(p in lowered_caller for p in caller_closing)
                                ):
                                    logger.info(
                                        f"[{self.call_sid}] Caller closing phrase detected "
                                        f"({caller_text!r}) — ending call in 2s."
                                    )

                                    async def _delayed_caller_hangup():
                                        await asyncio.sleep(2)
                                        if not self.call_should_end:
                                            self.call_should_end = True

                                    asyncio.create_task(_delayed_caller_hangup())

                    # Handle end_call / transfer_call / capture_enquiry_info
                    # tool invocations from Gemini
                    if response.tool_call:
                        for fn in response.tool_call.function_calls:

                            if fn.name == "end_call":
                                reason = (fn.args or {}).get("reason", "call_completed")
                                if self._caller_has_spoken:
                                    logger.info(
                                        f"[{self.call_sid}] end_call tool invoked "
                                        f"(reason={reason!r}) — setting call_should_end."
                                    )
                                    self.call_should_end = True
                                else:
                                    logger.warning(
                                        f"[{self.call_sid}] end_call invoked before caller spoke "
                                        f"— ignoring (too early)."
                                    )
                                try:
                                    await self._session.send_tool_response(
                                        function_responses=[
                                            genai.types.FunctionResponse(
                                                name="end_call",
                                                id=fn.id,
                                                response={"result": "ok"},
                                            )
                                        ]
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"[{self.call_sid}] Could not send end_call tool response: {e}"
                                    )

                            elif fn.name == "transfer_call":
                                destination = (fn.args or {}).get("destination", "")
                                reason = (fn.args or {}).get("reason", "transfer_requested")
                                logger.info(
                                    f"[{self.call_sid}] transfer_call tool invoked "
                                    f"(destination={destination!r}, reason={reason!r})."
                                )
                                self.transfer_requested = True
                                self.transfer_reason = reason
                                self._transfer_destination = destination
                                try:
                                    await self._session.send_tool_response(
                                        function_responses=[
                                            genai.types.FunctionResponse(
                                                name="transfer_call",
                                                id=fn.id,
                                                response={"result": "transferring"},
                                            )
                                        ]
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"[{self.call_sid}] Could not send transfer_call tool response: {e}"
                                    )

                            # ── NEW: capture_enquiry_info handling ──────
                            # This is the PRIMARY path for filling
                            # collected_info now. Script/language-
                            # independent by construction — the model
                            # reports whatever it understood, already
                            # normalized to Latin script, regardless of
                            # what script the caller's speech was
                            # transcribed in.
                            elif fn.name == "capture_enquiry_info":
                                args = fn.args or {}
                                logger.info(
                                    f"[{self.call_sid}] capture_enquiry_info tool "
                                    f"invoked — args={args}"
                                )

                                # FIX: the raw grade string the LLM reports
                                # (e.g. "11" for "Class 11") is NOT the
                                # SchoolKnot admission_opted_for code —
                                # SchoolKnot's codes don't line up 1:1 with
                                # the class number (code 11 = Class 7,
                                # code 15 = Class 11; see the doc's
                                # "Admission opted for" table). Previously
                                # this raw value was sent straight through,
                                # silently storing the wrong grade for every
                                # enquiry captured via this (primary) path.
                                # Route it through the same grade_to_code()
                                # mapping the regex fallback in
                                # school_extractor.py already used, so both
                                # paths always produce the identical,
                                # correct SchoolKnot code.
                                raw_grade = args.get("grade") or None
                                grade_code = grade_to_code(raw_grade)
                                if raw_grade and grade_code is None:
                                    logger.warning(
                                        f"[{self.call_sid}] capture_enquiry_info "
                                        f"reported grade {raw_grade!r} but it did "
                                        f"not match any known SchoolKnot grade — "
                                        f"leaving admission_opted_for unset rather "
                                        f"than sending a possibly-wrong code."
                                    )

                                # FIX: normalize callback_time as a
                                # safety net even though the prompt/schema
                                # now asks the model for an absolute
                                # 'YYYY-MM-DD HH:MM:SS' value. If the model
                                # still reports something relative (e.g.
                                # "Friday") or malformed, this converts it
                                # before it ever reaches collected_info /
                                # ws_call_handler, instead of relying on
                                # ws_call_handler to catch it later.
                                raw_callback_time = args.get("callback_time") or None
                                normalized_callback_time = _normalize_callback_time(
                                    raw_callback_time, self.call_sid
                                )

                                visit_val = args.get("visit_requested")
                                chunk_info = EnquiryInfo(
                                    lead_id=self.call_sid,
                                    child_name=(args.get("child_name") or None),
                                    father_name=(args.get("father_name") or None),
                                    mother_name=(args.get("mother_name") or None),
                                    dob=(args.get("dob") or None),
                                    admission_opted_for=grade_code,
                                    email=(args.get("email") or None),
                                    mother_mobile=(args.get("mother_mobile") or None),
                                    branch_name=(args.get("branch") or None),
                                    callback_time=normalized_callback_time,
                                    visit_requested=bool(visit_val) if visit_val is not None else False,
                                )

                                self._merge_info(chunk_info)
                                upsert_info(self.collected_info)

                                logger.info(
                                    f"[{self.call_sid}] collected_info after "
                                    f"capture_enquiry_info merge: {vars(self.collected_info)}"
                                )

                                try:
                                    await self._session.send_tool_response(
                                        function_responses=[
                                            genai.types.FunctionResponse(
                                                name="capture_enquiry_info",
                                                id=fn.id,
                                                response={"result": "ok"},
                                            )
                                        ]
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"[{self.call_sid}] Could not send "
                                        f"capture_enquiry_info tool response: {e}"
                                    )

                # --- Turn complete: reset playback tracking for the next
                # response (only if we didn't just break out due to an
                # interruption, which already reset it inside
                # _handle_interruption()). This covers the normal case
                # where the agent finished speaking without being cut off.
                self._response_started_at = None
                self._audio_ms_sent = 0.0

                # --- Turn complete: evaluate the FULL utterance now ---
                full_turn_text = "".join(turn_text_parts).lower()

                if full_turn_text:

                    if self._caller_has_spoken and not self.transfer_requested and any(
                        p in full_turn_text for p in _TRANSFER_PHRASES
                    ):
                        self.transfer_requested = True
                        self.transfer_reason = "ai_initiated_transfer"
                        logger.info(
                            f"[{self.call_sid}] Transfer intent detected in AI speech."
                        )

                    if self._caller_has_spoken and not self.call_should_end and any(
                        p in full_turn_text for p in _CALL_ENDING_PHRASES
                    ):
                        self.call_should_end = True
                        logger.info(
                            f"[{self.call_sid}] Call-ending phrase detected in AI speech "
                            f"(full turn, not a partial chunk match)."
                        )

        except asyncio.CancelledError:
            pass

        except Exception as e:
            logger.error(
                f"[{self.call_sid}] Gemini receive error: {e}",
                exc_info=True
            )

        finally:
            try:
                self.output_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    def full_transcript(self) -> str:
        return " ".join(self.transcript_parts)

    def structured_transcript(self) -> list[dict]:
        """Turn-by-turn transcript for storage (e.g. MongoDB).
        Each item: {"speaker": "agent"|"caller", "text": str, "timestamp": datetime}.
        """
        return self.transcript_turns

    def _merge_info(self, chunk: EnquiryInfo):
        """Merges school-admission fields. Mirrors the
        same COALESCE-style merge enquiry_info.upsert() also does; kept
        here too so self.collected_info reflects the merge immediately
        within this call, without waiting on the (possibly swapped-out)
        storage layer in upsert_info().

        Called from BOTH sources now:
          - the LLM's capture_enquiry_info tool call (primary)
          - the regex extractor in school_extractor.py (fallback)
        Since this only ever fills a field that is currently None (never
        overwrites an existing value with None), it's safe for both
        sources to call this on the same collected_info without one
        clobbering the other.
        """

        info = self.collected_info

        if chunk.child_name is not None:
            info.child_name = chunk.child_name
        if chunk.father_name is not None:
            info.father_name = chunk.father_name
        if chunk.mother_name is not None:
            info.mother_name = chunk.mother_name
        if chunk.dob is not None:
            info.dob = chunk.dob
        if chunk.admission_opted_for is not None:
            info.admission_opted_for = chunk.admission_opted_for
        if chunk.email is not None:
            info.email = chunk.email
        if chunk.mother_mobile is not None:
            info.mother_mobile = chunk.mother_mobile
        if chunk.branch_name is not None:
            info.branch_name = chunk.branch_name
        if chunk.callback_time is not None:
            info.callback_time = chunk.callback_time
        if chunk.visit_requested:
            info.visit_requested = True

        for r in chunk.requests:
            if r not in info.requests:
                info.requests.append(r)

        for t in chunk.tertiary_signals:
            if t not in info.tertiary_signals:
                info.tertiary_signals.append(t)


def _normalize_callback_time(raw: Optional[str], call_sid: str) -> Optional[str]:
    if not raw:
        return None
    try:
        from dateutil import parser as dtparser
        dt = dtparser.parse(raw, fuzzy=True, default=datetime.now())
        normalized = dt.strftime("%Y-%m-%d %H:%M:%S")
        if normalized != raw:
            logger.info(
                f"[{call_sid}] Normalized callback_time {raw!r} -> {normalized!r}"
            )
        return normalized
    except Exception as e:
        logger.warning(
            f"[{call_sid}] Could not parse callback_time={raw!r} "
            f"({e}) — leaving as-is so it isn't silently lost; "
            f"downstream SchoolKnot insert may reject/ignore it."
        )
        return raw