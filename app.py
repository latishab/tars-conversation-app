"""
app.py 

Main entry point for the TARS-AI Robot Body application.
"""

# === Standard Libraries ===
import os
import sys
import threading
import time
import signal
import asyncio
import json
import aiohttp
import logging
import subprocess

# === Custom Modules ===
from modules.module_config import load_config
from modules.module_messageQue import queue_message

# === WebRTC and Audio ===
try:
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
    from pipecat.transports.base_transport import TransportParams
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
    from aiortc.contrib.media import MediaPlayer, MediaRelay
    from aiortc.mediastreams import MediaStreamTrack
    import sounddevice as sd
    import numpy as np
    from av import AudioFrame
    from av.audio.resampler import AudioResampler
    import fractions
    WEBRTC_AVAILABLE = True
except ImportError as e:
    WEBRTC_AVAILABLE = False
    queue_message(f"ERROR: Required packages not available: {e}")
    queue_message("Install with: pip install aiortc aiohttp sounddevice numpy")

from modules.module_battery import BatteryModule

# Import servo control functions
CONFIG = load_config()
if (CONFIG["SERVO"]["MOVEMENT_VERSION"] == "V2"):
    from modules.module_servoctl_v2 import *
else:
    from modules.module_servoctl import *

from loguru import logger

# === LOGGING CONFIGURATION ===
logging.getLogger("aiortc").setLevel(logging.WARNING)
logging.getLogger("aioice").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger.remove() 
logger.add(
    sys.stderr, 
    format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", 
    level="INFO"
)

