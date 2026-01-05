"""All logging processors for debugging and monitoring the pipeline.

This module contains processors focused on logging, monitoring, and sending
status updates to the frontend. These are separate from data processing.
"""

import asyncio
import re
import time
from loguru import logger

from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    LLMTextFrame,
    TTSTextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSAudioRawFrame,
    UserImageRequestFrame,
    ErrorFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


# ============================================================================
# DEBUG & MONITORING LOGGERS
# ============================================================================

class DebugLogger(FrameProcessor):
    """General purpose debug logger for non-media frames."""

    def __init__(self, label="Debug"):
        super().__init__()
        self.label = label

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        frame_type = type(frame).__name__
        if "Audio" not in frame_type and "Video" not in frame_type and "Image" not in frame_type:
            # Log the User ID so we can verify they match
            uid = getattr(frame, 'user_id', 'None')
            logger.info(f"🔍 [{self.label}] {frame_type} | User: '{uid}' | Content: {str(frame)[:100]}")

        await self.push_frame(frame, direction)


class TurnDetectionLogger(FrameProcessor):
    """Logs turn detection and VAD events to verify turn analyzer is working."""

    def __init__(self):
        super().__init__()
        self._turn_count = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # Log VAD events (Voice Activity Detection)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            logger.info("🎙️  [TurnDetector] VAD detected: User STARTED speaking")
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            logger.info("🎙️  [TurnDetector] VAD detected: User STOPPED speaking")

        # Log Turn Detection events (Smart Turn Detection)
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._turn_count += 1
            logger.info(f"🗣️  [TurnDetector] Turn #{self._turn_count} STARTED")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            logger.info(f"🗣️  [TurnDetector] Turn #{self._turn_count} ENDED")

        await self.push_frame(frame, direction)

class LatencyLogger(FrameProcessor):
    """Tracks latency from STT transcription to TTS start."""

    # Class-level shared state (all instances share this)
    _shared_state = {
        "_last_transcription_time": None,
        "_last_transcription_text": None,
        "_llm_response_time": None,
        "_conversation_turn": 0
    }

    def __init__(self):
        super().__init__()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        current_time = time.time()
        state = LatencyLogger._shared_state

        # Track when transcription is received (STT complete) - can be UPSTREAM or DOWNSTREAM
        if isinstance(frame, TranscriptionFrame):
            state["_last_transcription_time"] = current_time
            state["_last_transcription_text"] = getattr(frame, 'text', None) or ""
            state["_llm_response_time"] = None  # Reset LLM response time for new turn
            state["_conversation_turn"] += 1
            text_preview = state["_last_transcription_text"][:50] + "..." if len(state["_last_transcription_text"]) > 50 else state["_last_transcription_text"]

        # Track when LLM generates response - DOWNSTREAM
        elif isinstance(frame, LLMTextFrame):
            # Only track the first LLM response time (multiple LLMTextFrames per response)
            if state["_last_transcription_time"] is not None and state["_llm_response_time"] is None:
                state["_llm_response_time"] = current_time

        # Track when TTS starts (calculate total latency) - DOWNSTREAM
        elif isinstance(frame, TTSStartedFrame):
            if state["_last_transcription_time"] is not None:
                total_latency = current_time - state["_last_transcription_time"]

                # Safely get transcription text for logging
                transcription_text = state["_last_transcription_text"] or "(no text)"
                text_preview = transcription_text[:60] + "..." if len(transcription_text) > 60 else transcription_text

                # Calculate breakdown if we have LLM response time
                if state["_llm_response_time"] is not None:
                    stt_to_llm = state["_llm_response_time"] - state["_last_transcription_time"]
                    llm_to_tts = current_time - state["_llm_response_time"]

                    logger.info(
                        f"⏱️  Latency (turn #{state['_conversation_turn']}): "
                        f"Total={total_latency:.3f}s "
                        f"(STT→LLM={stt_to_llm:.3f}s, LLM→TTS={llm_to_tts:.3f}s) | "
                        f"User: \"{text_preview}\""
                    )
                else:
                    logger.info(
                        f"⏱️  Latency (turn #{state['_conversation_turn']}): "
                        f"Total={total_latency:.3f}s (STT→TTS) | "
                        f"User: \"{text_preview}\""
                    )

                # Reset for next turn
                state["_last_transcription_time"] = None
                state["_last_transcription_text"] = None
                state["_llm_response_time"] = None

        await self.push_frame(frame, direction)


