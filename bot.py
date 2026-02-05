"""Bot pipeline setup and execution."""

import asyncio
import json
import os
import logging
import uuid
import httpx

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
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams
)
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.services.moondream.vision import MoondreamService
from pipecat.services.speechmatics.stt import SpeechmaticsSTTService, TurnDetectionMode
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
    TTS_PROVIDER,
    QWEN3_TTS_MODEL,
    QWEN3_TTS_DEVICE,
    QWEN3_TTS_REF_AUDIO,
    EMOTIONAL_MONITORING_ENABLED,
    EMOTIONAL_SAMPLING_INTERVAL,
    EMOTIONAL_INTERVENTION_THRESHOLD,
)
from services.tts_factory import create_tts_service
from processors import (
    SilenceFilter,
    InputAudioFilter,
    InterventionGating,
    VisualObserver,
    EmotionalStateMonitor,
)
from observers import (
    MetricsObserver,
    TranscriptionObserver,
    AssistantResponseObserver,
    TTSStateObserver,
    VisionObserver,
    DebugObserver,
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
from modules.module_crossword import (
    get_crossword_hint,
    create_crossword_hint_schema,
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
        # TRANSPORT INITIALIZATION
        # ====================================================================
        # Note: We're using Speechmatics' built-in SMART_TURN mode for turn detection,
        # so we don't need external VAD or turn analyzers in the transport.

        logger.info("Initializing transport (using Speechmatics built-in turn detection)...")

        transport_params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_in_enabled=False,
            video_out_enabled=False,
            video_out_is_live=False,
        )

        pipecat_transport = SmallWebRTCTransport(
            webrtc_connection=webrtc_connection,
            params=transport_params,
        )

        logger.info("✓ Transport initialized")

        # ====================================================================
        # SPEECH-TO-TEXT SERVICE
        # ====================================================================

        logger.info("Initializing Speechmatics STT...")
        stt = None
        try:
            stt_params = SpeechmaticsSTTService.InputParams(
                language=Language.EN,
                enable_diarization=False,
                turn_detection_mode=TurnDetectionMode.SMART_TURN,
            )

            stt = SpeechmaticsSTTService(
                api_key=SPEECHMATICS_API_KEY,
                params=stt_params,
            )
            service_refs["stt"] = stt
            logger.info("✓ Speechmatics STT initialized with SMART_TURN mode")
        except Exception as e:
            logger.error(f"Failed to initialize Speechmatics: {e}", exc_info=True)
            return

        # ====================================================================
        # TEXT-TO-SPEECH SERVICE
        # ====================================================================

        try:
            tts = create_tts_service(
                provider=TTS_PROVIDER,
                elevenlabs_api_key=ELEVENLABS_API_KEY,
                elevenlabs_voice_id=ELEVENLABS_VOICE_ID,
                qwen_model=QWEN3_TTS_MODEL,
                qwen_device=QWEN3_TTS_DEVICE,
                qwen_ref_audio=QWEN3_TTS_REF_AUDIO,
            )
            service_refs["tts"] = tts
        except Exception as e:
            logger.error(f"Failed to initialize TTS service: {e}", exc_info=True)
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

            # Create tool schemas (these return FunctionSchema objects)
            fetch_image_tool = create_fetch_image_schema()
            persona_tool = create_adjust_persona_schema()
            identity_tool = create_identity_schema()
            crossword_hint_tool = create_crossword_hint_schema()

            # Pass FunctionSchema objects directly to standard_tools
            tools = ToolsSchema(
                standard_tools=[
                    fetch_image_tool,
                    persona_tool,
                    identity_tool,
                    crossword_hint_tool
                ]
            )
            messages = [system_prompt]
            context = LLMContext(messages, tools)

            llm.register_function("fetch_user_image", fetch_user_image)
            llm.register_function("adjust_persona_parameter", adjust_persona_parameter)
            llm.register_function("get_crossword_hint", get_crossword_hint)

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

                    # Update Mem0 service with new user_id and run_id
                    if memory_service:
                        new_run_id = new_id.split('_')[-1]  # Extract the identifier part
                        memory_service.user_id = new_id
                        memory_service.run_id = new_run_id
                        logger.info(f"✓ Updated Mem0 service user_id to: {new_id}, run_id to: {new_run_id}")

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
            logger.error(f"Failed to initialize LLM: {e}", exc_info=True)
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

        logger.info("Initializing Emotional State Monitor...")
        emotional_monitor = EmotionalStateMonitor(
            vision_client=moondream,
            model="vikhyatk/moondream2",
            sampling_interval=EMOTIONAL_SAMPLING_INTERVAL,
            intervention_threshold=EMOTIONAL_INTERVENTION_THRESHOLD,
            enabled=EMOTIONAL_MONITORING_ENABLED,
            auto_intervene=False,  # Let gating layer handle intervention decisions
        )
        logger.info(f"✓ Emotional State Monitor initialized (enabled: {EMOTIONAL_MONITORING_ENABLED})")
        logger.info(f"   Mode: Integrated with gating layer for smarter decisions")

        logger.info("Initializing Gating Layer...")
        gating_layer = InterventionGating(
            api_key=DEEPINFRA_API_KEY,
            base_url=DEEPINFRA_BASE_URL,
            model=DEEPINFRA_GATING_MODEL,
            visual_observer=visual_observer,
            emotional_monitor=emotional_monitor
        )
        logger.info(f"✓ Gating Layer initialized with emotional state integration")

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
            user_turn_stop_timeout=1.5
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

        transcription_observer = TranscriptionObserver(
            webrtc_connection=webrtc_connection,
            client_state=client_state
        )
        assistant_observer = AssistantResponseObserver(webrtc_connection=webrtc_connection)
        tts_state_observer = TTSStateObserver(webrtc_connection=webrtc_connection)
        vision_observer = VisionObserver(webrtc_connection=webrtc_connection)

        # Create MetricsObserver (non-intrusive monitoring outside pipeline)
        metrics_observer = MetricsObserver(webrtc_connection=webrtc_connection)

        # Turn tracking observer (for debugging turn detection)
        turn_observer = TurnTrackingObserver()

        @turn_observer.event_handler("on_turn_started")
        async def on_turn_started(*args, **kwargs):
            turn_number = args[1] if len(args) > 1 else kwargs.get('turn_number', 0)
            logger.info(f"🗣️  [TurnObserver] Turn STARTED: {turn_number}")
            # Notify metrics observer of new turn
            metrics_observer.start_turn(turn_number)

        @turn_observer.event_handler("on_turn_ended")
        async def on_turn_ended(*args, **kwargs):
            turn_number = args[1] if len(args) > 1 else kwargs.get('turn_number', 0)
            logger.info(f"🗣️  [TurnObserver] Turn ENDED: {turn_number}")

        # ====================================================================
        # PIPELINE ASSEMBLY
        # ====================================================================

        logger.info("Creating audio/video pipeline...")

        pipeline = Pipeline([
            pipecat_transport.input(),
            # emotional_monitor,  # Real-time emotional state monitoring
            stt,
            pipeline_unifier,
            context_aggregator.user(),
            memory_service,  # Mem0 memory service for automatic recall/storage
            # gating_layer,  # AI decision system (with emotional state integration)
            llm,
            SilenceFilter(),
            tts,
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

                    # Send service configuration info with provider and model details
                    llm_display = DEEPINFRA_MODEL.split('/')[-1] if '/' in DEEPINFRA_MODEL else DEEPINFRA_MODEL

                    if TTS_PROVIDER == "elevenlabs":
                        tts_display = "ElevenLabs: eleven_flash_v2_5"
                    else:
                        tts_model = QWEN3_TTS_MODEL.split('/')[-1] if '/' in QWEN3_TTS_MODEL else QWEN3_TTS_MODEL
                        tts_display = f"Qwen3-TTS: {tts_model}"

                    webrtc_connection.send_app_message({
                        "type": "service_info",
                        "stt": "Speechmatics",
                        "mem0": "Mem0 (v2 API)",
                        "llm": f"DeepInfra: {llm_display}",
                        "tts": tts_display
                    })
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

        # Enable built-in Pipecat metrics for latency tracking
        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,              # Enable performance metrics (TTFB, latency)
                enable_usage_metrics=True,        # Enable LLM/TTS usage metrics
                report_only_initial_ttfb=False,   # Report all TTFB measurements
            ),
            observers=[
                turn_observer,
                metrics_observer,
                transcription_observer,
                assistant_observer,
                tts_state_observer,
                vision_observer,
            ],  # Non-intrusive monitoring
        )
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
