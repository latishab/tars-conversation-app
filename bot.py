"""Bot pipeline setup and execution."""

import asyncio
import json
import os
import logging
import uuid

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
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from loguru import logger

from config import (
    SPEECHMATICS_API_KEY,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    DEEPINFRA_API_KEY,
    DEEPINFRA_BASE_URL,
    DEEPINFRA_MODEL,
    DEEPINFRA_GATING_MODEL,
)
from processors import (
    SimpleTranscriptionLogger,
    AssistantResponseLogger,
    TTSSpeechStateBroadcaster,
    VisionLogger,
    LatencyLogger,
    SilenceFilter,
    InputAudioFilter,
    InterventionGating,
    VisualObserver,
)
from config import MEM0_API_KEY
from memory import Mem0Wrapper
from character.prompts import (
    load_persona_ini,
    load_tars_json,
    build_tars_system_prompt,
    get_introduction_instruction,
)
from modules.module_tools import (
    fetch_user_image,
    adjust_persona_parameter,
    create_fetch_image_schema,
    create_adjust_persona_schema,
    create_identity_schema,  # NEW
    get_persona_storage,
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
    
    # 1. Start with a unique Guest ID for this session
    # We use a mutable dict so inner functions can update the ID
    session_id = str(uuid.uuid4())[:8]
    client_state = {"client_id": f"guest_{session_id}"}
    logger.info(f"Starting session as: {client_state['client_id']}")

    service_refs = {"stt": None, "tts": None}

    # Define error handler EARLY
    def handle_speechmatics_error(error: Exception) -> bool:
        """Handle Speechmatics errors. Returns True if retryable."""
        error_str = str(error).lower()
        if "quota" in error_str or "4005" in error_str:
            logger.error("❌ Speechmatics quota exceeded!")
            return False
        return False

    try:
        # Initialize VAD and Smart Turn Detection
        logger.info("Initializing VAD and Smart Turn Detection...")
        vad_analyzer = None
        turn_analyzer = None
        try:
            from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
            
            vad_analyzer = SileroVADAnalyzer(params=VADParams(stop_secs=0.8, start_secs=0.2, confidence=0.5))
            turn_analyzer = LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=1.0, pre_speech_ms=200.0))
            logger.info("✓ VAD and Smart Turn Detection initialized")
        except ImportError:
            logger.warning("Smart Turn dependencies not installed.")

        # Create SmallWebRTC transport
        transport_params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_in_enabled=True,
            video_out_enabled=False,
            video_out_is_live=False,
        )
        
        if vad_analyzer: transport_params.vad_analyzer = vad_analyzer
        if turn_analyzer: transport_params.turn_analyzer = turn_analyzer
        
        pipecat_transport = SmallWebRTCTransport(
            webrtc_connection=webrtc_connection,
            params=transport_params,
        )

        # Initialize Speechmatics STT
        logger.info("Initializing Speechmatics STT...")
        stt = None
        try:
            stt_params = SpeechmaticsSTTService.InputParams(
                language=Language.EN,
                enable_diarization=True,
                max_speakers=2,
            )
            if turn_analyzer: stt_params.enable_vad = False
            
            stt = SpeechmaticsSTTService(
                api_key=SPEECHMATICS_API_KEY,
                params=stt_params,
            )
            service_refs["stt"] = stt
            logger.info("✓ Speechmatics STT initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Speechmatics: {e}")
            return

        # Initialize ElevenLabs TTS
        logger.info("Initializing ElevenLabs TTS...")
        tts = None
        try:
            tts = ElevenLabsTTSService(
                api_key=ELEVENLABS_API_KEY,
                voice_id=ELEVENLABS_VOICE_ID,
                model="eleven_flash_v2_5",
                output_format="pcm_24000",
                enable_word_timestamps=False
            )
            service_refs["tts"] = tts
            logger.info("✓ ElevenLabs TTS service created")
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}")
            return

        # Initialize LLM
        logger.info("Initializing LLM via DeepInfra...")
        llm = None
        try:
            llm = OpenAILLMService(
                api_key=DEEPINFRA_API_KEY,
                base_url=DEEPINFRA_BASE_URL,
                model=DEEPINFRA_MODEL
            )
            
            # --- TOOL REGISTRATION ---
            llm.register_function("fetch_user_image", fetch_user_image)
            llm.register_function("adjust_persona_parameter", adjust_persona_parameter)

            # Define the IDENTITY HANDLER wrapper
            async def wrapped_set_identity(function_name, tool_call_id, args, llm, context, result_callback):
                name = args["name"]
                logger.info(f"👤 Identity discovered: {name}")
                
                old_id = client_state["client_id"]
                # Normalize name to a clean ID (e.g. "Sarah" -> "user_sarah")
                new_id = f"user_{name.lower().replace(' ', '_')}"
                
                if old_id != new_id:
                    logger.info(f"🔄 Switching User ID: {old_id} -> {new_id}")
                    # Run memory transfer in background to avoid blocking
                    await asyncio.to_thread(_mem0.transfer_memories, old_id, new_id)
                    client_state["client_id"] = new_id
                    
                await result_callback(f"Identity updated to {name}. I will remember you as {name}.")

            # Register the wrapped function
            llm.register_function("set_user_identity", wrapped_set_identity)

            logger.info(f"✓ LLM initialized with model: {DEEPINFRA_MODEL}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            return

        # Initialize Moondream vision
        logger.info("Initializing Moondream vision service...")
        moondream = None
        try:
            moondream = MoondreamService(model="vikhyatk/moondream2", device="mps")
            logger.info("✓ Moondream vision service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Moondream: {e}")
            return

        # Initialize Visual Observer
        logger.info("Initializing Visual Observer...")
        visual_observer = VisualObserver(vision_client=moondream)
        logger.info("✓ Visual Observer initialized")

        # Initialize Gating Layer
        logger.info("Initializing Gating Layer...")
        gating_layer = InterventionGating(
            api_key=DEEPINFRA_API_KEY,
            base_url=DEEPINFRA_BASE_URL,
            model=DEEPINFRA_GATING_MODEL,
            visual_observer=visual_observer
        )
        logger.info(f"✓ Gating Layer initialized")

        # Load Context & Prompts
        character_dir = os.path.join(os.path.dirname(__file__), "character")
        persona_params = load_persona_ini(os.path.join(character_dir, "persona.ini"))
        tars_data = load_tars_json(os.path.join(character_dir, "TARS.json"))
        
        system_prompt = build_tars_system_prompt(persona_params, tars_data)

        # Create Tools Schema
        fetch_image_tool = create_fetch_image_schema()
        persona_tool = create_adjust_persona_schema()
        identity_tool = create_identity_schema() 
        
        tools = ToolsSchema(standard_tools=[fetch_image_tool, persona_tool, identity_tool])

        messages = [system_prompt]
        context = LLMContext(messages, tools)
        context_aggregator = LLMContextAggregatorPair(context)
        
        persona_storage = get_persona_storage()
        persona_storage["persona_params"] = persona_params
        persona_storage["tars_data"] = tars_data
        persona_storage["context_aggregator"] = context_aggregator

        # Loggers
        transcription_logger = SimpleTranscriptionLogger(webrtc_connection=webrtc_connection)
        assistant_logger = AssistantResponseLogger(webrtc_connection=webrtc_connection)
        tts_state_broadcaster = TTSSpeechStateBroadcaster(webrtc_connection=webrtc_connection)
        vision_logger = VisionLogger(webrtc_connection=webrtc_connection)
        latency_logger_upstream = LatencyLogger()
        latency_logger_llm = LatencyLogger()
        latency_logger_tts = LatencyLogger()

        logger.info("Creating audio/video pipeline...")

        parallel_branches = [llm]
        if moondream: parallel_branches.append(moondream)

        pipeline = Pipeline([
            pipecat_transport.input(),
            visual_observer,
            stt,
            transcription_logger,
            latency_logger_upstream,
            vision_logger,
            context_aggregator.user(),
            # gating_layer, # Disabled for now as requested
            ParallelPipeline(parallel_branches),
            assistant_logger,
            latency_logger_llm,
            SilenceFilter(),
            InputAudioFilter(),
            tts,
            tts_state_broadcaster,
            latency_logger_tts,
            pipecat_transport.output(),
            context_aggregator.assistant(),
        ])

        task_ref = {"task": None}

        @pipecat_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Pipecat Client connected")
            
            # Note: We now use the 'client_state["client_id"]' which starts as "guest_..."
            # Memories will only be recalled if this guest ID has history (unlikely for new sessions)
            # Real recall happens after they authenticate/state name
            
            try:
                if webrtc_connection.is_connected():
                    webrtc_connection.send_app_message({"type": "system", "message": "Connection established"})
            except Exception:
                pass

            if task_ref["task"]:
                # Custom Intro: Ask who they are if generic guest
                intro_text = "TARS online. Identity unknown. Please state your name."
                messages.append({"role": "system", "content": f"The user has just connected. Introduce yourself and ask for their name. System status: {intro_text}"})
                await task_ref["task"].queue_frames([LLMRunFrame()])

        @pipecat_transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Pipecat Client disconnected")
            if task_ref["task"]:
                await task_ref["task"].cancel()
            await _cleanup_services(service_refs)

        task = PipelineTask(pipeline)
        task_ref["task"] = task
        runner = PipelineRunner(handle_sigint=False)

        logger.info("Starting pipeline runner...")
        
        try:
            await runner.run(task)
        except Exception:
            raise
        finally:
            await _cleanup_services(service_refs)

    except Exception as e:
        logger.error(f"Error in bot pipeline: {e}", exc_info=True)
    finally:
        await _cleanup_services(service_refs)