# === MicrophoneStream Class ===
class MicrophoneStream(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self.rate = 48000
        self.channels = 1
        
        # We keep device=0 here to ensure we grab the WM8960 Mic
        self.stream = sd.InputStream(
            samplerate=self.rate,
            channels=self.channels,
            dtype="int16",
            blocksize=960, 
            device=0 
        )
        self.stream.start()
        self.start_time = time.time()
        logger.info(f"MicrophoneStream initialized: {self.rate}Hz")

    async def recv(self):
        loop = asyncio.get_running_loop()
        data, overflow = await loop.run_in_executor(None, lambda: self.stream.read(960))
        if overflow:
            logger.warning("⚠️ Audio Overflow")

        frame = AudioFrame.from_ndarray(data.T.reshape(1, -1), format='s16', layout='mono')
        frame.sample_rate = self.rate
        frame.pts = int((time.time() - self.start_time) * self.rate)
        frame.time_base = fractions.Fraction(1, self.rate)
        return frame

    def stop(self):
        if hasattr(self, 'stream') and self.stream:
            self.stream.stop()
            self.stream.close()

# === SpeakerStream Class (Jitter Buffer) ===
class SpeakerStream:
    def __init__(self, volume=1.0):
        self.volume = max(0.0, min(1.0, volume))
        self.stream = None
        self.running = True
        self.target_sample_rate = 48000  # WM8960 prefers 48 kHz playback
        self._buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self.resampler = AudioResampler(
            format="s16",
            layout="mono",
            rate=self.target_sample_rate,
        )

    def _callback(self, outdata, frames, time, status):
        if status:
            logger.warning(f"Audio Status: {status}")

        required = len(outdata)
        written = 0

        with self._buffer_lock:
            available = len(self._buffer)
            if available >= required:
                outdata[:] = self._buffer[:required]
                del self._buffer[:required]
                written = required
            elif available > 0:
                outdata[:available] = self._buffer
                del self._buffer[:available]
                written = available

        if written < required:
            outdata[written:] = b'\x00' * (required - written)

    async def play_track(self, track):
        logger.info("🔊 Speaker loop started (Buffered)")
        try:
            # Create a single playback stream locked to the target sample rate
            if self.stream is None:
                logger.info(f"🔊 Output Stream: {self.target_sample_rate}Hz")
                self.stream = sd.RawOutputStream(
                    samplerate=self.target_sample_rate,
                    channels=1,
                    dtype="int16",
                    device=None,
                    blocksize=960,
                    callback=self._callback,
                )
                self.stream.start()

            while self.running:
                try:
                    frame = await track.recv()
                except Exception:
                    break

                # Normalize every frame to signed 16-bit mono at 48 kHz
                try:
                    # Reuse resampler to avoid clicks when the remote side switches rates
                    resampled = self.resampler.resample(frame)
                    if not resampled:
                        continue
                    frame = resampled[0]
                except Exception as err:
                    logger.error(f"Resample error: {err}")
                    continue

                data = frame.to_ndarray()
                if frame.layout.name == 'stereo':
                    data = data[0] if len(data.shape) > 1 else data.reshape(2, -1)[0]
                if len(data.shape) > 1:
                    data = data.reshape(-1)

                pcm_bytes = data.tobytes()

                # Preserve leftover samples between callbacks so the stream stays smooth
                with self._buffer_lock:
                    self._buffer.extend(pcm_bytes)

        except Exception as e:
            logger.error(f"Speaker error: {e}")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except: pass
            self.stream = None
        with self._buffer_lock:
            self._buffer.clear()

# === Constants and Configuration ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)
CONFIG = load_config()
VERSION = "4.0"

SERVER_IP = os.getenv("SERVER_IP", "172.28.242.124")
SERVER_PORT = int(os.getenv("SERVER_PORT", "7860"))
SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"

for arg in sys.argv[1:]: 
    if "=" in arg:
        key, value = arg.split("=", 1)
        if key == "server_ip": SERVER_IP = value
        elif key == "server_port": SERVER_PORT = int(value)
SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"

# === Main ===
async def send_ice_candidate(session, pc_id, candidate):
    try:
        await session.patch(
            f"{SERVER_URL}/api/offer",
            json={
                "pc_id": pc_id,
                "candidates": [{"candidate": candidate.candidate, "sdp_mid": candidate.sdpMid, "sdp_mline_index": candidate.sdpMLineIndex}],
            },
        )
    except: pass

async def main():
    logger.info(f"🤖 Robot Body initializing... connecting to {SERVER_URL}")
    battery = BatteryModule()
    battery.start()

    try:
        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")]))
        
        try:
            logger.info("Initializing Microphone...")
            audio_player = MicrophoneStream()
            pc.addTransceiver(audio_player, direction="sendrecv")
            logger.info("✓ Microphone initialized")
        except Exception as e:
            logger.error(f"Mic Error: {e}")
            return

        speaker = None
        audio_task = None

        @pc.on("track")
        async def on_track(track):
            nonlocal speaker, audio_task
            logger.info(f"Received remote track: {track.kind}")
            
            if track.kind == "audio":
                speaker = SpeakerStream(volume=1.0)
                if audio_task and not audio_task.done():
                    audio_task.cancel()
                audio_task = asyncio.create_task(speaker.play_track(track))

        # --- DATA CHANNEL & CONNECTION LOGIC ---
        data_channel = pc.createDataChannel("messages", ordered=True)
        
        @data_channel.on("open")
        def on_open(): queue_message("✅ Data channel connected")
        
        # RESTORED: Full message handler for logs
        @data_channel.on("message")
        def on_msg(msg):
            try:
                data = json.loads(msg)
                msg_type = data.get("type")
                if msg_type == "transcription":
                    queue_message(f"🎤 YOU: {data.get('text')}")
                elif msg_type == "partial":
                    text = data.get("text", "")
                    if text: queue_message(f"🎙️ Listening... {text}")
                elif msg_type == "system":
                    queue_message(f"ℹ️ {data.get('message')}")
                elif msg_type == "error":
                    queue_message(f"❌ Error: {data.get('message')}")
            except: pass

        await pc.setLocalDescription(await pc.createOffer())
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{SERVER_URL}/api/offer", json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}) as resp:
                if resp.status != 200: 
                    logger.error("Server connection failed")
                    return
                answer = await resp.json()
                pc_id = answer["pc_id"]
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
        
        queue_message("✅ WebRTC connection established!")
        
        stop_event = asyncio.Event()
        def handler(): stop_event.set()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM): loop.add_signal_handler(sig, handler)
        await stop_event.wait()

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if 'audio_player' in locals(): audio_player.stop()
        if 'speaker' in locals() and speaker: speaker.stop()
        if 'pc' in locals(): await pc.close()
        battery.stop()

if __name__ == "__main__":
    asyncio.run(main())