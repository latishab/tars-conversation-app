"""
State synchronization via WebRTC DataChannel.

Manages bidirectional state updates between MacBook AI and RPi robot:

MacBook → RPi:
- Eye state (listening, thinking, speaking)
- Emotion (happy, surprised, etc.)
- Transcripts (user/assistant text)
- Audio level for visualization
- TTS speaking state

RPi → MacBook:
- Battery level
- Connection status
- Movement status
"""

import json
from typing import Dict, Any, Optional, Callable
from loguru import logger


class StateSync:
    """
    Manages state synchronization via WebRTC DataChannel.

    Sends state updates to RPi display and receives status from RPi.
    """

    def __init__(self, send_callback: Optional[Callable[[str], None]] = None):
        """
        Initialize state sync.

        Args:
            send_callback: Function to call to send messages (aiortc_client.send_data_channel_message)
        """
        self._send_callback = send_callback
        self._message_handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {}

    def set_send_callback(self, callback: Callable[[str], None]):
        """Set the callback for sending messages."""
        self._send_callback = callback

    def register_handler(self, message_type: str, handler: Callable[[Dict[str, Any]], None]):
        """
        Register handler for specific message type.

        Args:
            message_type: Message type to handle (e.g., "battery", "connected")
            handler: Function to call when message received
        """
        self._message_handlers[message_type] = handler

    def handle_message(self, message: str):
        """
        Handle incoming message from RPi.

        Args:
            message: JSON string from DataChannel
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type in self._message_handlers:
                self._message_handlers[msg_type](data)
            else:
                logger.debug(f"📡 Received unhandled message type: {msg_type}")

        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse DataChannel message: {e}")
        except Exception as e:
            logger.error(f"❌ Error handling DataChannel message: {e}")

    def send_message(self, data: Dict[str, Any]):
        """
        Send message to RPi via DataChannel.

        Args:
            data: Dictionary to send (will be JSON encoded)
        """
        if self._send_callback:
            try:
                message = json.dumps(data)
                self._send_callback(message)
            except Exception as e:
                logger.error(f"❌ Failed to send DataChannel message: {e}")
        else:
            logger.debug("⚠️  Send callback not set, message not sent")

    # ========== MacBook → RPi Messages ==========

    def send_eye_state(self, state: str):
        """
        Send eye state update.

        Args:
            state: "idle", "listening", "thinking", or "speaking"
        """
        self.send_message({"type": "eye_state", "state": state})
        logger.debug(f"👁️  Sent eye state: {state}")

    def send_emotion(self, emotion: str):
        """
        Send emotion update.

        Args:
            emotion: "default", "happy", "angry", "tired", "surprised", "confused"
        """
        self.send_message({"type": "emotion", "value": emotion})
        logger.debug(f"😊 Sent emotion: {emotion}")

    def send_transcript(self, role: str, text: str):
        """
        Send transcript update.

        Args:
            role: "user" or "assistant"
            text: Transcribed/generated text
        """
        self.send_message({"type": "transcript", "role": role, "text": text})
        logger.debug(f"📝 Sent transcript ({role}): {text[:50]}...")

    def send_audio_level(self, level: float):
        """
        Send audio level for visualization.

        Args:
            level: Audio level (0.0 to 1.0)
        """
        self.send_message({"type": "audio_level", "level": level})

    def send_tts_state(self, speaking: bool):
        """
        Send TTS speaking state.

        Args:
            speaking: True if TTS is currently speaking
        """
        self.send_message({"type": "tts_state", "speaking": speaking})
        logger.debug(f"🔊 Sent TTS state: {'speaking' if speaking else 'idle'}")

    # ========== RPi → MacBook Message Handlers ==========

    def on_battery_update(self, handler: Callable[[int, bool], None]):
        """
        Register handler for battery updates.

        Handler signature: handler(level: int, charging: bool)
        """
        def wrapper(data: Dict[str, Any]):
            level = data.get("level", 0)
            charging = data.get("charging", False)
            handler(level, charging)

        self.register_handler("battery", wrapper)

    def on_connected(self, handler: Callable[[str], None]):
        """
        Register handler for connection updates.

        Handler signature: handler(client: str)
        """
        def wrapper(data: Dict[str, Any]):
            client = data.get("client", "unknown")
            handler(client)

        self.register_handler("connected", wrapper)

    def on_movement_status(self, handler: Callable[[bool, str], None]):
        """
        Register handler for movement status.

        Handler signature: handler(moving: bool, movement: str)
        """
        def wrapper(data: Dict[str, Any]):
            moving = data.get("moving", False)
            movement = data.get("movement", "")
            handler(moving, movement)

        self.register_handler("movement_status", wrapper)
