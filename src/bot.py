"""Bot pipeline setup and execution."""

import sys
from pathlib import Path

# Add src directory to Python path for imports
src_dir = Path(__file__).parent
sys.path.insert(0, str(src_dir))

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
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams
)
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.observers.loggers.user_bot_latency_log_observer import UserBotLatencyLogObserver
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transcriptions.language import Language
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from loguru import logger

from config import (
    SPEECHMATICS_API_KEY,
    DEEPGRAM_API_KEY,
    SONIOX_API_KEY_JP,
    SONIOX_API_KEY_US,
    DEEPGRAM_MODEL,
    DEEPGRAM_ENDPOINTING,
    SONIOX_MODEL,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    DEEPINFRA_API_KEY,
    DEEPINFRA_BASE_URL,
    CEREBRAS_API_KEY,
    GEMINI_API_KEY,
    GOOGLE_BASE_URL,
    get_fresh_config,
)
from services.factories import create_stt_service, create_tts_service, create_llm_service, stt_display_name
from processors import (
    SilenceFilter,
    InputAudioFilter,
    ReasoningLeakFilter,
    ExpressTagFilter,
    SpaceNormalizer,
    ProactiveMonitor,
    ReactiveGate,
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
    load_character,
    get_introduction_instruction,
)
from tools import (
    capture_user_camera,
    adjust_persona_parameter,
    express,
    execute_movement,
    capture_robot_camera,
    set_task_mode,
    create_user_camera_schema,
    create_adjust_persona_schema,
    create_identity_schema,
    create_movement_schema,
    create_express_schema,
    create_robot_camera_schema,
    create_task_mode_schema,
    get_persona_storage,
    set_custom_expressions,
)
from shared_state import metrics_store

# Truncate LLM context dumps to last 4 messages to avoid system-prompt spam in logs
def _truncated_messages_for_logging(self):
    msgs = [m for m in self.messages if m.get("role") != "system"][-4:]
    return msgs

