"""
TARS Client - Communicates with Raspberry Pi hardware over Tailscale/HTTP
Handles: Display, Movement, Camera, Audio streaming
"""

import httpx
import asyncio
import base64
from typing import Optional, Dict, Any, Callable, List
from loguru import logger

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("websockets not installed - audio streaming disabled")


class TARSClient:
    """
    Client for controlling TARS Raspberry Pi hardware service.

    Features:
    - Display control (eyes, spectrum, emotions)
    - Movement control (servos, walking)
    - Camera capture
    - Audio streaming (mic input)
    - Audio playback (speaker output)
    """

    def __init__(
        self,
        base_url: str = "http://100.64.0.0:8001",  # Tailscale IP
        timeout: float = 30.0
    ):
        """
        Initialize TARS client.

        Args:
            base_url: Base URL of TARS Raspberry Pi API
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.ws_url = self.base_url.replace('http://', 'ws://').replace('https://', 'wss://')
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False

        # Audio streaming
        self._audio_ws = None
        self._audio_callback: Optional[Callable[[bytes], None]] = None
        self._audio_task: Optional[asyncio.Task] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self):
        """Initialize HTTP client and test connection"""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            # Test connection
            try:
                health = await self.health()
                if health.get("status") == "ok":
                    self._connected = True
                    logger.info(f"✓ Connected to TARS at {self.base_url}")
                    logger.info(f"  Hardware: servos={health.get('hardware', {}).get('servos')}, "
                              f"camera={health.get('hardware', {}).get('camera')}, "
                              f"audio={health.get('hardware', {}).get('audio')}")
                else:
                    logger.warning(f"TARS connection test failed: {health}")
                    self._connected = False
            except Exception as e:
                logger.warning(f"Could not connect to TARS: {e}")
                self._connected = False

    async def disconnect(self):
        """Close all connections"""
        await self.stop_audio_stream()
        if self._client:
            await self._client.aclose()
            self._client = None
            self._connected = False

    # Alias for consistency
    async def close(self):
        """Alias for disconnect()"""
        await self.disconnect()

    def is_connected(self) -> bool:
        """Check if connected to TARS hardware"""
        return self._connected

    async def is_available(self) -> bool:
        """Check if TARS hardware is available"""
        health = await self.health()
        return health.get("status") == "ok"

    async def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Internal POST request handler.

        Args:
            endpoint: API endpoint (e.g., "/display/mode")
            data: JSON data to send

        Returns:
            Response JSON
        """
        if not self._client:
            await self.connect()

        try:
            url = f"{self.base_url}{endpoint}"
            response = await self._client.post(url, json=data)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.debug(f"TARS API error ({endpoint}): {e}")
            return {"status": "error", "error": str(e)}

    async def _get(self, endpoint: str) -> Dict[str, Any]:
        """
        Internal GET request handler.

        Args:
            endpoint: API endpoint

        Returns:
            Response JSON
        """
        if not self._client:
            await self.connect()

        try:
            url = f"{self.base_url}{endpoint}"
            response = await self._client.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.debug(f"TARS API error ({endpoint}): {e}")
            return {"status": "error", "error": str(e)}

    # ========== Health & Status ==========

    async def health(self) -> Dict[str, Any]:
        """
        Check hardware service health.

        Returns:
            Dict with status, moving flag, and hardware availability
        """
        try:
            return await self._get("/health")
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def get_state(self) -> Dict[str, Any]:
        """Get current servo positions and movement state"""
        return await self._get("/state")

    # ========== Movement Control ==========

    async def move(self, movements: List[str]) -> Dict[str, Any]:
        """
        Execute movement sequence.

        Args:
            movements: List of movements, e.g. ["forward", "left", "backward"]
                      Valid: forward, backward, walk_forward, walk_backward, left, right

        Returns:
            Dict with status and results
        """
        try:
            result = await self._post("/move", {"movements": movements})
            if result.get("status") == "ok":
                logger.info(f"🚶 Movement executed: {movements}")
            else:
                logger.warning(f"Movement failed: {result}")
            return result
        except Exception as e:
            logger.error(f"Movement error: {e}")
            return {"status": "error", "error": str(e)}

    async def reset(self) -> Dict[str, Any]:
        """Reset servos to neutral position"""
        result = await self._post("/reset", {})
        if result.get("status") == "ok":
            logger.info("🔄 Servos reset to neutral")
        return result

    async def disable_servos(self) -> Dict[str, Any]:
        """Disable all servos"""
        result = await self._post("/disable", {})
        if result.get("status") == "ok":
            logger.info("🔌 Servos disabled")
        return result

    # ========== Camera Capture ==========

    async def capture_image(self) -> Dict[str, Any]:
        """
        Capture image from camera.

        Returns:
            Dict with:
            - status: "ok" or "error"
            - image: base64-encoded JPEG (if successful)
            - width, height: Image dimensions
            - format: "jpeg"
        """
        try:
            result = await self._get("/camera/capture")
            if result.get("status") == "ok":
                logger.info(f"📷 Captured: {result.get('width')}x{result.get('height')}")
            else:
                logger.warning(f"Camera capture failed: {result.get('error')}")
            return result
        except Exception as e:
            logger.error(f"Camera error: {e}")
            return {"status": "error", "error": str(e)}

    async def get_camera_status(self) -> Dict[str, Any]:
        """Get camera availability and status"""
        return await self._get("/camera/status")

    # ========== Audio Streaming ==========

    async def start_audio_stream(self, callback: Callable[[bytes], None]):
        """
        Start streaming microphone audio from RPi.

        Args:
            callback: Function that receives raw PCM audio bytes (16-bit, 16kHz, mono)

        Note: Requires 'websockets' package installed
        """
        if not WEBSOCKETS_AVAILABLE:
            logger.error("Cannot start audio stream: websockets not installed")
            return

        self._audio_callback = callback
        self._audio_task = asyncio.create_task(self._audio_stream_loop())
        logger.info("🎤 Audio stream started")

    async def _audio_stream_loop(self):
        """Internal: WebSocket audio receive loop"""
        if not WEBSOCKETS_AVAILABLE:
            return

        try:
            import websockets as ws
            async with ws.connect(f"{self.ws_url}/audio/stream") as websocket:
                self._audio_ws = websocket
                logger.info("WebSocket audio stream connected")
                while True:
                    data = await websocket.recv()
                    if self._audio_callback and isinstance(data, bytes):
                        self._audio_callback(data)
        except Exception as e:
            if "websockets.exceptions.ConnectionClosed" not in str(type(e)):
                logger.error(f"Audio stream error: {e}")
            else:
                logger.info("Audio stream closed")
        finally:
            self._audio_ws = None

    async def stop_audio_stream(self):
        """Stop audio streaming"""
        if self._audio_task:
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
            self._audio_task = None
        if self._audio_ws:
            await self._audio_ws.close()
            self._audio_ws = None
        logger.info("🎤 Audio stream stopped")

    # ========== Audio Playback ==========

    async def play_audio(
        self,
        audio_bytes: bytes,
        format: str = "pcm",
        sample_rate: int = 24000
    ) -> Dict[str, Any]:
        """
        Send audio to RPi for playback through speaker.

        Args:
            audio_bytes: Raw audio data
            format: "pcm" (raw) or "wav"
            sample_rate: Sample rate (default 24000 for TTS)

        Returns:
            Dict with status
        """
        try:
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

            result = await self._post("/audio/play", {
                "audio": audio_b64,
                "format": format,
                "sample_rate": sample_rate
            })

            if result.get("status") == "ok":
                logger.debug(f"🔊 Audio queued for playback ({len(audio_bytes)} bytes)")
            return result
        except Exception as e:
            logger.error(f"Play audio error: {e}")
            return {"status": "error", "error": str(e)}

    async def stop_audio(self) -> Dict[str, Any]:
        """Stop any currently playing audio"""
        result = await self._post("/audio/stop", {})
        if result.get("status") == "ok":
            logger.info("🔇 Audio playback stopped")
        return result

    async def get_audio_status(self) -> Dict[str, Any]:
        """Get audio device status"""
        return await self._get("/audio/status")

    # ========== Display Mode Control ==========

    async def set_display_mode(self, mode: str) -> Dict[str, Any]:
        """
        Set display mode.

        Args:
            mode: "eyes", "spectrum", or "off"
        """
        return await self._post("/display/mode", {"mode": mode})

    # ========== Eyes Control ==========

    async def set_eye_state(self, state: str) -> Dict[str, Any]:
        """
        Set eye state.

        Args:
            state: "idle", "listening", "thinking", or "speaking"
        """
        return await self._post("/eyes/state", {"state": state})

    async def set_emotion(self, emotion: str) -> Dict[str, Any]:
        """
        Set eye emotion/expression.

        Args:
            emotion: "default", "happy", "angry", "tired", "surprised", or "confused"
        """
        return await self._post("/eyes/emotion", {"emotion": emotion})

    async def set_look(self, x: float, y: float) -> Dict[str, Any]:
        """
        Set eye look direction.

        Args:
            x: Horizontal look direction (-1 to 1)
            y: Vertical look direction (-1 to 1)
        """
        return await self._post("/eyes/look", {"x": x, "y": y})

    async def blink(self) -> Dict[str, Any]:
        """Trigger eye blink"""
        return await self._post("/eyes/blink", {})

    async def play_animation(self, animation: str) -> Dict[str, Any]:
        """
        Play eye animation.

        Args:
            animation: "laugh" or "confused"
        """
        return await self._post("/eyes/animation", {"animation": animation})

    # ========== Audio Level ==========

    async def set_audio_level(self, level: float, source: str) -> Dict[str, Any]:
        """
        Update audio level for visualization.

        Args:
            level: Audio level (0.0 to 1.0)
            source: "speaker" or "mic"
        """
        return await self._post("/display/audio", {"level": level, "source": source})

    # ========== Face Tracking ==========

    async def set_face_position(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        detected: bool
    ) -> Dict[str, Any]:
        """
        Update face position for eye tracking.

        Args:
            x: Face center X coordinate
            y: Face center Y coordinate
            width: Frame width
            height: Frame height
            detected: Whether face is detected
        """
        return await self._post("/eyes/face", {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "detected": detected
        })

    # ========== Status ==========

    async def get_status(self) -> Dict[str, Any]:
        """Get display status"""
        return await self._get("/display/status")


# ============== Singleton & Helper Functions ==============

_client: Optional[TARSClient] = None


def get_tars_client() -> TARSClient:
    """Get singleton TARS client instance"""
    global _client
    if _client is None:
        _client = TARSClient()
    return _client


async def execute_movement(movements: List[str]) -> str:
    """
    LLM tool: Execute movement sequence.

    Args:
        movements: List of movements to execute

    Returns:
        Human-readable result string
    """
    client = get_tars_client()
    if not await client.is_available():
        return "TARS hardware not available. Cannot move."

    result = await client.move(movements)
    if result.get("status") == "ok":
        return f"Executed movements: {', '.join(movements)}"
    return f"Movement failed: {result.get('error', 'unknown')}"


async def capture_camera_view() -> Dict[str, Any]:
    """
    LLM tool: Capture image from camera.

    Returns:
        Dict with image data or error
    """
    client = get_tars_client()
    if not await client.is_available():
        return {"status": "error", "error": "TARS hardware not available"}
    return await client.capture_image()
