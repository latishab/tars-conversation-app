"""
TARS Bot - Robot Mode

Pipecat pipeline that connects to Raspberry Pi TARS robot via WebRTC.
Uses aiortc client for bidirectional audio and DataChannel for state sync.

Architecture:
- RPi WebRTC Server (aiortc) ← MacBook WebRTC Client (aiortc)
- Audio: RPi mic → Pipeline → RPi speaker
- State: DataChannel for real-time sync
- Commands: HTTP REST for robot control
"""

import asyncio
import os
import uuid
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams
)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.transcriptions.language import Language
from pipecat.frames.frames import LLMRunFrame

from config import (
    DEEPGRAM_API_KEY,
    SPEECHMATICS_API_KEY,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    DEEPINFRA_API_KEY,
    DEEPINFRA_BASE_URL,
    RPI_URL,
    AUTO_CONNECT,
    RECONNECT_DELAY,
    MAX_RECONNECT_ATTEMPTS,
    get_fresh_config,
)

from transport import AiortcRPiClient, AudioBridge, StateSync
from transport.audio_bridge import RPiAudioInputTrack, RPiAudioOutputTrack
from services.factories import create_stt_service, create_tts_service
from services.tars_client import TARSClient
from processors import SilenceFilter
from observers import StateObserver
from character.prompts import (
    load_persona_ini,
    load_tars_json,
    build_tars_system_prompt,
    get_introduction_instruction,
)
from modules.module_tools import (
    fetch_user_image,
    adjust_persona_parameter,
    execute_movement,
    capture_camera_view,
    create_fetch_image_schema,
    create_adjust_persona_schema,
    create_identity_schema,
    create_movement_schema,
    create_camera_capture_schema,
    get_persona_storage,
)


