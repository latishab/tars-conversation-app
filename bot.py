"""Bot pipeline setup and execution."""

import asyncio
import json
import os
import logging

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import LLMRunFrame, UserImageRequestFrame
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.moondream.vision import MoondreamService
from pipecat.services.speechmatics.stt import SpeechmaticsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.qwen.llm import QwenLLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from loguru import logger

from config import (
    SPEECHMATICS_API_KEY,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    QWEN_API_KEY,
    QWEN_MODEL,
)
from processors import SimpleTranscriptionLogger
from config import MEM0_API_KEY
from memory import Mem0Wrapper  # required

if not MEM0_API_KEY:
    raise RuntimeError("MEM0_API_KEY is required but not set.")

_mem0 = Mem0Wrapper(api_key=MEM0_API_KEY)


async def fetch_user_image(params: FunctionCallParams):
    """Fetch the user image for vision analysis.

    When called, this function pushes a UserImageRequestFrame upstream to the
    transport. As a result, the transport will request the user image and push a
    UserImageRawFrame downstream to Moondream for processing.
    """
    user_id = params.arguments["user_id"]
    question = params.arguments["question"]
    logger.info(f"📸 Requesting image with user_id={user_id}, question={question}")

    # Request a user image frame. We don't want the requested
    # image to be added to the context because we will process it with
    # Moondream.
    await params.llm.push_frame(
        UserImageRequestFrame(user_id=user_id, text=question, append_to_context=False),
        FrameDirection.UPSTREAM,
    )

    await params.result_callback(None)


