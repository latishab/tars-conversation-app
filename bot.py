"""Bot pipeline setup and execution."""

import asyncio
import json
import os
import logging
import uuid

from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    LLMRunFrame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
    Frame,
    TranscriptionMessage,
    TranslationFrame,
    UserImageRawFrame,
    UserAudioRawFrame,
    UserImageRequestFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams
)
from pipecat.services.moondream.vision import MoondreamService
from pipecat.services.speechmatics.stt import SpeechmaticsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.mem0.memory import Mem0MemoryService
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
    MEM0_API_KEY,
)
from processors import (
    SilenceFilter,
    InputAudioFilter,
    InterventionGating,
    VisualObserver,
)
from loggers import (
    DebugLogger,
    TurnDetectionLogger,
    TranscriptionLogger,
    AssistantResponseLogger,
    TTSSpeechStateBroadcaster,
    VisionLogger,
    LatencyLogger,
)
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
    create_identity_schema,
    get_persona_storage,
)


# ============================================================================
# CUSTOM FRAME PROCESSORS
# ============================================================================

class IdentityUnifier(FrameProcessor):
    """
    Applies 'guest_ID' ONLY to specific user input frames.
    Leaves other frames untouched.
    """
    # Define the frame types that should have user_id set
    TARGET_FRAME_TYPES = (
        TranscriptionFrame,
        TranscriptionMessage,
        TranslationFrame,
        InterimTranscriptionFrame,
        UserImageRawFrame,
        UserAudioRawFrame,
        UserImageRequestFrame,
    )

    def __init__(self, target_user_id):
        super().__init__()
        self.target_user_id = target_user_id

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # 1. Handle internal state
        await super().process_frame(frame, direction)

        # 2. Only modify specific frame types
        if isinstance(frame, self.TARGET_FRAME_TYPES):
            try:
                frame.user_id = self.target_user_id
            except Exception:
                pass

        # 3. Push downstream
        await self.push_frame(frame, direction)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def _cleanup_services(service_refs: dict):
    if service_refs.get("stt"):
        try:
            await service_refs["stt"].close()
            logger.info("✓ STT service cleaned up")
        except Exception:
            pass
    if service_refs.get("tts"):
        try:
            await service_refs["tts"].close()
            logger.info("✓ TTS service cleaned up")
        except Exception:
            pass


# ============================================================================
# MAIN BOT PIPELINE
# ============================================================================

