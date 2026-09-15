"""
test_client.py

Test client for the Bonvoice inbound/outbound voice WebSocket integration.

This matches Bonvoice's confirmed spec (NOT the earlier a-law/VoiceLink
format this test was originally written for):

    Audio format : PCM, 16-bit, 8000 Hz, mono
    Chunk size   : 320 bytes exactly (multiples of 320 only — anything
                   else is rejected by Bonvoice)

Message types Bonvoice sends/expects on the WebSocket:

  1. Call Start Event (sent once, when the WS connects)
     {
       "event": "start",
       "data": {
         "stream_id": "<stream_id>",
         "call_id": "<call_id>",
         "from": "<caller_id>",
         "to": "<did_number>"
       }
     }

  2. Media Packet (sent continuously, both directions)
     {
       "event": "media",
       "stream_id": "<stream_id>",
       "media": {
         "packet_id": <id>,
         "timestamp": <timestamp>,
         "payload": "<base64_encoded_pcm16_audio>"
       }
     }

  3. Interruption / barge-in (AI -> Bonvoice, to stop playback to caller)
     {
       "event": "clear",
       "stream_id": "<stream_id>"
     }

  4. Call Transfer (AI -> Bonvoice, to hand off to a human agent)
     {
       "event": "transfer",
       "transferTo": "<phone_number>"
     }

This script simulates Bonvoice's side: it connects to our own AI
websocket, sends a synthetic "start" event + streamed caller audio in
320-byte PCM16 chunks, and records whatever audio the AI sends back so
you can listen to it afterwards.
"""

import asyncio
import base64
import json
import math
import struct
import sys
import wave

import websockets

SERVER_URL = "wss://vineeth-outbound.onrender.com/ws/voice-agent"

# Bonvoice's confirmed spec.
SAMPLE_RATE = 8000
CHUNK_SIZE = 320  # bytes — MUST be a multiple of 320, per Bonvoice's spec

# Test call identifiers (stand-ins for what Bonvoice would generate)
TEST_STREAM_ID = "test-stream-001"
TEST_CALL_ID = "test-call-001"
TEST_CALLER_NUMBER = "8305989380"   # "from"
TEST_DID_NUMBER = "7946350797"      # "to"