# ============================================================================
# USER INTERACTION LOGGERS
# ============================================================================

class TranscriptionLogger(FrameProcessor):
    """Logs transcriptions and sends to frontend."""

    def __init__(self, webrtc_connection=None, client_state=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self.client_state = client_state or {}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames as they pass through the pipeline."""

        await super().process_frame(frame, direction)

        # --- (Logging Logic) ---
        if isinstance(frame, TranscriptionFrame):
            raw_id = getattr(frame, 'user_id', None)
            display_id = raw_id if (raw_id and raw_id != "S1") else self.client_state.get("client_id", "guest")

            logger.info(f"🎤 Transcription [{display_id}]: {frame.text}")

            # Update Frontend
            if self.webrtc_connection:
                self._send_to_frontend("transcription", frame.text, display_id)

        elif isinstance(frame, InterimTranscriptionFrame):
            raw_id = getattr(frame, 'user_id', None)
            display_id = raw_id if (raw_id and raw_id != "S1") else self.client_state.get("client_id", "guest")

            # logger.info(f"🎤 Partial [{display_id}]: {frame.text}")

            # Update Frontend
            if self.webrtc_connection:
                self._send_to_frontend("partial", frame.text, display_id)

        await self.push_frame(frame, direction)

    def _send_to_frontend(self, type_str, text, speaker_id):
        """Helper to send messages to frontend via WebRTC data channel."""
        try:
            if self.webrtc_connection and self.webrtc_connection.is_connected():
                self.webrtc_connection.send_app_message({
                    "type": type_str,
                    "text": text,
                    "speaker_id": speaker_id
                })
        except Exception as e:
            logger.error(f"Error sending {type_str}: {e}")


class AssistantResponseLogger(FrameProcessor):
    """Logs TARS assistant responses and forwards them to the frontend."""

    SENTENCE_REGEX = re.compile(r"(.+?[\.!\?\n])")

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._buffer = ""
        self._max_buffer_chars = 320

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # Debug: Log all frame types to see what's coming through
        frame_type = type(frame).__name__
        if "Audio" not in frame_type and "Video" not in frame_type and "Image" not in frame_type:
            logger.debug(f"🔍 [AssistantLogger] Received {frame_type}")

        if isinstance(frame, (LLMTextFrame, TTSTextFrame)):
            text = getattr(frame, "text", "") or ""
            logger.debug(f"📝 [AssistantLogger] Text frame detected: '{text[:50]}'")
            self._ingest_text(text)

        await self.push_frame(frame, direction)

    def _ingest_text(self, text: str):
        if not text.strip():
            return
        self._buffer += text
        self._emit_complete_sentences()

        if len(self._buffer) > self._max_buffer_chars:
            self._flush_buffer()

    def _emit_complete_sentences(self):
        while True:
            match = self.SENTENCE_REGEX.match(self._buffer)
            if not match:
                break
            sentence = match.group(0).replace("\n", " ").strip()
            self._buffer = self._buffer[match.end():].lstrip()
            if sentence:
                self._log_sentence(sentence)

    def _flush_buffer(self):
        pending = self._buffer.strip()
        if pending:
            self._log_sentence(pending)
        self._buffer = ""

    def _log_sentence(self, sentence: str):
        logger.info(f"🗣️ TARS: {sentence}")
        self._send_to_frontend(sentence)

    def _send_to_frontend(self, text: str):
        if not self.webrtc_connection:
            logger.warning("⚠️ [AssistantLogger] No WebRTC connection available")
            return

        try:
            if self.webrtc_connection.is_connected():
                logger.info(f"📤 [AssistantLogger] Sending to frontend: type=assistant, text='{text[:50]}'")
                self.webrtc_connection.send_app_message(
                    {
                        "type": "assistant",
                        "text": text,
                    }
                )
            else:
                logger.warning("⚠️ [AssistantLogger] WebRTC connection not connected")
        except Exception as exc:  # pragma: no cover
            logger.error(f"❌ [AssistantLogger] Failed to send assistant text to frontend: {exc}")


# ============================================================================
# TTS & VISION LOGGERS
# ============================================================================

class TTSSpeechStateBroadcaster(FrameProcessor):
    """Emits `tts_state` messages whenever the assistant starts or stops speaking."""

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._speaking = False
        self._has_received_audio = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # Priority 1: Explicit start/stop frames (most reliable)
        if isinstance(frame, TTSStartedFrame):
            self._set_state(True)
        elif isinstance(frame, TTSStoppedFrame):
            self._set_state(False)
            self._has_received_audio = False
        elif isinstance(frame, TTSAudioRawFrame):
            # Priority 2: Use first audio frame to detect start (fallback)
            # Only set to started if we haven't already and this is the first audio frame
            if not self._speaking and not self._has_received_audio:
                logger.debug("Detected TTS start via first TTSAudioRawFrame")
                self._set_state(True)
            self._has_received_audio = True
            # Note: We rely on TTSStoppedFrame to detect stop, not audio frame absence

        await self.push_frame(frame, direction)

    def _set_state(self, active: bool):
        if self._speaking == active:
            return

        self._speaking = active
        state = "started" if active else "stopped"
        logger.info(f"TTS state changed: {state}")

        if not self.webrtc_connection:
            return

        try:
            if self.webrtc_connection.is_connected():
                self.webrtc_connection.send_app_message(
                    {
                        "type": "tts_state",
                        "state": state,
                    }
                )
                logger.debug(f"Sent TTS state message: {state}")
        except Exception as exc:  # pragma: no cover
            logger.error(f"Failed to send TTS state: {exc}")


class VisionLogger(FrameProcessor):
    """Logs vision processing events and Moondream activity."""

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._video_frame_count = 0
        self._last_video_frame_time = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        current_time = time.time()

        frame_type = type(frame).__name__
        direction_str = "UPSTREAM" if direction == FrameDirection.UPSTREAM else "DOWNSTREAM"

        # Log vision request frames
        if isinstance(frame, UserImageRequestFrame):
            user_id = getattr(frame, 'user_id', 'unknown')
            question = getattr(frame, 'text', 'unknown')
            logger.info(f"👁️ Vision request received [{direction_str}]: user_id={user_id}, question={question}")
            self._last_vision_request_time = current_time  # Track when vision was requested
            self._vision_request_count = getattr(self, '_vision_request_count', 0) + 1
            logger.info(f"📊 Vision request #{self._vision_request_count} - waiting for video frames and Moondream response...")

            # Send status to frontend
            if self.webrtc_connection:
                try:
                    if self.webrtc_connection.is_connected():
                        self.webrtc_connection.send_app_message({
                            "type": "vision",
                            "status": "requested",
                            "question": question
                        })
                except Exception as e:
                    logger.debug(f"Error sending vision status: {e}")

        elif 'video' in frame_type.lower() or 'image' in frame_type.lower() or 'vision' in frame_type.lower():
            # Only log at info level if we're actively processing a vision request
            is_vision_active = hasattr(self, '_last_vision_request_time') and self._last_vision_request_time is not None
            if is_vision_active:
                time_since_request = current_time - self._last_vision_request_time
                if time_since_request < 5:  # Only log during active vision processing (5 seconds)
                    logger.debug(f"📷 Vision-related frame [{direction_str}]: {frame_type}")
            else:
                # Otherwise, only log at debug level (won't show unless debug logging is enabled)
                logger.debug(f"📷 Vision-related frame [{direction_str}]: {frame_type}")

        # Log frames with image attribute only at debug level
        elif hasattr(frame, 'image'):
            logger.debug(f"📷 Frame with image attribute [{direction_str}]: {frame_type}")

        # Log any frame that might be a vision response by checking attributes
        elif hasattr(frame, 'user_id') and hasattr(frame, 'text'):
            user_id = getattr(frame, 'user_id', 'unknown')
            text = getattr(frame, 'text', '')
            if 'vision' in frame_type.lower() or 'image' in frame_type.lower() or 'moondream' in frame_type.lower():
                logger.info(f"✅ Vision response frame [{direction_str}]: {frame_type}, user_id={user_id}")
                logger.info(f"   Response: {text[:200]}..." if len(text) > 200 else f"   Response: {text}")

        # Log LLM text frames that might contain vision responses
        # Moondream responses come through as LLMTextFrame with vision context
        elif isinstance(frame, LLMTextFrame):
            text = getattr(frame, 'text', '')
            vision_keywords = ['see', 'visible', 'camera', 'image', 'showing', 'appears', 'looks like', 'dimly lit', 'desk', 'monitor', 'room', 'window', 'mug', 'laptop', 'coffee', 'analyzing', 'processing']

            # Check if this is a vision response (either from keywords or if we recently requested vision)
            is_vision_response = False
            if hasattr(self, '_last_vision_request_time'):
                time_since_request = current_time - self._last_vision_request_time
                if time_since_request < 10:  # Within 10 seconds of vision request
                    is_vision_response = True
                    logger.info(f"✅ Vision response received [{direction_str}] (within {time_since_request:.1f}s of request): {text[:200]}..." if len(text) > 200 else f"✅ Vision response: {text}")

            if text and any(keyword in text.lower() for keyword in vision_keywords) and not is_vision_response:
                logger.info(f"✅ Possible vision response in LLM text [{direction_str}]: {text[:200]}..." if len(text) > 200 else f"✅ Possible vision response: {text}")

        # Log errors
        elif isinstance(frame, ErrorFrame):
            error_msg = getattr(frame, 'error', str(frame))
            if 'vision' in error_msg.lower() or 'moondream' in error_msg.lower() or 'image' in error_msg.lower():
                logger.error(f"❌ Vision error: {error_msg}")

                # Send error to frontend
                if self.webrtc_connection:
                    try:
                        if self.webrtc_connection.is_connected():
                            self.webrtc_connection.send_app_message({
                                "type": "vision",
                                "status": "error",
                                "error": str(error_msg)
                            })
                    except Exception as e:
                        logger.debug(f"Error sending vision error: {e}")

        # Check for actual video frames (exclude audio frames)
        # Check for video frames - be specific to avoid false positives
        is_video_frame = False

        # Explicitly exclude audio frames
        if 'audio' in frame_type.lower():
            is_video_frame = False
        # Check for actual video frame types
        elif 'VideoRawFrame' in frame_type or 'InputVideoRawFrame' in frame_type:
            is_video_frame = True
        elif 'video' in frame_type.lower() and 'audio' not in frame_type.lower():
            # Only if it's a video frame and not an audio frame
            is_video_frame = True
        elif hasattr(frame, 'video') and not hasattr(frame, 'audio'):
            # Has video attribute but not audio
            is_video_frame = True
        elif hasattr(frame, 'image') and hasattr(frame, 'user_id'):
            # User image request/response frames
            is_video_frame = True

        # Only log actual video frames, not audio frames
        if is_video_frame:
            self._video_frame_count += 1
            self._last_video_frame_time = current_time
            # Only log every 100 frames to reduce spam significantly
            if self._video_frame_count % 100 == 0:
                logger.debug(f"🎥 Video frames streaming [{direction_str}]: {self._video_frame_count} frames received")

        # Log frame count summary every 30 seconds (less frequent)
        if not hasattr(self, '_last_summary_time'):
            self._last_summary_time = current_time
        elif current_time - self._last_summary_time >= 30:
            if self._video_frame_count > 0:
                logger.debug(f"📊 Video stream: {self._video_frame_count} frames in last 30 seconds")
            else:
                logger.warning(f"⚠️ No video frames detected in last 30 seconds!")
            self._video_frame_count = 0
            self._last_summary_time = current_time

        await self.push_frame(frame, direction)
