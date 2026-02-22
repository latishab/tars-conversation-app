"""
WebRTC client using aiortc to connect to Raspberry Pi TARS robot.

Manages:
- WebRTC peer connection to RPi server
- Audio tracks (mic from RPi, TTS to RPi)
- DataChannel for state synchronization
- Automatic reconnection
"""

import asyncio
import httpx
from typing import Optional, Callable, Dict, Any
from loguru import logger

from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
    MediaStreamTrack,
)
from aiortc.contrib.media import MediaRecorder, MediaPlayer


class AiortcRPiClient:
    """
    WebRTC client that connects to Raspberry Pi TARS robot.

    Connection flow:
    1. Create SDP offer
    2. POST offer to http://<rpi-ip>:8000/api/offer
    3. Receive SDP answer
    4. Establish P2P connection
    5. Audio tracks + DataChannel active
    """

    def __init__(
        self,
        rpi_url: str = "http://tars.local:8000",
        auto_reconnect: bool = True,
        reconnect_delay: int = 5,
        max_reconnect_attempts: int = 0,  # 0 = infinite
    ):
        """
        Initialize WebRTC client.

        Args:
            rpi_url: Base URL of RPi TARS server
            auto_reconnect: Enable automatic reconnection
            reconnect_delay: Delay between reconnection attempts (seconds)
            max_reconnect_attempts: Max reconnection attempts (0 = infinite)
        """
        self.rpi_url = rpi_url.rstrip('/')
        self.auto_reconnect = auto_reconnect
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # Connection state
        self._pc: Optional[RTCPeerConnection] = None
        self._data_channel: Optional[Any] = None
        self._connected = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_count = 0

        # Audio tracks
        self._audio_track_from_rpi: Optional[MediaStreamTrack] = None
        self._audio_track_to_rpi: Optional[MediaStreamTrack] = None

        # Callbacks
        self._on_audio_track_callback: Optional[Callable[[MediaStreamTrack], None]] = None
        self._on_data_channel_message_callback: Optional[Callable[[str], None]] = None
        self._on_connected_callback: Optional[Callable[[], None]] = None
        self._on_disconnected_callback: Optional[Callable[[], None]] = None

    async def connect(self) -> bool:
        """
        Connect to RPi WebRTC server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"🔌 Connecting to RPi at {self.rpi_url}...")

            # Create peer connection
            # Use STUN server for NAT traversal (helpful for remote connections)
            config = RTCConfiguration(
                iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
            )
            self._pc = RTCPeerConnection(configuration=config)

            # Set up event handlers
            @self._pc.on("connectionstatechange")
            async def on_connectionstatechange():
                state = self._pc.connectionState
                logger.info(f"🔗 WebRTC connection state: {state}")

                if state == "connected":
                    self._connected = True
                    self._reconnect_count = 0
                    if self._on_connected_callback:
                        await self._on_connected_callback()
                elif state == "failed" or state == "closed":
                    self._connected = False
                    if self._on_disconnected_callback:
                        await self._on_disconnected_callback()
                    if self.auto_reconnect:
                        await self._schedule_reconnect()

            @self._pc.on("track")
            async def on_track(track):
                logger.info(f"📻 Received track: {track.kind}")
                if track.kind == "audio":
                    self._audio_track_from_rpi = track
                    if self._on_audio_track_callback:
                        await self._on_audio_track_callback(track)

                    @track.on("ended")
                    async def on_ended():
                        logger.info("📻 Audio track ended")

            # Create data channel for state sync
            self._data_channel = self._pc.createDataChannel("state")

            @self._data_channel.on("open")
            def on_open():
                logger.info("📡 DataChannel opened")

            @self._data_channel.on("message")
            def on_message(message):
                if self._on_data_channel_message_callback:
                    self._on_data_channel_message_callback(message)

            # Add transceiver to receive audio from RPi
            self._pc.addTransceiver("audio", direction="recvonly")

            # Create offer
            offer = await self._pc.createOffer()
            await self._pc.setLocalDescription(offer)

            # Send offer to RPi
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.rpi_url}/api/offer",
                    json={
                        "sdp": self._pc.localDescription.sdp,
                        "type": self._pc.localDescription.type,
                    },
                )
                response.raise_for_status()
                answer_data = response.json()

            # Set remote description (answer from RPi)
            answer = RTCSessionDescription(
                sdp=answer_data["sdp"],
                type=answer_data["type"],
            )
            await self._pc.setRemoteDescription(answer)

            logger.info("✓ WebRTC offer/answer exchange complete")
            # Connection will be marked as connected when ICE completes
            return True

        except Exception as e:
            logger.error(f"❌ Failed to connect to RPi: {e}")
            self._connected = False
            if self.auto_reconnect:
                await self._schedule_reconnect()
            return False

    async def disconnect(self):
        """Close WebRTC connection."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._pc:
            await self._pc.close()
            self._pc = None

        self._data_channel = None
        self._audio_track_from_rpi = None
        self._audio_track_to_rpi = None
        self._connected = False
        logger.info("🔌 Disconnected from RPi")

    async def _schedule_reconnect(self):
        """Schedule reconnection attempt."""
        if not self.auto_reconnect:
            return

        if self.max_reconnect_attempts > 0 and self._reconnect_count >= self.max_reconnect_attempts:
            logger.error(f"❌ Max reconnection attempts ({self.max_reconnect_attempts}) reached")
            return

        self._reconnect_count += 1
        logger.info(f"🔄 Reconnecting in {self.reconnect_delay}s (attempt {self._reconnect_count})...")

        await asyncio.sleep(self.reconnect_delay)
        await self.connect()

    def is_connected(self) -> bool:
        """Check if connected to RPi."""
        return self._connected and self._pc is not None

    def send_data_channel_message(self, message: str):
        """
        Send message via DataChannel.

        Args:
            message: JSON string to send
        """
        if self._data_channel and self._data_channel.readyState == "open":
            self._data_channel.send(message)
        else:
            logger.debug("DataChannel not open, message not sent")

    def get_audio_track(self) -> Optional[MediaStreamTrack]:
        """Get audio track from RPi (microphone)."""
        return self._audio_track_from_rpi

    def add_audio_track(self, track: MediaStreamTrack):
        """
        Add audio track to send to RPi (TTS output).

        Args:
            track: Audio track to send
        """
        if self._pc:
            self._pc.addTrack(track)
            self._audio_track_to_rpi = track
            logger.info("🎤 Added audio track to RPi connection")

    def on_audio_track(self, callback: Callable[[MediaStreamTrack], None]):
        """Register callback for when audio track is received."""
        self._on_audio_track_callback = callback

    def on_data_channel_message(self, callback: Callable[[str], None]):
        """Register callback for DataChannel messages."""
        self._on_data_channel_message_callback = callback

    def on_connected(self, callback: Callable[[], None]):
        """Register callback for connection established."""
        self._on_connected_callback = callback

    def on_disconnected(self, callback: Callable[[], None]):
        """Register callback for connection lost."""
        self._on_disconnected_callback = callback