async def run_robot_bot():
    """Run TARS bot in robot mode (connected to RPi via aiortc)."""
    logger.info("=" * 80)
    logger.info("🤖 Starting TARS in Robot Mode")
    logger.info("=" * 80)

    # Load fresh configuration
    runtime_config = get_fresh_config()
    DEEPINFRA_MODEL = runtime_config['DEEPINFRA_MODEL']
    STT_PROVIDER = runtime_config['STT_PROVIDER']
    TTS_PROVIDER = runtime_config['TTS_PROVIDER']
    QWEN3_TTS_MODEL = runtime_config['QWEN3_TTS_MODEL']
    QWEN3_TTS_DEVICE = runtime_config['QWEN3_TTS_DEVICE']
    QWEN3_TTS_REF_AUDIO = runtime_config['QWEN3_TTS_REF_AUDIO']
    TARS_DISPLAY_URL = runtime_config['TARS_DISPLAY_URL']
    TARS_DISPLAY_ENABLED = runtime_config['TARS_DISPLAY_ENABLED']

    logger.info(f"📋 Configuration:")
    logger.info(f"   STT: {STT_PROVIDER}")
    logger.info(f"   LLM: {DEEPINFRA_MODEL}")
    logger.info(f"   TTS: {TTS_PROVIDER}")
    logger.info(f"   RPi: {RPI_URL}")
    logger.info(f"   Display: {TARS_DISPLAY_URL} ({'enabled' if TARS_DISPLAY_ENABLED else 'disabled'})")

    # Session initialization
    session_id = str(uuid.uuid4())[:8]
    client_id = f"guest_{session_id}"
    client_state = {"client_id": client_id}
    logger.info(f"📱 Session: {client_id}")

    service_refs = {"stt": None, "tts": None, "tars_client": None, "aiortc_client": None}

    try:
        # ====================================================================
        # WEBRTC CONNECTION TO RPI
        # ====================================================================

        logger.info("🔌 Initializing WebRTC client...")
        aiortc_client = AiortcRPiClient(
            rpi_url=RPI_URL,
            auto_reconnect=True,
            reconnect_delay=RECONNECT_DELAY,
            max_reconnect_attempts=MAX_RECONNECT_ATTEMPTS,
        )
        service_refs["aiortc_client"] = aiortc_client

        # State sync via DataChannel
        state_sync = StateSync()

        # Set up callbacks
        @aiortc_client.on_connected
        async def on_connected():
            logger.info("✓ WebRTC connected to RPi")
            state_sync.set_send_callback(aiortc_client.send_data_channel_message)

        @aiortc_client.on_disconnected
        async def on_disconnected():
            logger.warning("⚠️  WebRTC disconnected from RPi")

        @aiortc_client.on_data_channel_message
        def on_data_message(message: str):
            state_sync.handle_message(message)

        # Register DataChannel message handlers
        state_sync.on_battery_update(lambda level, charging:
            logger.debug(f"🔋 Battery: {level}% ({'charging' if charging else 'discharging'})"))

        state_sync.on_movement_status(lambda moving, movement:
            logger.debug(f"🚶 Movement: {movement} ({'active' if moving else 'idle'})"))

        # Connect to RPi
        if AUTO_CONNECT:
            logger.info("🔄 Connecting to RPi...")
            connected = await aiortc_client.connect()
            if not connected:
                logger.error("❌ Failed to connect to RPi. Exiting.")
                return
        else:
            logger.info("⏸️  Auto-connect disabled. Waiting for manual connection.")
            return

        # Wait for audio track from RPi
        logger.info("⏳ Waiting for audio track from RPi...")
        timeout = 10
        start_time = asyncio.get_event_loop().time()
        while not aiortc_client.get_audio_track() and (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(0.1)

        audio_track_from_rpi = aiortc_client.get_audio_track()
        if not audio_track_from_rpi:
            logger.error("❌ No audio track received from RPi. Exiting.")
            return

        logger.info("✓ Received audio track from RPi")

        # ====================================================================
        # AUDIO BRIDGE SETUP
        # ====================================================================

        logger.info("🎧 Setting up audio bridge...")

        # Create audio input track (RPi mic → Pipecat)
        rpi_input = RPiAudioInputTrack(
            aiortc_track=audio_track_from_rpi,
            sample_rate=16000  # RPi mic sample rate
        )

        # Create audio output track (Pipecat TTS → RPi speaker)
        rpi_output = RPiAudioOutputTrack(
            sample_rate=24000  # TTS output sample rate
        )

        # Add output track to WebRTC connection
        aiortc_client.add_audio_track(rpi_output)

        # Create audio bridge processor
        audio_bridge = AudioBridge(
            rpi_input_track=rpi_input,
            rpi_output_track=rpi_output
        )

        logger.info("✓ Audio bridge ready")

        # ====================================================================
        # SPEECH-TO-TEXT SERVICE
        # ====================================================================

        logger.info(f"🎤 Initializing {STT_PROVIDER} STT...")
        stt = create_stt_service(
            provider=STT_PROVIDER,
            speechmatics_api_key=SPEECHMATICS_API_KEY,
            deepgram_api_key=DEEPGRAM_API_KEY,
            language=Language.EN,
            enable_diarization=False,
        )
        service_refs["stt"] = stt
        logger.info(f"✓ STT initialized")

        # ====================================================================
        # TEXT-TO-SPEECH SERVICE
        # ====================================================================

        logger.info(f"🔊 Initializing {TTS_PROVIDER} TTS...")
        tts = create_tts_service(
            provider=TTS_PROVIDER,
            elevenlabs_api_key=ELEVENLABS_API_KEY,
            elevenlabs_voice_id=ELEVENLABS_VOICE_ID,
            qwen_model=QWEN3_TTS_MODEL,
            qwen_device=QWEN3_TTS_DEVICE,
            qwen_ref_audio=QWEN3_TTS_REF_AUDIO,
        )
        service_refs["tts"] = tts
        logger.info(f"✓ TTS initialized")

        # ====================================================================
        # LLM SERVICE & TOOLS
        # ====================================================================

        logger.info("🧠 Initializing LLM...")
        llm = OpenAILLMService(
            api_key=DEEPINFRA_API_KEY,
            base_url=DEEPINFRA_BASE_URL,
            model=DEEPINFRA_MODEL
        )

        # Load character
        character_dir = os.path.join(os.path.dirname(__file__), "character")
        persona_params = load_persona_ini(os.path.join(character_dir, "persona.ini"))
        tars_data = load_tars_json(os.path.join(character_dir, "TARS.json"))
        system_prompt = build_tars_system_prompt(persona_params, tars_data)

        # Create tool schemas
        tools = ToolsSchema(
            standard_tools=[
                create_fetch_image_schema(),
                create_adjust_persona_schema(),
                create_identity_schema(),
                create_movement_schema(),
                create_camera_capture_schema(),
            ]
        )

        messages = [system_prompt]
        context = LLMContext(messages, tools)

        # Register tool functions
        llm.register_function("fetch_user_image", fetch_user_image)
        llm.register_function("adjust_persona_parameter", adjust_persona_parameter)
        llm.register_function("execute_movement", execute_movement)
        llm.register_function("capture_camera_view", capture_camera_view)

        logger.info(f"✓ LLM initialized with {DEEPINFRA_MODEL}")

        # ====================================================================
        # TARS DISPLAY CLIENT (HTTP commands)
        # ====================================================================

        logger.info("📺 Initializing TARS Display Client...")
        tars_client = None
        if TARS_DISPLAY_ENABLED:
            try:
                tars_client = TARSClient(base_url=TARS_DISPLAY_URL, timeout=2.0)
                await tars_client.connect()
                service_refs["tars_client"] = tars_client
                if tars_client.is_connected():
                    logger.info(f"✓ TARS Display Client connected")
                    await tars_client.set_display_mode("eyes")
                    await tars_client.set_eye_state("idle")
                else:
                    logger.warning("⚠️ TARS Display not available")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize TARS Display: {e}")
        else:
            logger.info("ℹ️  TARS Display disabled")

        # ====================================================================
        # CONTEXT AGGREGATOR
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
        # OBSERVERS
        # ====================================================================

        state_observer = StateObserver(state_sync=state_sync)

        # ====================================================================
        # PIPELINE ASSEMBLY
        # ====================================================================

        logger.info("🔧 Building pipeline...")

        pipeline = Pipeline([
            stt,
            context_aggregator.user(),
            llm,
            SilenceFilter(),
            tts,
            audio_bridge,  # Captures TTS output and sends to RPi speaker
            context_aggregator.assistant(),
        ])

        # ====================================================================
        # AUDIO INPUT FEEDING
        # ====================================================================

        # Task reference for audio feeding
        task_ref = {"task": None, "audio_task": None}

        async def feed_rpi_audio():
            """Feed audio frames from RPi mic into the pipeline."""
            logger.info("🎤 Starting audio input from RPi...")
            try:
                async for audio_frame in rpi_input.start():
                    if task_ref.get("task"):
                        await task_ref["task"].queue_frames([audio_frame])
            except Exception as e:
                logger.error(f"❌ Audio input error: {e}", exc_info=True)
            finally:
                logger.info("🎤 Audio input stopped")

        # ====================================================================
        # PIPELINE EXECUTION
        # ====================================================================

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
                report_only_initial_ttfb=False,
            ),
            observers=[state_observer],
        )

        task_ref["task"] = task
        runner = PipelineRunner(handle_sigint=True)

        logger.info("▶️  Starting pipeline...")
        logger.info("=" * 80)

        # Start audio input feeding task
        audio_task = asyncio.create_task(feed_rpi_audio())
        task_ref["audio_task"] = audio_task

        # Send initial greeting
        await asyncio.sleep(2.0)
        intro_instruction = get_introduction_instruction(client_id, persona_params.get("verbosity", 10))
        if context and hasattr(context, "messages"):
            context.messages.append(intro_instruction)
        await task.queue_frames([LLMRunFrame()])

        # Run pipeline
        try:
            await runner.run(task)
        finally:
            # Cancel audio feeding task
            if task_ref.get("audio_task"):
                task_ref["audio_task"].cancel()
                try:
                    await task_ref["audio_task"]
                except asyncio.CancelledError:
                    pass

    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Error in robot bot: {e}", exc_info=True)
    finally:
        # Cleanup
        logger.info("🧹 Cleaning up...")
        if service_refs.get("aiortc_client"):
            await service_refs["aiortc_client"].disconnect()
        if service_refs.get("stt"):
            try:
                await service_refs["stt"].close()
            except:
                pass
        if service_refs.get("tts"):
            try:
                await service_refs["tts"].close()
            except:
                pass
        if service_refs.get("tars_client"):
            try:
                await service_refs["tars_client"].disconnect()
            except:
                pass
        logger.info("✓ Cleanup complete")


if __name__ == "__main__":
    asyncio.run(run_robot_bot())
