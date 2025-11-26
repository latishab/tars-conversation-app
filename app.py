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
import queue 

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
        self.audio_queue = queue.Queue() 
        self.current_sample_rate = 24000 

    def _callback(self, outdata, frames, time, status):
        if status:
            logger.warning(f"Audio Status: {status}")
        try:
            data = self.audio_queue.get_nowait()
            if len(data) < len(outdata):
                outdata[:len(data)] = data
                outdata[len(data):] = b'\x00' * (len(outdata) - len(data))
            else:
                outdata[:] = data[:len(outdata)]
        except queue.Empty:
            outdata[:] = b'\x00' * len(outdata)

    async def play_track(self, track):
        logger.info("🔊 Speaker loop started (Buffered)")
        try:
            while self.running:
                try:
                    frame = await track.recv()
                except Exception:
                    break
                
                if self.stream is None or self.current_sample_rate != frame.sample_rate:
                    if self.stream: self.stream.stop()
                    self.current_sample_rate = frame.sample_rate
                    logger.info(f"🔊 Output Stream: {self.current_sample_rate}Hz")
                    
                    # FIX: Use device=None (Default) to avoid locking the hardware
                    # This allows PulseAudio to mix the Mic input and Speaker output safely
                    self.stream = sd.RawOutputStream(
                        samplerate=self.current_sample_rate,
                        channels=1,
                        dtype='int16',
                        device=None,  # <--- CHANGED FROM 0 TO NONE
                        blocksize=960, 
                        callback=self._callback
                    )
                    self.stream.start()

                data = frame.to_ndarray()
                if frame.layout.name == 'stereo':
                    data = data[0] if len(data.shape) > 1 else data.reshape(2, -1)[0]
                if len(data.shape) > 1:
                    data = data.reshape(-1)
                
                self.audio_queue.put(data.tobytes())
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
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except: break

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