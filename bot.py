"""Bot pipeline setup and execution."""

import asyncio
import json
import os
import logging

from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
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
from processors import (
    SimpleTranscriptionLogger,
    AssistantResponseLogger,
    TTSSpeechStateBroadcaster,
    VisionLogger,
    SilenceFilter,
    InputAudioFilter,
)
from config import MEM0_API_KEY
from memory import Mem0Wrapper  # required
from character.prompts import (
    load_persona_ini,
    load_tars_json,
    build_tars_system_prompt,
    get_introduction_instruction,
)
from modules.module_tools import (
    fetch_user_image,
    set_speaking_rate,
    create_fetch_image_schema,
    create_speaking_rate_schema,
    get_tts_speed_storage,
)

if not MEM0_API_KEY:
    raise RuntimeError("MEM0_API_KEY is required but not set.")

_mem0 = Mem0Wrapper(api_key=MEM0_API_KEY)


async def _cleanup_services(service_refs: dict):
    """Cleanup STT and TTS services to prevent connection leaks."""
    if service_refs.get("stt"):
        try:
            stt_service = service_refs["stt"]
            if hasattr(stt_service, 'cleanup'):
                await stt_service.cleanup()
            elif hasattr(stt_service, 'close'):
                await stt_service.close()
            elif hasattr(stt_service, '_client') and stt_service._client:
                client = stt_service._client
                if hasattr(client, 'close'):
                    await client.close()
                elif hasattr(client, 'websocket') and client.websocket:
                    await client.websocket.close()
            logger.info("✓ STT service cleaned up")
        except Exception as e:
            logger.debug(f"Error cleaning up STT service: {e}")
    
    if service_refs.get("tts"):
        try:
            tts_service = service_refs["tts"]
            if hasattr(tts_service, 'cleanup'):
                await tts_service.cleanup()
            elif hasattr(tts_service, 'close'):
                await tts_service.close()
            logger.info("✓ TTS service cleaned up")
        except Exception as e:
            logger.debug(f"Error cleaning up TTS service: {e}")