async def run_bot(webrtc_connection):
    """Run the bot pipeline with the given WebRTC connection"""
    logger.info("Starting bot pipeline for WebRTC connection...")

    try:
        # Initialize VAD and Smart Turn Detection (lazy import to handle missing dependencies)
        logger.info("Initializing VAD and Smart Turn Detection...")
        vad_analyzer = None
        turn_analyzer = None
        try:
            from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
            
            vad_analyzer = SileroVADAnalyzer(params=VADParams(stop_secs=0.2))
            turn_analyzer = LocalSmartTurnAnalyzerV3(
                params=SmartTurnParams(
                    stop_secs=3.0,
                    pre_speech_ms=0.0,
                    max_duration_secs=8.0
                )
            )
            logger.info("✓ VAD and Smart Turn Detection initialized")
        except ImportError as e:
            logger.warning(f"Smart Turn dependencies not installed: {e}")
            logger.warning("Install with: pip install 'pipecat-ai[local-smart-turn-v3,silero]'")
            logger.warning("Falling back to transport without Smart Turn Detection")
        except Exception as e:
            logger.error(f"Failed to initialize VAD/Smart Turn: {e}", exc_info=True)
            logger.warning("Falling back to transport without Smart Turn Detection")

        # Create SmallWebRTC transport from the connection
        transport_params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_in_enabled=True,
            video_out_enabled=True,
            video_out_is_live=True,
        )
        
        # Add VAD and Smart Turn if available
        if vad_analyzer:
            transport_params.vad_analyzer = vad_analyzer
        if turn_analyzer:
            transport_params.turn_analyzer = turn_analyzer
            logger.info("✓ Smart Turn Detection enabled - will prevent interruptions")
        else:
            logger.warning("⚠ Smart Turn Detection NOT enabled - bot may interrupt users")

        pipecat_transport = SmallWebRTCTransport(
            webrtc_connection=webrtc_connection,
            params=transport_params,
        )

        # Initialize Speechmatics STT with speaker diarization
        logger.info("Initializing Speechmatics STT with speaker diarization (max 2 speakers)...")
        stt = None
        try:
            # Disable Speechmatics VAD when Smart Turn is enabled to avoid conflicts
            # Smart Turn handles turn detection, so we don't need Speechmatics' VAD
            stt_params = SpeechmaticsSTTService.InputParams(
                language=Language.EN,
                enable_diarization=True,
                max_speakers=2,
            )
            # If Smart Turn is enabled, disable Speechmatics' internal VAD
            if turn_analyzer:
                stt_params.enable_vad = False
                logger.info("Disabled Speechmatics VAD (using Smart Turn instead)")
            
            stt = SpeechmaticsSTTService(
                api_key=SPEECHMATICS_API_KEY,
                params=stt_params,
            )
            logger.info("✓ Speechmatics STT initialized with speaker diarization (max 2 speakers)")
        except Exception as e:
            error_msg = str(e).lower()
            if "quota" in error_msg or "4005" in error_msg or "quota_exceeded" in error_msg:
                logger.error("❌ Speechmatics API quota exceeded!")
                logger.error("   Your Speechmatics API quota has been exceeded.")
                logger.error("   Please check your quota at: https://portal.speechmatics.com/")
                logger.error("   You may need to wait for your quota to reset or upgrade your plan.")
            else:
                logger.error(f"Failed to initialize Speechmatics: {e}", exc_info=True)
            return

        # Initialize ElevenLabs TTS with Flash model
        logger.info("Initializing ElevenLabs TTS...")
        tts = None
        try:
            tts = ElevenLabsTTSService(
                api_key=ELEVENLABS_API_KEY,
                voice_id=ELEVENLABS_VOICE_ID,
                model="eleven_flash_v2_5"
            )
            logger.info("✓ ElevenLabs TTS initialized")
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}", exc_info=True)
            return

        # Initialize Qwen LLM service
        logger.info("Initializing Qwen LLM...")
        if not QWEN_API_KEY or len(QWEN_API_KEY) < 10:
            logger.error(f"QWEN_API_KEY appears invalid (length: {len(QWEN_API_KEY) if QWEN_API_KEY else 0}). Please check your .env.local file.")
            return
        logger.info(f"Using Qwen API key starting with: {QWEN_API_KEY[:8]}... (model: {QWEN_MODEL})")
        llm = None
        try:
            llm = QwenLLMService(
                api_key=QWEN_API_KEY,
                model=QWEN_MODEL
            )
            # Register function for image requests
            llm.register_function("fetch_user_image", fetch_user_image)
            logger.info(f"✓ Qwen LLM initialized with model: {QWEN_MODEL}")
        except Exception as e:
            logger.error(f"Failed to initialize Qwen LLM: {e}", exc_info=True)
            logger.error("This might be due to an invalid API key. Please check your QWEN_API_KEY in .env.local")
            return

        # Initialize Moondream vision service
        logger.info("Initializing Moondream vision service...")
        try:
            moondream = MoondreamService(
                model="vikhyatk/moondream2",
                device="mps"
            )
            logger.info("✓ Moondream vision service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Moondream: {e}", exc_info=True)
            logger.error("Moondream initialization failed. Make sure pipecat-ai[moondream] is installed.")
            return

        if not stt or not tts or not llm:
            logger.error("Failed to initialize services. Cannot start bot.")
            return

        # Create LLM context and aggregator pair
        logger.info("Creating LLM context aggregator pair...")

        # Load system prompt from character.json
        character_file = os.path.join(os.path.dirname(__file__), "character.json")
        try:
            with open(character_file, "r", encoding="utf-8") as f:
                system_prompt = json.load(f)
            logger.info(f"✓ Loaded character prompt from {character_file}")
        except FileNotFoundError:
            logger.warning(f"character.json not found at {character_file}, using default prompt")
            system_prompt = {
                "role": "system",
                "content": "You are a helpful AI assistant with vision capabilities. You can describe images from the user's camera. Respond naturally and conversationally to user queries. Your output will be converted to audio so don't include special characters in your answers."
            }
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing character.json: {e}, using default prompt")
            system_prompt = {
                "role": "system",
                "content": "You are a helpful AI assistant with vision capabilities. You can describe images from the user's camera. Respond naturally and conversationally to user queries. Your output will be converted to audio so don't include special characters in your answers."
            }

        # Create function schema for image fetching
        fetch_image_function = FunctionSchema(
            name="fetch_user_image",
            description="Called when the user requests a description of their camera feed or wants to know what they're showing on camera",
            properties={
                "user_id": {
                    "type": "string",
                    "description": "The ID of the user to grab the image from",
                },
                "question": {
                    "type": "string",
                    "description": "The question that the user is asking about the image",
                },
            },
            required=["user_id", "question"],
        )
        tools = ToolsSchema(standard_tools=[fetch_image_function])

        messages = [system_prompt]
        context = LLMContext(messages, tools)
        context_aggregator = LLMContextAggregatorPair(context)

        # Create simple transcription logger with WebRTC connection for sending messages
        transcription_logger = SimpleTranscriptionLogger(webrtc_connection=webrtc_connection)

        # Create pipeline with ParallelPipeline for Qwen + Moondream
        # Pipeline flow:
        #   transport.input() -> STT -> logger -> context_aggregator.user() ->
        #   ParallelPipeline([llm], [moondream]) -> TTS ->
        #   transport.output() -> context_aggregator.assistant()
        #
        # Qwen LLM and Moondream process in parallel:
        # - Qwen handles text responses and can call fetch_user_image function
        # - Moondream processes UserImageRawFrame requests from Qwen
        logger.info("Creating audio/video pipeline with Qwen + Moondream...")

        # Build parallel pipeline branches
        parallel_branches = [llm]  # Qwen LLM branch
        if moondream:
            parallel_branches.append(moondream)  # Moondream vision branch

        pipeline = Pipeline([
            pipecat_transport.input(),      # Receives all frames (audio and video)
            stt,                            # Speech to text
            transcription_logger,           # Log transcriptions
            context_aggregator.user(),      # Process user input into context
            ParallelPipeline(parallel_branches),  # Parallel processing: Qwen + Moondream
            tts,                            # Text to speech
            pipecat_transport.output(),     # Sends TTS audio to transport
            context_aggregator.assistant(), # Process assistant response into context
        ])

        # Store client_id and task reference for event handlers
        client_id_storage = {"client_id": None}
        task_ref = {"task": None}

        # Set up event handlers before creating task
        @pipecat_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Pipecat Client connected")
            # Capture camera video stream
            try:
                await pipecat_transport.capture_participant_video("camera")
                logger.info("Camera video capture started")
            except Exception as e:
                logger.error(f"Error capturing camera video: {e}", exc_info=True)

            # Get client ID for function calls
            # For SmallWebRTC, we'll use a simple identifier
            client_id_storage["client_id"] = "user_1"

            # Augment context with recalled memories for this user
            try:
                if _mem0 and _mem0.enabled:
                    recalled = _mem0.recall(user_id=client_id_storage["client_id"], limit=8)
                    if recalled:
                        memory_text = "\n".join(f"- {m}" for m in recalled)
                        messages.append({
                            "role": "system",
                            "content": (
                                "The following are previously stored facts about the user. "
                                "Use them to personalize responses when helpful, but do not repeat them verbatim unless asked.\n"
                                f"{memory_text}"
                            ),
                        })
                        logger.info(f"✓ Injected {len(recalled)} recalled memories into context")
            except Exception as e:  # pragma: no cover
                logger.debug(f"Skipping memory recall injection due to error: {e}")

            # Test if we can send a message
            try:
                if webrtc_connection.is_connected():
                    logger.info("WebRTC connection is ready for sending messages")
                    # Test message
                    webrtc_connection.send_app_message({
                        "type": "system",
                        "message": "Connection established"
                    })
                else:
                    logger.warning("WebRTC connection not ready yet")
            except Exception as e:
                logger.error(f"Error sending test message: {e}", exc_info=True)

            # Kick off the conversation with introduction
            if task_ref["task"]:
                messages.append({
                    "role": "system",
                    "content": f"Please introduce yourself to the user. Use '{client_id_storage['client_id']}' as the user ID during function calls.",
                })
                await task_ref["task"].queue_frames([LLMRunFrame()])

        @pipecat_transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Pipecat Client disconnected")
            if task_ref["task"]:
                await task_ref["task"].cancel()

        # Helper function to detect and handle Speechmatics retryable errors
        def handle_speechmatics_error(error: Exception) -> bool:
            """Handle Speechmatics errors and return True if retryable, False otherwise."""
            error_str = str(error).lower()
            error_code = None
            
            # Extract error code from error message
            if "4005" in error_str or "quota_exceeded" in error_str or "concurrent quota exceeded" in error_str:
                error_code = 4005
            elif "4013" in error_str or "job_error" in error_str:
                error_code = 4013
            elif "1011" in error_str or "internal_error" in error_str:
                error_code = 1011
            
            # Check if this is a retryable error
            retryable_errors = [4005, 4013, 1011]
            if error_code in retryable_errors:
                logger.warning(f"⚠️ Speechmatics retryable error ({error_code}) detected: {error}")
                logger.info("   Per Speechmatics docs, client should retry after 5-10 seconds...")
                logger.info("   Note: The service will need to be restarted after quota issues are resolved.")
                
                # Send error message to frontend
                try:
                    if webrtc_connection.is_connected():
                        if error_code == 4005:
                            webrtc_connection.send_app_message({
                                "type": "error",
                                "message": "Speechmatics quota exceeded. Please check your API quota and wait 5-10 seconds before retrying."
                            })
                        else:
                            webrtc_connection.send_app_message({
                                "type": "error",
                                "message": f"Speechmatics error ({error_code}). Will retry after delay."
                            })
                except:
                    pass
                
                return True
            elif "quota" in error_str or "4005" in error_str:
                logger.error("❌ Speechmatics quota exceeded!")
                logger.error("   Your Speechmatics API quota has been exceeded.")
                logger.error("   Please check your quota at: https://portal.speechmatics.com/")
                logger.error("   Wait 5-10 seconds before retrying the connection.")
                try:
                    if webrtc_connection.is_connected():
                        webrtc_connection.send_app_message({
                            "type": "error",
                            "message": "Speechmatics quota exceeded. Please check your API quota."
                        })
                except:
                    pass
            
            return False

        # Create and run pipeline task
        task = PipelineTask(pipeline)
        task_ref["task"] = task
        runner = PipelineRunner(handle_sigint=False)

        logger.info("Starting pipeline runner...")
        
        # Run the pipeline with error handling for Speechmatics quota issues
        try:
            await runner.run(task)
        except Exception as pipeline_error:
            # Check if this is a Speechmatics quota error
            if handle_speechmatics_error(pipeline_error):
                logger.info("   Pipeline stopped due to retryable Speechmatics error.")
                logger.info("   Please wait 5-10 seconds and try reconnecting.")
            else:
                # Re-raise if it's not a handled error
                raise

    except Exception as e:
        # Handle initialization errors
        if handle_speechmatics_error(e):
            logger.info("   Bot initialization stopped due to retryable Speechmatics error.")
        else:
            error_str = str(e).lower()
            if "quota" in error_str or "4005" in error_str or "quota_exceeded" in error_str:
                logger.error("❌ Speechmatics quota exceeded!")
                logger.error("   Your Speechmatics API quota has been exceeded.")
                logger.error("   Please check your quota at: https://portal.speechmatics.com/")
            else:
                logger.error(f"Error in bot pipeline: {e}", exc_info=True)