async def run_bot(webrtc_connection):
    """Initialize and run the TARS bot pipeline."""
    logger.info("Starting bot pipeline for WebRTC connection...")

    # Session initialization
    session_id = str(uuid.uuid4())[:8]
    client_id = f"guest_{session_id}"
    client_state = {"client_id": client_id}
    logger.info(f"Session started: {client_id}")

    service_refs = {"stt": None, "tts": None}

    try:
        # ====================================================================
        # VAD & SMART TURN DETECTION
        # ====================================================================
        logger.info("Initializing VAD and Smart Turn Detection...")
        vad_analyzer = None
        turn_analyzer = None
        try:
            from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
            
            vad_analyzer = SileroVADAnalyzer(params=VADParams(stop_secs=0.6, start_secs=0.2, confidence=0.4))
            turn_analyzer = LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=0.8, pre_speech_ms=200.0))
            logger.info("✓ VAD and Smart Turn Detection initialized")
        except ImportError:
            logger.warning("Smart Turn dependencies not installed.")

        # ====================================================================
        # TRANSPORT INITIALIZATION
        # ====================================================================

        transport_params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_in_enabled=False,
            video_out_enabled=False,
            video_out_is_live=False,
        )
        
        if vad_analyzer: transport_params.vad_analyzer = vad_analyzer
        if turn_analyzer: transport_params.turn_analyzer = turn_analyzer
        
        pipecat_transport = SmallWebRTCTransport(
            webrtc_connection=webrtc_connection,
            params=transport_params,
        )

        # ====================================================================
        # SPEECH-TO-TEXT SERVICE
        # ====================================================================

        logger.info("Initializing Speechmatics STT...")
        stt = None
        try:
            stt_params = SpeechmaticsSTTService.InputParams(
                language=Language.EN,
                enable_diarization=False,
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
            logger.error(f"Failed to initialize Speechmatics: {e}", exc_info=True)
            return

        # ====================================================================
        # TEXT-TO-SPEECH SERVICE
        # ====================================================================

        logger.info("Initializing ElevenLabs TTS...")
        tts = None
        try:
            tts = ElevenLabsTTSService(
                api_key=ELEVENLABS_API_KEY,
                voice_id=ELEVENLABS_VOICE_ID,
                model="eleven_turbo_v2_5",
                output_format="pcm_24000",
                enable_word_timestamps=False,
                voice_settings={
                    "stability": 0.5,
                    "similarity_boost": 0.75, 
                    "style": 0.0,
                    "use_speaker_boost": True
                }
            )
            service_refs["tts"] = tts
            logger.info("✓ ElevenLabs TTS service created")
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}", exc_info=True)
            return

        # ====================================================================
        # LLM SERVICE & TOOLS
        # ====================================================================

        logger.info("Initializing LLM via DeepInfra...")
        llm = None
        try:
            llm = OpenAILLMService(
                api_key=DEEPINFRA_API_KEY,
                base_url=DEEPINFRA_BASE_URL,
                model=DEEPINFRA_MODEL 
            )
            
            character_dir = os.path.join(os.path.dirname(__file__), "character")
            persona_params = load_persona_ini(os.path.join(character_dir, "persona.ini"))
            tars_data = load_tars_json(os.path.join(character_dir, "TARS.json"))
            system_prompt = build_tars_system_prompt(persona_params, tars_data)

            fetch_image_tool = create_fetch_image_schema()
            persona_tool = create_adjust_persona_schema()
            identity_tool = create_identity_schema()
            
            tools = ToolsSchema(standard_tools=[fetch_image_tool, persona_tool, identity_tool])
            messages = [system_prompt]
            context = LLMContext(messages, tools)

            llm.register_function("fetch_user_image", fetch_user_image)
            llm.register_function("adjust_persona_parameter", adjust_persona_parameter)

            pipeline_unifier = IdentityUnifier(client_id)
            async def wrapped_set_identity(params: FunctionCallParams):
                name = params.arguments["name"]
                logger.info(f"👤 Identity discovered: {name}")

                old_id = client_state["client_id"]
                new_id = f"user_{name.lower().replace(' ', '_')}"

                if old_id != new_id:
                    logger.info(f"🔄 Switching User ID: {old_id} -> {new_id}")
                    client_state["client_id"] = new_id

                    # Update the pipeline unifier to use new identity
                    pipeline_unifier.target_user_id = new_id
                    logger.info(f"✓ Updated pipeline unifier with new ID: {new_id}")

                    # Update Mem0 service with new user_id
                    if memory_service:
                        memory_service._user_id = new_id
                        logger.info(f"✓ Updated Mem0 service user_id to: {new_id}")

                    # Notify frontend of identity change
                    try:
                        if webrtc_connection and webrtc_connection.is_connected():
                            webrtc_connection.send_app_message({
                                "type": "identity_update",
                                "old_id": old_id,
                                "new_id": new_id,
                                "name": name
                            })
                            logger.info(f"📤 Sent identity update to frontend: {new_id}")
                    except Exception as e:
                        logger.warning(f"Failed to send identity update to frontend: {e}")

                await params.result_callback(f"Identity updated to {name}.")

            llm.register_function("set_user_identity", wrapped_set_identity)
            logger.info(f"✓ LLM initialized with model: {DEEPINFRA_MODEL}")

        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            return

        # ====================================================================
        # VISION & GATING SERVICES
        # ====================================================================

        logger.info("Initializing Moondream vision service...")
        moondream = None
        try:
            moondream = MoondreamService(model="vikhyatk/moondream2", revision="2025-01-09")
            logger.info("✓ Moondream vision service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Moondream: {e}")
            return

        logger.info("Initializing Visual Observer...")
        visual_observer = VisualObserver(vision_client=moondream)
        logger.info("✓ Visual Observer initialized")

        logger.info("Initializing Gating Layer...")
        gating_layer = InterventionGating(
            api_key=DEEPINFRA_API_KEY,
            base_url=DEEPINFRA_BASE_URL,
            model=DEEPINFRA_GATING_MODEL,
            visual_observer=visual_observer
        )
        logger.info(f"✓ Gating Layer initialized")

        # ====================================================================
        # MEMORY SERVICE
        # ====================================================================

        logger.info("Initializing Mem0 memory service...")
        memory_service = None
        try:
            memory_service = Mem0MemoryService(
                api_key=MEM0_API_KEY,
                user_id=client_id,
                agent_id="tars_agent",
                run_id=session_id,
                params=Mem0MemoryService.InputParams(
                    search_limit=10,
                    search_threshold=0.3,
                    api_version="v2",
                    system_prompt="Based on previous conversations, I recall: \n\n",
                    add_as_system_message=True,
                    position=1,
                ),
            )
            logger.info(f"✓ Mem0 memory service initialized for {client_id}")
        except Exception as e:
            logger.error(f"Failed to initialize Mem0 service: {e}")
            return

        # ====================================================================
        # CONTEXT AGGREGATOR & PERSONA STORAGE
        # ====================================================================

        user_params = LLMUserAggregatorParams(
            aggregation_timeout=1.5
        )
        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=user_params
        )
        
        persona_storage = get_persona_storage()
        persona_storage["persona_params"] = persona_params
        persona_storage["tars_data"] = tars_data
        persona_storage["context_aggregator"] = context_aggregator

        # ====================================================================
        # LOGGING PROCESSORS
        # ====================================================================

        transcription_logger = TranscriptionLogger(
            webrtc_connection=webrtc_connection,
            client_state=client_state
        )

        assistant_logger = AssistantResponseLogger(webrtc_connection=webrtc_connection)
        tts_state_broadcaster = TTSSpeechStateBroadcaster(webrtc_connection=webrtc_connection)
        vision_logger = VisionLogger(webrtc_connection=webrtc_connection)
        latency_logger = LatencyLogger()
        turn_logger = TurnDetectionLogger()

        # ====================================================================
        # PIPELINE ASSEMBLY
        # ====================================================================

        logger.info("Creating audio/video pipeline...")

        pipeline = Pipeline([
            pipecat_transport.input(),
            stt,
            # turn_logger,
            pipeline_unifier,
            transcription_logger,
            context_aggregator.user(),
            memory_service,  # Mem0 memory service for automatic recall/storage
            llm,
            assistant_logger,
            latency_logger,
            SilenceFilter(),
            tts,
            tts_state_broadcaster,
            pipecat_transport.output(),
            context_aggregator.assistant(),
        ])

        # ====================================================================
        # EVENT HANDLERS
        # ====================================================================

        task_ref = {"task": None}

        @pipecat_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Pipecat Client connected")
            try:
                if webrtc_connection.is_connected():
                    webrtc_connection.send_app_message({"type": "system", "message": "Connection established"})
            except Exception:
                pass

            if task_ref["task"]:
                verbosity = persona_params.get("verbosity", 10) if persona_params else 10
                intro_instruction = get_introduction_instruction(client_state['client_id'], verbosity)
                
                if context and hasattr(context, "messages"):
                     context.messages.append(intro_instruction)

                logger.info("Waiting for pipeline to warm up...")
                await asyncio.sleep(2.0)
                
                logger.info("Queueing initial LLM greeting...")
                await task_ref["task"].queue_frames([LLMRunFrame()])

        @pipecat_transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Pipecat Client disconnected")
            if task_ref["task"]:
                await task_ref["task"].cancel()
            await _cleanup_services(service_refs)

        # ====================================================================
        # PIPELINE EXECUTION
        # ====================================================================

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