OpenAILLMContext.get_messages_for_logging = _truncated_messages_for_logging


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

    # Load fresh configuration for this connection (allows runtime config updates)
    runtime_config = get_fresh_config()
    DEEPINFRA_MODEL = runtime_config['DEEPINFRA_MODEL']
    _LLM_PROVIDER = runtime_config['LLM_PROVIDER']
    _LLM_MODEL = runtime_config['LLM_MODEL']
    STT_PROVIDER = runtime_config['STT_PROVIDER']
    TTS_PROVIDER = runtime_config['TTS_PROVIDER']
    QWEN3_TTS_MODEL = runtime_config['QWEN3_TTS_MODEL']
    QWEN3_TTS_DEVICE = runtime_config['QWEN3_TTS_DEVICE']
    QWEN3_TTS_REF_AUDIO = runtime_config['QWEN3_TTS_REF_AUDIO']
    TARS_DISPLAY_URL = runtime_config['TARS_DISPLAY_URL']
    TARS_DISPLAY_ENABLED = runtime_config['TARS_DISPLAY_ENABLED']

    logger.info(f"📋 Runtime config loaded - STT: {STT_PROVIDER}, LLM: {_LLM_PROVIDER}/{_LLM_MODEL}, TTS: {TTS_PROVIDER}")

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
        logger.info(f"Initializing transport ({STT_PROVIDER})...")

        transport_params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_in_enabled=False,
            video_out_enabled=False,
            video_out_is_live=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
        )

        pipecat_transport = SmallWebRTCTransport(
            webrtc_connection=webrtc_connection,
            params=transport_params,
        )

        logger.info("✓ Transport initialized")

        # ====================================================================
        # SPEECH-TO-TEXT SERVICE
        # ====================================================================

        logger.info(f"Initializing {STT_PROVIDER} STT...")
        stt = None
        try:
            stt = create_stt_service(
                provider=STT_PROVIDER,
                speechmatics_api_key=SPEECHMATICS_API_KEY,
                deepgram_api_key=DEEPGRAM_API_KEY,
                soniox_api_key=SONIOX_API_KEY_JP if STT_PROVIDER == "soniox-jp" else SONIOX_API_KEY_US,
                deepgram_model=DEEPGRAM_MODEL,
                deepgram_endpointing=DEEPGRAM_ENDPOINTING,
                soniox_model=SONIOX_MODEL,
                language=Language.EN,
                enable_diarization=False,
            )
            service_refs["stt"] = stt

            # Log additional info for Deepgram
            if STT_PROVIDER == "deepgram":
                logger.info("✓ Deepgram: 300ms endpointing for turn detection")
                logger.info("✓ Deepgram: VAD events enabled for speech detection")

        except Exception as e:
            logger.error(f"Failed to initialize {STT_PROVIDER} STT: {e}", exc_info=True)
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

        logger.info("Initializing LLM...")
        llm = None
        try:
            _api_key_map = {
                "cerebras": CEREBRAS_API_KEY,
                "google":   GEMINI_API_KEY,
            }
            llm = create_llm_service(
                provider=_LLM_PROVIDER,
                model=_LLM_MODEL,
                api_key=_api_key_map.get(_LLM_PROVIDER, DEEPINFRA_API_KEY),
                base_url=GOOGLE_BASE_URL if _LLM_PROVIDER == "google" else DEEPINFRA_BASE_URL,
            )
            logger.info(f"✓ LLM initialized: {_LLM_PROVIDER} / {_LLM_MODEL}")

            # Fetch custom sequences from Pi to wire into prompt + schemas
            from services import tars_robot as _tars_robot
            _custom_seq = await _tars_robot.fetch_custom_sequences()
            _custom_movements = [n for n, v in _custom_seq.items() if v["type"] == "movement"]
            _quick_expressions = [n for n, v in _custom_seq.items() if v["type"] == "expression" and v["quick"]]
            _long_expressions = [n for n, v in _custom_seq.items() if v["type"] == "expression" and not v["quick"]]
            if _custom_seq:
                logger.info(f"Custom sequences: movements={_custom_movements}, quick_expressions={_quick_expressions}, long_expressions={_long_expressions} (hidden from LLM)")
            _custom_expressions = _quick_expressions
            set_custom_expressions(_custom_expressions)

            persona_params, tars_data, system_prompt = load_character(
                custom_movements=_custom_movements,
                custom_expressions=_custom_expressions,
            )

            # Create tool schemas (these return FunctionSchema objects)
            user_camera_tool = create_user_camera_schema()
            persona_tool = create_adjust_persona_schema()
            # identity_tool = create_identity_schema()  # disabled: name recognition unreliable
            movement_tool = create_movement_schema(custom_movements=_custom_movements)
            # express_tool omitted: express is handled via inline [express(...)] tags,
            # not as a real tool call. Having it in the schema causes the model to
            # call it as a tool (returning no text), which produces silent hangs.
            camera_capture_tool = create_robot_camera_schema()
            task_mode_tool = create_task_mode_schema()

            # Pass FunctionSchema objects directly to standard_tools
            tools = ToolsSchema(
                standard_tools=[
                    user_camera_tool,
                    persona_tool,
                    # identity_tool,
                    movement_tool,
                    camera_capture_tool,
                    task_mode_tool,
                ]
            )
            messages = [system_prompt]
            context = LLMContext(messages, tools)

            llm.register_function("capture_user_camera", capture_user_camera)
            llm.register_function("adjust_persona_parameter", adjust_persona_parameter)
            llm.register_function("execute_movement", execute_movement)
            llm.register_function("capture_robot_camera", capture_robot_camera)
            llm.register_function("set_task_mode", set_task_mode)

            pipeline_unifier = IdentityUnifier(client_id)
            # async def wrapped_set_identity(params: FunctionCallParams):  # disabled: name recognition unreliable
            #     name = params.arguments["name"]
            #     logger.info(f"👤 Identity discovered: {name}")
            #
            #     old_id = client_state["client_id"]
            #     new_id = f"user_{name.lower().replace(' ', '_')}"
            #
            #     if old_id != new_id:
            #         logger.info(f"🔄 Switching User ID: {old_id} -> {new_id}")
            #         client_state["client_id"] = new_id
            #
            #         # Update the pipeline unifier to use new identity
            #         pipeline_unifier.target_user_id = new_id
            #         logger.info(f"✓ Updated pipeline unifier with new ID: {new_id}")
            #
            #         # Update memory service with new user_id
            #         if memory_service:
            #             memory_service.user_id = new_id
            #             logger.info(f"✓ Updated memory service user_id to: {new_id}")
            #
            #         # Notify frontend of identity change
            #         try:
            #             if webrtc_connection and webrtc_connection.is_connected():
            #                 webrtc_connection.send_app_message({
            #                     "type": "identity_update",
            #                     "old_id": old_id,
            #                     "new_id": new_id,
            #                     "name": name
            #                 })
            #                 logger.info(f"📤 Sent identity update to frontend: {new_id}")
            #         except Exception as e:
            #             logger.warning(f"Failed to send identity update to frontend: {e}")
            #
            #     await params.result_callback(f"Identity updated to {name}.")
            # llm.register_function("set_user_identity", wrapped_set_identity)
            logger.info(f"✓ LLM initialized with model: {DEEPINFRA_MODEL}")

        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}", exc_info=True)
            return

        # ====================================================================
        # MEMORY SERVICE (disabled)
        # ====================================================================

        memory_service = None  # Hybrid memory disabled

        # ====================================================================
        # CONTEXT AGGREGATOR & PERSONA STORAGE
        # ====================================================================

        user_params = LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_stop_timeout=0.5,
        )

        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=user_params
        )

        
        persona_storage = get_persona_storage()
        persona_storage["persona_params"] = persona_params
        persona_storage["tars_data"] = tars_data
        persona_storage["context_aggregator"] = context_aggregator
        persona_storage["context"] = context  # direct reference for system prompt updates

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
        metrics_observer = MetricsObserver(
            webrtc_connection=webrtc_connection,
            stt_service=stt
        )

        # Turn tracking observer (for debugging turn detection)
        turn_observer = TurnTrackingObserver()

        @turn_observer.event_handler("on_turn_started")
        async def on_turn_started(*args, **kwargs):
            turn_number = args[1] if len(args) > 1 else kwargs.get('turn_number', 0)
            logger.info(f"🗣️  [TurnObserver] Turn STARTED: {turn_number}")

        @turn_observer.event_handler("on_turn_ended")
        async def on_turn_ended(*args, **kwargs):
            turn_number = args[1] if len(args) > 1 else kwargs.get('turn_number', 0)
            logger.info(f"🗣️  [TurnObserver] Turn ENDED: {turn_number}")

        # ====================================================================
        # PIPELINE ASSEMBLY
        # ====================================================================

        logger.info("Creating audio/video pipeline...")

        # task_ref defined here so proactive_monitor can hold a reference before
        # the PipelineTask is created; dict is populated below after PipelineTask
        task_ref = {"task": None}

        proactive_monitor = ProactiveMonitor(
            context=context,
            task_ref=task_ref,
            silence_threshold=8.0,
            hesitation_threshold=3,
            hesitation_window=10.0,
            cooldown=30.0,
            post_bot_buffer=5.0,
            check_interval=1.0,
        )
        persona_storage["proactive_monitor"] = proactive_monitor

        reactive_gate = ReactiveGate(proactive_monitor)

        pipeline = Pipeline([
            pipecat_transport.input(),
            stt,
            proactive_monitor,
            pipeline_unifier,
            context_aggregator.user(),
            llm,
            ExpressTagFilter(),
            reactive_gate,
            SilenceFilter(),
            ReasoningLeakFilter(),
            SpaceNormalizer(),
            tts,
            pipecat_transport.output(),
            context_aggregator.assistant(),
        ])

        # ====================================================================
        # EVENT HANDLERS
        # ====================================================================

        @pipecat_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info(f"Pipecat Client connected (session {client_id})")
            try:
                if webrtc_connection.is_connected():
                    webrtc_connection.send_app_message({"type": "system", "message": "Connection established"})

                    # Send service configuration info with provider and model details
                    llm_display = _LLM_MODEL.split('/')[-1] if '/' in _LLM_MODEL else _LLM_MODEL

                    if TTS_PROVIDER == "elevenlabs":
                        tts_display = "ElevenLabs: eleven_flash_v2_5"
                    else:
                        tts_model = QWEN3_TTS_MODEL.split('/')[-1] if '/' in QWEN3_TTS_MODEL else QWEN3_TTS_MODEL
                        tts_display = f"Qwen3-TTS: {tts_model}"

                    # Format STT provider name for display
                    stt_display = stt_display_name(STT_PROVIDER)

                    service_info = {
                        "stt": stt_display,
                        "llm": f"{_LLM_PROVIDER.capitalize()}: {llm_display}",
                        "tts": tts_display
                    }

                    # Store in shared state for Gradio UI
                    metrics_store.set_service_info(service_info)

                    # Send via WebRTC
                    webrtc_connection.send_app_message({
                        "type": "service_info",
                        **service_info
                    })
                    logger.info(f"📊 Sent service info to frontend: STT={stt_display}, LLM={llm_display}, TTS={tts_display}")
            except Exception as e:
                logger.error(f"❌ Error sending service info: {e}")

            if task_ref["task"]:
                verbosity = persona_params.get("verbosity", 10) if persona_params else 10
                intro_instruction = get_introduction_instruction(verbosity)
                
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
        user_bot_latency_observer = UserBotLatencyLogObserver()

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
                user_bot_latency_observer,        # Measures total user→bot response time
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
        metrics_store.print_session_summary()
        await _cleanup_services(service_refs)
