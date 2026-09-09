"""
LiveKitCallHandler — manages one LiveKit room session for voice calls.

This replaces the Exotel WebSocket handler with LiveKit's real-time
communication infrastructure, providing better scalability and features.
"""
import asyncio
import logging
from typing import Optional
from livekit import rtc, api
from audio_utils import upsample_8k_to_16k, downsample_24k_to_8k
from gemini_bridge import GeminiBridge
from config import LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL

logger = logging.getLogger(__name__)


class LiveKitCallHandler:
    def __init__(
        self,
        room_name: str,
        participant_identity: str,
        lead_id: str = "",
        lead_name: str = "there",
        lead_company: str = "",
        call_context: str = "",
        outbound_intro: Optional[str] = None,
        initial_info=None,
        on_call_end=None,
    ):
        self.room_name = room_name
        self.participant_identity = participant_identity
        self.lead_id = lead_id
        self.lead_name = lead_name
        self.lead_company = lead_company
        self.call_context = call_context
        self.outbound_intro = outbound_intro
        self.initial_info = initial_info
        self.on_call_end = on_call_end

        self.room: Optional[rtc.Room] = None
        self.bridge: Optional[GeminiBridge] = None
        self.audio_source: Optional[rtc.AudioSource] = None
        self._sender_task = None
        self._active = False

    async def connect_and_run(self):
        """Connect to LiveKit room and start the voice agent session."""
        try:
            # Create room instance
            self.room = rtc.Room()

            # Set up event handlers
            @self.room.on("participant_connected")
            def on_participant_connected(participant: rtc.RemoteParticipant):
                logger.info(f"[{self.room_name}] Participant connected: {participant.identity}")

            @self.room.on("track_subscribed")
            def on_track_subscribed(
                track: rtc.Track,
                publication: rtc.RemoteTrackPublication,
                participant: rtc.RemoteParticipant,
            ):
                if track.kind == rtc.TrackKind.KIND_AUDIO:
                    logger.info(f"[{self.room_name}] Subscribed to audio track from {participant.identity}")
                    asyncio.create_task(self._handle_audio_track(track))

            @self.room.on("participant_disconnected")
            def on_participant_disconnected(participant: rtc.RemoteParticipant):
                logger.info(f"[{self.room_name}] Participant disconnected: {participant.identity}")
                asyncio.create_task(self._cleanup())

            # Generate access token
            token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            token.with_identity("voice-agent")
            token.with_name("AI Voice Agent")
            token.with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self.room_name,
                    can_publish=True,
                    can_subscribe=True,
                )
            )
            access_token = token.to_jwt()

            # Connect to room
            await self.room.connect(LIVEKIT_URL, access_token)
            logger.info(f"[{self.room_name}] Connected to LiveKit room")

            # Start Gemini bridge
            self.bridge = GeminiBridge(
                call_sid=self.room_name,
                lead_id=self.lead_id,
                lead_name=self.lead_name,
                lead_company=self.lead_company,
                call_context=self.call_context,
                outbound_intro=self.outbound_intro,
                initial_info=self.initial_info,
            )
            await self.bridge.start()

            # Create audio source for publishing agent's voice
            self.audio_source = rtc.AudioSource(24000, 1)  # 24kHz mono
            track = rtc.LocalAudioTrack.create_audio_track("agent-voice", self.audio_source)
            options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            await self.room.local_participant.publish_track(track, options)

            self._active = True
            self._sender_task = asyncio.create_task(self._audio_sender())

            # Keep the session alive
            while self._active:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"[{self.room_name}] Error in LiveKit session: {e}")
        finally:
            await self._cleanup()

    async def _handle_audio_track(self, track: rtc.AudioTrack):
        """Process incoming audio from the participant and send to Gemini."""
        audio_stream = rtc.AudioStream(track)
        async for frame in audio_stream:
            if not self._active or not self.bridge:
                break
            
            # Convert frame to PCM bytes
            # LiveKit provides audio frames, we need to convert to the format Gemini expects
            pcm_data = frame.data.tobytes()
            
            # Send to Gemini bridge
            await self.bridge.send_audio(pcm_data)

    async def _audio_sender(self):
        """Send Gemini's audio output to LiveKit room."""
        if not self.bridge or not self.audio_source:
            return
        
        try:
            while self._active:
                chunk = await self.bridge.output_queue.get()
                if chunk is None:  # Sentinel value
                    break
                
                # Convert 8kHz PCM to 24kHz for LiveKit
                # Gemini outputs 24kHz, but we may need to resample
                import numpy as np
                audio_array = np.frombuffer(chunk, dtype=np.int16)
                
                # Create audio frame
                frame = rtc.AudioFrame(
                    data=audio_array.tobytes(),
                    sample_rate=24000,
                    num_channels=1,
                    samples_per_channel=len(audio_array),
                )
                
                await self.audio_source.capture_frame(frame)
                
        except Exception as e:
            logger.error(f"[{self.room_name}] Audio sender error: {e}")

    async def _cleanup(self):
        """Clean up resources when call ends."""
        self._active = False
        
        if self._sender_task:
            self._sender_task.cancel()
            try:
                await self._sender_task
            except asyncio.CancelledError:
                pass

        transcript = self.bridge.full_transcript() if self.bridge else ""
        collected_info = self.bridge.collected_info if self.bridge else None

        if self.bridge:
            await self.bridge.stop()

        if self.room:
            await self.room.disconnect()

        if self.on_call_end:
            if asyncio.iscoroutinefunction(self.on_call_end):
                await self.on_call_end(self.room_name, transcript, collected_info)
            else:
                self.on_call_end(self.room_name, transcript, collected_info)

        logger.info(f"[{self.room_name}] Session cleaned up")


async def create_livekit_room(
    lead_id: str = "",
    lead_name: str = "there",
    lead_company: str = "",
    call_context: str = "",
    initial_info=None,
    on_call_end=None,
) -> dict:
    """
    Create a new LiveKit room for a voice call session.
    Returns room details including access token for the client.
    """
    import uuid
    room_name = f"call-{uuid.uuid4().hex[:12]}"
    participant_identity = f"lead-{lead_id or uuid.uuid4().hex[:8]}"

    # Generate token for the participant (caller)
    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    token.with_identity(participant_identity)
    token.with_name(lead_name)
    token.with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        )
    )
    participant_token = token.to_jwt()

    # Start the agent handler in background
    handler = LiveKitCallHandler(
        room_name=room_name,
        participant_identity=participant_identity,
        lead_id=lead_id,
        lead_name=lead_name,
        lead_company=lead_company,
        call_context=call_context,
        initial_info=initial_info,
        on_call_end=on_call_end,
    )
    
    asyncio.create_task(handler.connect_and_run())

    return {
        "room_name": room_name,
        "participant_token": participant_token,
        "livekit_url": LIVEKIT_URL,
        "participant_identity": participant_identity,
    }