def generate_test_audio_pcm16(freq=300, duration_sec=1.0, sample_rate=SAMPLE_RATE) -> bytes:
    """Generates a simple sine wave as linear PCM16 (16-bit, mono) — a
    synthetic test tone standing in for real caller audio."""
    n_samples = int(sample_rate * duration_sec)
    samples = []
    for i in range(n_samples):
        val = int(5000 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(struct.pack("<h", val))
    return b"".join(samples)


async def run_test():
    print(f"→ Connecting to {SERVER_URL} ...")
    replies_received = 0
    reply_pcm_chunks = []
    packet_id_counter = 0

    try:
        async with websockets.connect(SERVER_URL) as ws:
            print("✓ WebSocket connected")

            # ── 1. Send the "start" event, exactly as Bonvoice would ──
            start_msg = {
                "event": "start",
                "data": {
                    "stream_id": TEST_STREAM_ID,
                    "call_id": TEST_CALL_ID,
                    "from": TEST_CALLER_NUMBER,
                    "to": TEST_DID_NUMBER,
                },
            }
            await ws.send(json.dumps(start_msg))
            print(f"→ Sent 'start' event: {start_msg}")

            async def listen_for_replies():
                nonlocal replies_received
                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            print(f"  [WARN] Non-JSON message received: {raw[:200]}")
                            continue

                        event = msg.get("event")

                        if event == "media":
                            media = msg.get("media", {})
                            audio_b64 = media.get("payload")

                            if not audio_b64:
                                print(f"  [WARN] 'media' event with no payload: {msg}")
                                continue

                            try:
                                audio_bytes = base64.b64decode(audio_b64)
                            except Exception as e:
                                print(f"  [WARN] Failed to decode audio: {e}")
                                continue

                            if len(audio_bytes) % CHUNK_SIZE != 0:
                                print(f"  [WARN] Reply chunk size {len(audio_bytes)} "
                                      f"bytes is not a multiple of {CHUNK_SIZE} — "
                                      f"Bonvoice would reject this in production.")

                            # Server sends PCM16 directly — no decoding needed,
                            # can append straight to the WAV buffer.
                            reply_pcm_chunks.append(audio_bytes)

                            replies_received += 1
                            print(f"← Reply audio #{replies_received} received "
                                  f"({len(audio_bytes)} bytes, PCM16, "
                                  f"packet_id={media.get('packet_id')})")

                        elif event == "clear":
                            print(f"  [INFO] 'clear' (interruption) event received: {msg}")

                        elif event == "transfer":
                            print(f"  [INFO] 'transfer' event received: {msg}")

                        else:
                            print(f"  [INFO] Unrecognized event received: {event!r} — {msg}")

                except websockets.exceptions.ConnectionClosed:
                    print("  (connection closed by server)")
                except Exception as e:
                    print(f"  [LISTENER ERROR] {type(e).__name__}: {e}")

            listener = asyncio.create_task(listen_for_replies())

            await asyncio.sleep(1.0)

            # ── 2. Stream synthetic caller audio in 320-byte PCM16 chunks ──
            test_audio_pcm16 = generate_test_audio_pcm16(duration_sec=1.0)

            for i in range(0, len(test_audio_pcm16), CHUNK_SIZE):
                chunk = test_audio_pcm16[i:i + CHUNK_SIZE]
                if len(chunk) < CHUNK_SIZE:
                    # Pad the final chunk with silence so it's still a
                    # valid multiple of 320 bytes.
                    chunk = chunk + b"\x00" * (CHUNK_SIZE - len(chunk))

                packet_id_counter += 1
                media_msg = {
                    "event": "media",
                    "stream_id": TEST_STREAM_ID,
                    "media": {
                        "packet_id": packet_id_counter,
                        "timestamp": int(asyncio.get_event_loop().time() * 1000),
                        "payload": base64.b64encode(chunk).decode("ascii"),
                    },
                }
                await ws.send(json.dumps(media_msg))
                await asyncio.sleep(0.02)  # 320 bytes @ 16-bit mono 8kHz = 20ms per chunk

            print(f"→ Sent {len(test_audio_pcm16)} bytes of caller audio "
                  f"(PCM16) in {packet_id_counter} chunks of {CHUNK_SIZE} bytes")

            print("→ Waiting for AI reply (up to 6s)...")
            await asyncio.sleep(6.0)

            listener.cancel()

    except ConnectionRefusedError:
        print("FAILED: Could not connect to server. Check the server is running "
              "and SERVER_URL is correct.")
        sys.exit(1)
    except Exception as e:
        print(f"✗ FAILED: {type(e).__name__}: {e}")
        sys.exit(1)

    # Save whatever reply audio we got as a WAV so you can listen to it
    # and confirm it's clean speech, not garbled/cracking noise.
    if reply_pcm_chunks:
        full_pcm = b"".join(reply_pcm_chunks)
        out_path = "test_reply_output.wav"
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)  # 16-bit
            w.setframerate(SAMPLE_RATE)
            w.writeframes(full_pcm)
        print(f"\n→ Saved decoded reply audio to {out_path} — listen to it "
              f"to confirm the format handling is correct.")

    print("\n" + "=" * 50)
    if replies_received > 0:
        print(f"TEST PASSED — {replies_received} reply audio chunk(s) received.")
        print("   WebSocket layer and AI pipeline are working.")
        print("   Listen to test_reply_output.wav to verify audio quality.")
    else:
        print("TEST FAILED — no reply audio received.")
        print("Check server logs (Render dashboard) for errors.")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(run_test())