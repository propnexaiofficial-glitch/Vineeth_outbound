import asyncio
import audioop
import base64
import json
import math
import struct
import sys
import wave

import websockets

SERVER_URL = "wss://vineeth-inbound.onrender.com/ws/voice-agent"

# Vendor's confirmed spec: 8-bit, 8kHz, mono, a-law, base64-encoded.
AUDIO_FORMAT = "alaw"
SAMPLE_RATE = 8000


def generate_test_audio_pcm16(freq=300, duration_sec=1.0, sample_rate=8000) -> bytes:
    """Generates a simple sine wave as linear PCM16 (this is just a synthetic
    test tone — real callers obviously don't sound like this)."""
    n_samples = int(sample_rate * duration_sec)
    samples = []
    for i in range(n_samples):
        val = int(5000 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(struct.pack("<h", val))
    return b"".join(samples)


def pcm16_to_alaw(pcm16_bytes: bytes) -> bytes:
    """Convert linear PCM16 -> a-law, to simulate what the real telephony
    vendor actually sends on the wire."""
    return audioop.lin2alaw(pcm16_bytes, 2)


def alaw_to_pcm16(alaw_bytes: bytes) -> bytes:
    """Convert a-law -> linear PCM16, so we can save the AI's reply as a
    normal, listenable WAV file for manual verification."""
    return audioop.alaw2lin(alaw_bytes, 2)


async def run_test():
    print(f"→ Connecting to {SERVER_URL} ...")
    replies_received = 0
    reply_pcm_chunks = []

    try:
        async with websockets.connect(SERVER_URL) as ws:
            print("✓ WebSocket connected")

            start_msg = {
                "event": "start",
                "call_id": "test-call-alaw-001",
                "audio_format": AUDIO_FORMAT,
                "sample_rate": SAMPLE_RATE,
                "lead_name": "Test User",
                "prompt_type": "sales",
                "caller_number": "8305989380"
                # "is_outbound": True,
            }
            await ws.send(json.dumps(start_msg))
            print(f"→ Sent 'start' event (audio_format={AUDIO_FORMAT!r})")

            async def listen_for_replies():
                nonlocal replies_received
                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            print(f"  [WARN] Non-JSON message received: {raw[:200]}")
                            continue

                        if msg.get("event") == "media":

                            audio_b64 = None
                            if "media" in msg and isinstance(msg["media"], dict):
                                audio_b64 = msg["media"].get("payload")
                            elif "audio" in msg:
                                audio_b64 = msg.get("audio")

                            if not audio_b64:
                                print(f"  [WARN] 'media' event with no audio payload: {msg}")
                                continue

                            try:
                                audio_bytes = base64.b64decode(audio_b64)
                            except Exception as e:
                                print(f"  [WARN] Failed to decode audio: {e}")
                                continue

                            # Server is sending audio back in AUDIO_FORMAT
                            # (a-law) — decode it to PCM16 so we can save a
                            # listenable WAV afterwards.
                            try:
                                pcm_chunk = alaw_to_pcm16(audio_bytes)
                                reply_pcm_chunks.append(pcm_chunk)
                            except Exception as e:
                                print(f"  [WARN] Failed to decode a-law reply chunk: {e}")

                            replies_received += 1
                            print(f"← Reply audio #{replies_received} received "
                                  f"({len(audio_bytes)} bytes, a-law)")
                        else:
                            print(f"  [INFO] Non-media event received: {msg.get('event')!r}")
                except websockets.exceptions.ConnectionClosed:
                    print("  (connection closed by server)")
                except Exception as e:
                    print(f"  [LISTENER ERROR] {type(e).__name__}: {e}")

            listener = asyncio.create_task(listen_for_replies())

            await asyncio.sleep(1.0)

            # Generate a synthetic tone as PCM16, then convert it to a-law
            # before sending — this simulates exactly what the real
            # telephony vendor's wire format looks like.
            test_audio_pcm16 = generate_test_audio_pcm16(duration_sec=1.0)
            test_audio_alaw = pcm16_to_alaw(test_audio_pcm16)

            chunk_size = 800  # ~0.1 sec chunks @ 8kHz, 1 byte/sample (a-law)
            for i in range(0, len(test_audio_alaw), chunk_size):
                chunk = test_audio_alaw[i:i + chunk_size]
                await ws.send(json.dumps({
                    "event": "media",
                    "audio": base64.b64encode(chunk).decode("ascii"),
                }))
                await asyncio.sleep(0.1)
            print(f"→ Sent {len(test_audio_alaw)} bytes of caller audio "
                  f"(a-law) in chunks")

            print("→ Waiting for AI reply (up to 6s)...")
            await asyncio.sleep(6.0)

            await ws.send(json.dumps({"event": "stop"}))
            print("→ Sent 'stop' event")

            await asyncio.sleep(1.0)
            listener.cancel()

    except ConnectionRefusedError:
        print("FAILED: Server not connect "
              "Check server ")
        sys.exit(1)
    except Exception as e:
        print(f"✗ FAILED: {type(e).__name__}: {e}")
        sys.exit(1)

    # Save whatever reply audio we got as a WAV so you can actually LISTEN
    # to it and confirm it's clean speech, not garbled/cracking noise.
    if reply_pcm_chunks:
        full_pcm = b"".join(reply_pcm_chunks)
        out_path = "test_reply_output.wav"
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(full_pcm)
        print(f"\n→ Saved decoded reply audio to {out_path} — listen to it "
              f"to confirm the format handling and resampling are correct.")

    print("\n" + "=" * 50)
    if replies_received > 0:
        print(f"TEST PASSED — {replies_received} reply audio chunk(s) ")
        print("   WebSocket layer and Bridge pipeline works well.")
        print("   Listen to test_reply_output.wav to verify audio quality.")
    else:
        print("TEST FAILED ")
        print("Checks Server Logs (Render dashboard) for the errors.")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(run_test())
