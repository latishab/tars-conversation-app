"""
app.py 

Main entry point for the TARS-AI Robot Body application.

Connects to a remote server (Brain) via WebRTC and streams:
- Microphone audio input
- Camera video input
- Receives audio output from server
- Handles servo control commands from server

Run this script directly to start the robot body.
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


# === MicrophoneStream Class (SoundDevice-based) ===
class MicrophoneStream(MediaStreamTrack):
    """Custom audio track using sounddevice for microphone input."""
    kind = "audio"

    def __init__(self):
        super().__init__()
        # WebRTC typically uses 48kHz for audio (standard WebRTC sample rate)
        # Using 48kHz ensures compatibility with WebRTC codecs
        self.rate = 48000
        self.channels = 1
        self.device_name = "default"  # Or use the specific index if needed
        
        # Create the stream (Non-blocking)
        # blocksize=960 = 20ms of audio at 48kHz (960 samples = 20ms)
        self.stream = sd.InputStream(
            samplerate=self.rate,
            channels=self.channels,
            dtype="int16",
            blocksize=960  # 20ms of audio at 48kHz
        )
        self.stream.start()
        self.start_time = time.time()
        logger.info(f"MicrophoneStream initialized: {self.rate}Hz, {self.channels} channel(s)")

    async def recv(self):
        # NOTE: Run the blocking 'read' in a separate thread!
        # This allows the WebRTC connection to keep breathing while we wait for audio.
        # Without this, the blocking read freezes the event loop and prevents
        # WebRTC from performing DTLS handshake and sending data packets.
        loop = asyncio.get_running_loop()
        
        # Run the blocking read in an executor thread
        data, overflow = await loop.run_in_executor(None, lambda: self.stream.read(960))
        
        if overflow:
            logger.warning("⚠️ Audio Overflow (CPU too slow)")

        # Convert numpy array to AV AudioFrame
        # Format: s16 (signed 16-bit), layout: mono
        # Reshape: (1, samples) for mono channel
        frame = AudioFrame.from_ndarray(data.T.reshape(1, -1), format='s16', layout='mono')
        frame.sample_rate = self.rate
        frame.pts = int((time.time() - self.start_time) * self.rate)
        frame.time_base = fractions.Fraction(1, self.rate)
        
        return frame

    def stop(self):
        if hasattr(self, 'stream') and self.stream:
            self.stream.stop()
            self.stream.close()

import logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger('bm25s').setLevel(logging.WARNING)

# === Constants and Globals ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)
sys.path.append(os.getcwd())

CONFIG = load_config()
VERSION = "4.0"

# --- CONFIGURATION ---
# WebRTC server connection settings
SERVER_IP = os.getenv("SERVER_IP", "172.28.149.250")
SERVER_PORT = int(os.getenv("SERVER_PORT", "7860"))
SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"

# Parse command line arguments
for arg in sys.argv[1:]: 
    if "=" in arg:
        key, value = arg.split("=", 1)
        if key == "server_ip":
            SERVER_IP = value
            SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"
        elif key == "server_port":
            SERVER_PORT = int(value)
            SERVER_URL = f"http://{SERVER_IP}:{SERVER_PORT}"

# === Helper Functions ===

def handle_servo_command(message_data):
    """
    Handle incoming servo control commands from the server.
    Expected format: {"command": "function_name", "args": {...}}
    """
    try:
        if isinstance(message_data, str):
            message_data = json.loads(message_data)
        
        command = message_data.get("command")
        args = message_data.get("args", {})
        
        # Map of available servo commands
        servo_commands = {
            "step_forward": step_forward,
            "step_backward": step_backward,
            "turn_right": turn_right,
            "turn_left": turn_left,
            "right_hi": right_hi,
            "laugh": laugh,
            "swing_legs": swing_legs,
            "pose": pose,
            "bow": bow,
            "reset_positions": reset_positions,
            "disable_all_servos": disable_all_servos,
            "move_legs": lambda: move_legs(
                args.get("height_percent"),
                args.get("starboard_percent"),
                args.get("port_percent"),
                args.get("speed_factor", 1.0)
            ),
            "move_arm": lambda: move_arm(
                args.get("port_main"),
                args.get("port_forearm"),
                args.get("port_hand"),
                args.get("star_main"),
                args.get("star_forearm"),
                args.get("star_hand"),
                args.get("speed_factor", 0.5)
            ),
            "set_servo_pwm": lambda: set_servo_pwm(
                args.get("channel"),
                args.get("pwm_value")
            ),
        }
        
        if command in servo_commands:
            queue_message(f"🤖 Executing servo command: {command}")
            func = servo_commands[command]
            if callable(func):
                # Run in a thread to avoid blocking
                threading.Thread(target=func, daemon=True).start()
            else:
                func()  # If it's already a lambda call
        else:
            queue_message(f"⚠️ Unknown servo command: {command}")
            
    except Exception as e:
        queue_message(f"❌ Error handling servo command: {e}")
        import traceback
        queue_message(traceback.format_exc())


# === Main Application Logic ===

async def send_ice_candidate(session: aiohttp.ClientSession, pc_id: str, candidate):
    """Send ICE candidate to server"""
    try:
        await session.patch(
            f"{SERVER_URL}/api/offer",
            json={
                "pc_id": pc_id,
                "candidates": [{
                    "candidate": candidate.candidate,
                    "sdp_mid": candidate.sdpMid,
                    "sdp_mline_index": candidate.sdpMLineIndex,
                }],
            },
        )
        logger.debug(f"Sent ICE candidate")
    except Exception as e:
        logger.error(f"Error sending ICE candidate: {e}")


async def main():
    """Main async function to handle WebRTC connection"""
        logger.info(f"🤖 Robot Body initializing... connecting to Brain at {SERVER_URL}")

    # Initialize the battery module
    battery = BatteryModule()
    battery.start()

    if not WEBRTC_AVAILABLE:
        queue_message("ERROR: WebRTC not available. Please install: pip install aiortc aiohttp")
        return

    try:
        queue_message(f"LOAD: TARS-AI Robot Body v{VERSION} connecting to {SERVER_URL}")
        queue_message(f"INFO: Make sure server is running on {SERVER_IP}:{SERVER_PORT}")
        
        # Create WebRTC peer connection
        # Add STUN server for NAT traversal (helps with connection)
        # FIX: Use RTCConfiguration object instead of dictionary
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(
                iceServers=[
                    RTCIceServer(urls="stun:stun.l.google.com:19302")
                ]
            )
        )
        relay = MediaRelay()
        
        # Queue for ICE candidates
        pending_ice_candidates = []
        pc_id = None
        can_send_ice_candidates = False
        
        # Voice activity tracking
        is_speaking = False
        last_audio_time = time.time()
        last_partial_text = ""  # Track last partial to avoid spam
        last_partial_time = 0  # Throttle partial updates
        
        # Video disabled for now - focus on audio only
        # COMMENTED OUT to stop server from crashing on video encoding
        # The server tries to send video but fails, causing AssertionError in vpx.py
        logger.debug("Video disabled - audio only mode")
        # pc.addTransceiver("video", direction="recvonly")  # Disabled to prevent video errors
        video_player = None
        
        # Create audio player (microphone) using SoundDevice
        # This approach uses PortAudio to talk to ALSA hardware directly
        # Much more reliable than MediaPlayer for embedded devices
        audio_player = None
        
        try:
            logger.info("Initializing SoundDevice Microphone...")
            
            # Optional: Print available devices for debugging
            # logger.debug(f"Available audio devices:\n{sd.query_devices()}")
            
            # Initialize our custom track
            audio_player = MicrophoneStream()
            
            # Add track directly to WebRTC - SmallWebRTC expects transceivers
            # Using addTransceiver ensures the server can receive our audio
            # IMPORTANT: Add transceiver BEFORE creating the offer
            # Try without relay first - direct track addition
            audio_transceiver = pc.addTransceiver(audio_player, direction="sendrecv")
            
            logger.debug(f"Audio transceiver created (direction: sendrecv)")
            logger.debug(f"Audio track kind: {audio_player.kind}")
            
            # Verify the transceiver is set up correctly
            if audio_transceiver.sender and audio_transceiver.sender.track:
                logger.debug(f"Audio sender track confirmed: {audio_transceiver.sender.track.kind}")
            else:
                logger.warning("⚠️ Audio sender track not properly set")
            
            logger.info("✓ Microphone initialized via SoundDevice")
            queue_message("✓ Microphone connected via SoundDevice")
            queue_message("")
            queue_message("=" * 60)
            queue_message("✅ READY TO TALK TO TARS!")
            queue_message("=" * 60)
            queue_message("📢 Just speak into the microphone naturally")
            queue_message("")
            queue_message("📊 STATUS INDICATORS:")
            queue_message("   🎙️ Listening... = VAD detected, STT processing")
            queue_message("   🎤 YOU: = Your final transcription")
            queue_message("   ⏳ Processing... = LLM generating response")
            queue_message("   🤖 TARS: = TARS is speaking")
            queue_message("")
            queue_message("💡 Wait for TARS to finish before speaking again")
            queue_message("=" * 60)
            queue_message("")
            
        except Exception as e:
            logger.error(f"Microphone failed: {e}")
            queue_message(f"❌ Mic Error: {e}")
            queue_message("INFO: Check wm8960 is enabled: dmesg | grep wm8960")
            queue_message("INFO: Test recording: arecord -D hw:0,0 -d 2 test.wav")
            queue_message("INFO: List audio devices: arecord -l")
            queue_message("INFO: You can still receive audio from server, but cannot send voice")
            queue_message("")
            queue_message("⚠️ MICROPHONE NOT WORKING - TARS cannot hear you!")
            queue_message("   Fix microphone first, then restart the app.")
            audio_player = None
        
        # Handle incoming audio (TTS from server) - TARS speaking to you
        audio_output_player = None
        tars_is_speaking = False
        
        @pc.on("track")
        async def on_track(track):
            nonlocal tars_is_speaking
            logger.debug(f"Received remote track: {track.kind}")
            if track.kind == "audio":
                if not tars_is_speaking:
                    logger.info("🔊 TARS is speaking...")
                    queue_message("")
                    queue_message("🤖 TARS: [Speaking...]")
                    tars_is_speaking = True
        
        # Create data channel for receiving messages (servo commands)
        data_channel = pc.createDataChannel("messages", ordered=True)
        
        @data_channel.on("open")
        def on_data_channel_open():
            logger.debug("Data channel opened")
            queue_message("✅ Data channel connected")
        
        @data_channel.on("message")
        def on_data_channel_message(message):
            nonlocal is_speaking, last_partial_text, last_partial_time
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")
                
                if msg_type == "transcription":
                    # User's speech was transcribed (final result)
                    text = data.get("text", "")
                    speaker_id = data.get("speaker_id")
                    speaker_label = f"[Speaker {speaker_id}] " if speaker_id else ""
                    logger.info(f"🎤 You said: {text}")
                    queue_message("")
                    queue_message(f"🎤 YOU: {text}")
                    queue_message("   ⏳ Processing...")
                    is_speaking = False
                    last_partial_text = ""  # Reset partial tracking
                    
                elif msg_type == "partial":
                    # Partial transcription (while speaking) - throttle to reduce spam
                    text = data.get("text", "").strip()
                    current_time = time.time()
                    
                    # Only show if:
                    # 1. Text has changed significantly (new words added)
                    # 2. Or it's been > 0.5 seconds since last update
                    text_changed = text != last_partial_text and (
                        len(text) > len(last_partial_text) + 3 or  # Significant new text
                        not text.startswith(last_partial_text[:max(1, len(last_partial_text)-5)])  # Different words
                    )
                    time_elapsed = current_time - last_partial_time > 0.5
                    
                    if text and (text_changed or time_elapsed):
                        logger.debug(f"⏳ Partial: {text}")  # Changed to DEBUG to reduce spam
                        # Only update queue if text changed significantly
                        if text_changed:
                            queue_message(f"🎙️ Listening... {text}")
                            last_partial_text = text
                            last_partial_time = current_time
                        is_speaking = True
                    
                elif msg_type == "error":
                    # Error from server
                    error_msg = data.get("message", "")
                    logger.error(f"Server error: {error_msg}")
                    queue_message(f"❌ Error: {error_msg}")
                    is_speaking = False
                    
                elif msg_type == "system":
                    # System message
                    sys_msg = data.get("message", "")
                    logger.debug(f"System: {sys_msg}")
                    queue_message(f"ℹ️ {sys_msg}")
                    
                else:
                    # Servo command or other message
                    logger.debug(f"📩 Message from Brain: {data}")
                    # handle_servo_command(data)  # Uncomment to enable servo commands
                    
            except Exception as e:
                logger.error(f"Error handling message: {e}")
        
        # Handle ICE candidates
        @pc.on("icecandidate")
        async def on_ice_candidate(candidate):
            if candidate:
                if can_send_ice_candidates and pc_id:
                    async with aiohttp.ClientSession() as session:
                        await send_ice_candidate(session, pc_id, candidate)
                else:
                    pending_ice_candidates.append(candidate)
            else:
                logger.info("All ICE candidates sent")
        
        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            logger.info(f"Connection state: {pc.connectionState}")
            if pc.connectionState == "connected":
                logger.success("✅ Connected to Brain!")
                queue_message("✅ Connected to Brain!")
            elif pc.connectionState in ["disconnected", "failed"]:
                logger.warning(f"Connection {pc.connectionState}")
                queue_message(f"⚠️ Connection {pc.connectionState}")
        
        # Create offer
        await pc.setLocalDescription(await pc.createOffer())
        offer = pc.localDescription
        
        logger.debug("Sending WebRTC offer to server...")
        
        # First, test server connectivity
        logger.debug("Testing server connectivity...")
        async with aiohttp.ClientSession() as test_session:
            try:
                async with test_session.get(
                    f"{SERVER_URL}/api/status",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as status_response:
                    if status_response.status == 200:
                        status_data = await status_response.json()
                        logger.debug(f"✓ Server is reachable: {status_data}")
                        queue_message("✓ Server is reachable")
                    else:
                        logger.warning(f"Server returned status {status_response.status}")
                        queue_message(f"⚠️ Server returned status {status_response.status}")
            except aiohttp.ClientConnectorError as e:
                logger.error(f"Cannot connect to server: {e}")
                queue_message(f"ERROR: Cannot connect to server at {SERVER_URL}")
                queue_message(f"INFO: Make sure the server is running on {SERVER_IP}:{SERVER_PORT}")
                queue_message(f"INFO: Check network connectivity: ping {SERVER_IP}")
                queue_message(f"INFO: Check firewall settings on server")
                return
            except asyncio.TimeoutError:
                logger.error("Server connection timeout")
                queue_message(f"ERROR: Server connection timeout")
                queue_message(f"INFO: Server may be unreachable or firewall is blocking")
                return
            except Exception as e:
                logger.error(f"Error testing server: {e}")
                queue_message(f"ERROR: {str(e)}")
                return
        
        # Send offer to server
        logger.debug("Sending WebRTC offer...")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{SERVER_URL}/api/offer",
                    json={"sdp": offer.sdp, "type": offer.type},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Server error: {response.status} - {error_text}")
                        queue_message(f"ERROR: Server error: {response.status}")
                        return
                    
                    answer_data = await response.json()
                    pc_id = answer_data.get("pc_id")
                    logger.info(f"Received answer with pc_id: {pc_id}")
            except aiohttp.ClientError as e:
                logger.error(f"HTTP client error: {e}")
                queue_message(f"ERROR: HTTP error: {str(e)}")
                return
            except Exception as e:
                logger.error(f"Error sending offer: {e}")
                queue_message(f"ERROR: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                return
        
        # Set remote description
        answer = RTCSessionDescription(
            sdp=answer_data["sdp"],
            type=answer_data["type"],
        )
        await pc.setRemoteDescription(answer)
        
        # Now we can send ICE candidates
        can_send_ice_candidates = True
        
        # Send any queued ICE candidates
        async with aiohttp.ClientSession() as session:
            for candidate in pending_ice_candidates:
                await send_ice_candidate(session, pc_id, candidate)
        pending_ice_candidates = []
        
        logger.success("✅ WebRTC connection established!")
        queue_message("✅ WebRTC connection established!")
        queue_message("")
        queue_message("🎤 Microphone is active and listening...")
        queue_message("")
        
        # Keep the script running until interrupted
        stop_event = asyncio.Event()
        
        # Periodic status update to show mic is working
        async def status_heartbeat():
            """Periodic heartbeat to show system is alive"""
            while not stop_event.is_set():
                await asyncio.sleep(30)  # Every 30 seconds
                if not stop_event.is_set():
                    logger.debug("💓 System heartbeat - microphone active")
                    # Don't spam messages, just log
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(status_heartbeat())
        
        def signal_handler():
            logger.info("Stopping...")
            queue_message("INFO: Stopping robot body...")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

        await stop_event.wait()
        
        # Cancel heartbeat
        heartbeat_task.cancel()

    except Exception as e:
        logger.error(f"❌ Connection failed: {e}")
        queue_message(f"ERROR: Connection failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # Cleanup
        queue_message("INFO: Cleaning up...")
        # Video disabled, so no video_player cleanup needed
        if audio_player:
            audio_player.stop()
        if 'pc' in locals():
            await pc.close()
        battery.stop()
        queue_message("INFO: Robot body stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        queue_message("INFO: Interrupted by user")
    except Exception as e:
        queue_message(f"ERROR: {e}")
        import traceback
        queue_message(traceback.format_exc())