async def run_bot(webrtc_connection):
    """Run the bot pipeline with the given WebRTC connection"""
    logger.info("Starting bot pipeline for WebRTC connection...")
    
    # Initialize service references early for cleanup
    service_refs = {"stt": None, "tts": None}

    try:
        # Initialize VAD and Smart Turn Detection
        logger.info("Initializing VAD and Smart Turn Detection...")
        vad_analyzer = None
        turn_analyzer = None
        try:
            from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
            
            vad_analyzer = SileroVADAnalyzer(params=VADParams(
                stop_secs=0.8,  # Natural pauses
                start_secs=0.2,
                confidence=0.5
            ))
            turn_analyzer = LocalSmartTurnAnalyzerV3(
                params=SmartTurnParams(
                    stop_secs=1.0,
                    pre_speech_ms=200.0,
                    max_duration_secs=15.0
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

        # Create SmallWebRTC transport (audio + video)
        transport_params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_in_enabled=True,  # Enable video input for camera feed
            video_out_enabled=False,
            video_out_is_live=False,
        )
        
        # Add VAD and Smart Turn if available
        if vad_analyzer:
            transport_params.vad_analyzer = vad_analyzer
        if turn_analyzer:
            transport_params.turn_analyzer = turn_analyzer
            logger.info("✓ Smart Turn Detection enabled - will prevent interruptions")
        else:
            logger.warning("⚠ Smart Turn Detection NOT enabled - bot may interrupt users")
        
        logger.info("✓ Video input enabled - camera feed will be available for vision analysis")

        pipecat_transport = SmallWebRTCTransport(
            webrtc_connection=webrtc_connection,
            params=transport_params,
        )

        # Initialize Speechmatics STT with speaker diarization
        logger.info("Initializing Speechmatics STT with speaker diarization (max 2 speakers)...")
        stt = None
        try:
            stt_params = SpeechmaticsSTTService.InputParams(
                language=Language.EN,
                enable_diarization=True,
                max_speakers=2,
            )
            # Disable Speechmatics VAD when Smart Turn is enabled
            if turn_analyzer:
                stt_params.enable_vad = False
                logger.info("Disabled Speechmatics VAD (using Smart Turn instead)")
            
            stt = SpeechmaticsSTTService(
                api_key=SPEECHMATICS_API_KEY,
                params=stt_params,
            )
            service_refs["stt"] = stt  # Store for cleanup
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

        # Initialize ElevenLabs TTS
        logger.info("Initializing ElevenLabs TTS...")
        tts = None
        try:
            # Validate API key before creating service
            if not ELEVENLABS_API_KEY or len(ELEVENLABS_API_KEY) < 10:
                logger.error(f"ELEVENLABS_API_KEY appears invalid (length: {len(ELEVENLABS_API_KEY) if ELEVENLABS_API_KEY else 0}). Please check your .env.local file.")
                return
            
            logger.info(f"Using ElevenLabs API key starting with: {ELEVENLABS_API_KEY[:8]}...")
            logger.info(f"Using voice ID: {ELEVENLABS_VOICE_ID}")
            
            tts = ElevenLabsTTSService(
                api_key=ELEVENLABS_API_KEY,
                voice_id=ELEVENLABS_VOICE_ID,
                model="eleven_flash_v2_5",
                output_format="pcm_24000",
                enable_word_timestamps=False
            )
            service_refs["tts"] = tts
            tts_speed_storage = get_tts_speed_storage()
            tts_speed_storage["tts_service"] = tts
            try:
                if hasattr(tts, 'speed'):
                    tts.speed = tts_speed_storage["speed"]
                    logger.info(f"✓ ElevenLabs TTS service created (speed: {tts_speed_storage['speed']}x)")
                else:
                    logger.info("✓ ElevenLabs TTS service created")
            except Exception:
                logger.info("✓ ElevenLabs TTS service created")
            
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}", exc_info=True)
            logger.error("This might be due to an invalid API key or network issue.")
            logger.error("Please check your ELEVENLABS_API_KEY in .env.local")
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
            llm.register_function("fetch_user_image", fetch_user_image)
            llm.register_function("set_speaking_rate", set_speaking_rate)
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

        # Load character files from character directory
        character_dir = os.path.join(os.path.dirname(__file__), "character")
        persona_file = os.path.join(character_dir, "persona.ini")
        tars_file = os.path.join(character_dir, "TARS.json")
        
        # Load persona parameters and TARS character data
        persona_params = load_persona_ini(persona_file)
        if persona_params:
            logger.info(f"✓ Loaded persona parameters from {persona_file}")
        
        tars_data = load_tars_json(tars_file)
        if tars_data:
            logger.info(f"✓ Loaded TARS character data from {tars_file}")
        
        # Build system prompt from character data
        if persona_params or tars_data:
            system_prompt = build_tars_system_prompt(persona_params, tars_data)
            logger.info("✓ Built system prompt from character files")
        else:
            # Fallback to character.json if character files not found
            character_file = os.path.join(os.path.dirname(__file__), "character.json")
            try:
                with open(character_file, "r", encoding="utf-8") as f:
                    system_prompt = json.load(f)
                logger.info(f"✓ Loaded character prompt from {character_file}")
            except FileNotFoundError:
                logger.warning(f"Character files not found, using default prompt")
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

        # Create function schemas
        fetch_image_function = create_fetch_image_schema()
        rate_function = create_speaking_rate_schema()
        
        tools = ToolsSchema(standard_tools=[fetch_image_function, rate_function])

        messages = [system_prompt]
        context = LLMContext(messages, tools)
        context_aggregator = LLMContextAggregatorPair(context)

        # Create loggers with WebRTC connection for sending messages
        transcription_logger = SimpleTranscriptionLogger(webrtc_connection=webrtc_connection)
        assistant_logger = AssistantResponseLogger(webrtc_connection=webrtc_connection)
        tts_state_broadcaster = TTSSpeechStateBroadcaster(webrtc_connection=webrtc_connection)
        vision_logger = VisionLogger(webrtc_connection=webrtc_connection)

        # Create pipeline: Qwen + Moondream process in parallel
        logger.info("Creating audio/video pipeline with Qwen + Moondream...")

        parallel_branches = [llm]
        if moondream:
            parallel_branches.append(moondream)

        pipeline = Pipeline([
            pipecat_transport.input(),
            stt,
            transcription_logger,
            vision_logger,  # Log all vision-related frames (requests and responses)
            context_aggregator.user(),
            ParallelPipeline(parallel_branches),
            assistant_logger,
            SilenceFilter(),
            InputAudioFilter(),
            tts,
            tts_state_broadcaster,
            pipecat_transport.output(),
            context_aggregator.assistant(),
        ])

        client_id_storage = {"client_id": None}
        task_ref = {"task": None}
        service_refs["stt"] = stt
        service_refs["tts"] = tts
        @pipecat_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Pipecat Client connected")
            client_id_storage["client_id"] = "user_1"

            # Inject recalled memories
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

            # Test connection
            try:
                if webrtc_connection.is_connected():
                    logger.info("WebRTC connection is ready for sending messages")
                    webrtc_connection.send_app_message({
                        "type": "system",
                        "message": "Connection established"
                    })
                else:
                    logger.warning("WebRTC connection not ready yet")
            except Exception as e:
                logger.error(f"Error sending test message: {e}", exc_info=True)

            # Send introduction
            if task_ref["task"]:
                verbosity_level = persona_params.get("verbosity", 10) if persona_params else 10
                if isinstance(verbosity_level, str):
                    try:
                        verbosity_level = int(verbosity_level)
                    except ValueError:
                        verbosity_level = 10
                
                intro_instruction = get_introduction_instruction(
                    client_id_storage['client_id'],
                    verbosity_level
                )
                messages.append(intro_instruction)
                await task_ref["task"].queue_frames([LLMRunFrame()])

        @pipecat_transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Pipecat Client disconnected")
            if task_ref["task"]:
                await task_ref["task"].cancel()
            await _cleanup_services(service_refs)

        def handle_speechmatics_error(error: Exception) -> bool:
            """Handle Speechmatics errors. Returns True if retryable."""
            error_str = str(error).lower()
            error_code = None
            if "4005" in error_str or "quota_exceeded" in error_str or "concurrent quota exceeded" in error_str:
                error_code = 4005
            elif "4013" in error_str or "job_error" in error_str:
                error_code = 4013
            elif "1011" in error_str or "internal_error" in error_str:
                error_code = 1011
            
            retryable_errors = [4005, 4013, 1011]
            if error_code in retryable_errors:
                logger.warning(f"⚠️ Speechmatics retryable error ({error_code}) detected: {error}")
                logger.info("   Retry after 5-10 seconds...")
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

        task = PipelineTask(pipeline)
        task_ref["task"] = task
        runner = PipelineRunner(handle_sigint=False)

        logger.info("Starting pipeline runner...")
        
        try:
            await runner.run(task)
        except Exception as pipeline_error:
            if handle_speechmatics_error(pipeline_error):
                logger.info("   Pipeline stopped due to retryable Speechmatics error.")
            else:
                raise
        finally:
            await _cleanup_services(service_refs)

    except Exception as e:
        if handle_speechmatics_error(e):
            logger.info("   Bot initialization stopped due to retryable Speechmatics error.")
        else:
            error_str = str(e).lower()
            if "quota" in error_str or "4005" in error_str or "quota_exceeded" in error_str:
                logger.error("❌ Speechmatics quota exceeded!")
                logger.error("   Please check your quota at: https://portal.speechmatics.com/")
            else:
                logger.error(f"Error in bot pipeline: {e}", exc_info=True)
    finally:
        await _cleanup_services(service_refs)

