"""
TARS Bot - Robot Mode

Pipecat pipeline that connects to Raspberry Pi TARS robot via WebRTC.
Uses aiortc client for bidirectional audio and DataChannel for state sync.

Architecture:
- RPi WebRTC Server (aiortc) ← MacBook WebRTC Client (aiortc)
- Audio: RPi mic → Pipeline → RPi speaker
- State: DataChannel for real-time sync
- Commands: gRPC for robot control
"""

import sys
from pathlib import Path

# Add src/ to Python path
# Add src directory to Python path for imports
src_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(src_dir))

import asyncio
import os
import uuid
import argparse
import threading
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
    RPI_GRPC,
    AUTO_CONNECT,
    RECONNECT_DELAY,
    MAX_RECONNECT_ATTEMPTS,
    get_fresh_config,
    detect_deployment_mode,
    get_robot_grpc_address,
)

from transport import AiortcRPiClient, AudioBridge, StateSync
from transport.audio_bridge import RPiAudioInputTrack, RPiAudioOutputTrack
from services.factories import create_stt_service, create_tts_service
from services import tars_robot
from services.update_checker import TarsUpdateChecker, CLIENT_VERSION
from processors import SilenceFilter
from observers import StateObserver
from character.prompts import (
    load_persona_ini,
    load_tars_json,
    build_tars_system_prompt,
    get_introduction_instruction,
)
from tools import (
    capture_user_camera,
    capture_robot_camera,
    adjust_persona_parameter,
    express,
    execute_movement,
    create_user_camera_schema,
    create_robot_camera_schema,
    create_adjust_persona_schema,
    create_identity_schema,
    create_express_schema,
    create_movement_schema,
    get_persona_storage,
    set_rate_limiter,
    ExpressionRateLimiter,
)


async def run_robot_bot(ui=None):
    """Run TARS bot in robot mode (connected to RPi via aiortc).

    Args:
        ui: Optional TarsGradioUI instance for live updates
    """
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

    # Detect deployment mode
    deployment_mode = detect_deployment_mode()
    robot_grpc_address = get_robot_grpc_address()

    logger.info(f"📋 Configuration:")
    logger.info(f"   Client: v{CLIENT_VERSION}")
    logger.info(f"   Deployment: {deployment_mode}")
    logger.info(f"   STT: {STT_PROVIDER}")
    logger.info(f"   LLM: {DEEPINFRA_MODEL}")
    logger.info(f"   TTS: {TTS_PROVIDER}")
    logger.info(f"   RPi HTTP: {RPI_URL}")
    logger.info(f"   RPi gRPC: {robot_grpc_address}")
    logger.info(f"   Display: {TARS_DISPLAY_URL} ({'enabled' if TARS_DISPLAY_ENABLED else 'disabled'})")

    # Store service info for UI
    from shared_state import metrics_store

    # Format LLM display name
    llm_display = DEEPINFRA_MODEL.split('/')[-1] if '/' in DEEPINFRA_MODEL else DEEPINFRA_MODEL

    # Format TTS display name
    if TTS_PROVIDER == "elevenlabs":
        tts_display = "ElevenLabs: eleven_flash_v2_5"
    else:
        tts_model = QWEN3_TTS_MODEL.split('/')[-1] if '/' in QWEN3_TTS_MODEL else QWEN3_TTS_MODEL
        tts_display = f"Qwen3-TTS: {tts_model}"

    # Format STT display name
    stt_display = {
        "speechmatics": "Speechmatics",
        "deepgram": "Deepgram Nova-2",
        "deepgram-flux": "Deepgram Flux"
    }.get(STT_PROVIDER, STT_PROVIDER.capitalize())

    service_info = {
        "stt": stt_display,
        "llm": f"DeepInfra: {llm_display}",
        "tts": tts_display
    }
    metrics_store.set_service_info(service_info)
    logger.info(f"📊 Service info: STT={stt_display}, LLM={llm_display}, TTS={tts_display}")

    # Session initialization
    session_id = str(uuid.uuid4())[:8]
    client_id = f"guest_{session_id}"
    client_state = {"client_id": client_id}
    logger.info(f"📱 Session: {client_id}")

    service_refs = {"stt": None, "tts": None, "robot_client": None, "aiortc_client": None}

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
                from shared_state import metrics_store
                metrics_store.set_pipeline_status("disconnected")
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

        # Set pipeline status to idle after successful connection
        from shared_state import metrics_store
        metrics_store.set_pipeline_status("idle")
        logger.info("📊 Pipeline status set to idle")

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

        # Initialize expression rate limiter
        rate_limiter = ExpressionRateLimiter(
            min_expression_interval=2.0,
            min_gesture_interval=15.0,
            max_medium_per_session=5,
            max_high_per_session=2,
        )
        set_rate_limiter(rate_limiter)

        # Create tool schemas
        tools = ToolsSchema(
            standard_tools=[
                create_express_schema(),
                create_movement_schema(),
                create_user_camera_schema(),
                create_robot_camera_schema(),
                create_adjust_persona_schema(),
                create_identity_schema(),
            ]
        )

        messages = [system_prompt]
        context = LLMContext(messages, tools)

        # Register tool functions
        llm.register_function("express", express)
        llm.register_function("execute_movement", execute_movement)
        llm.register_function("capture_user_camera", capture_user_camera)
        llm.register_function("capture_robot_camera", capture_robot_camera)
        llm.register_function("adjust_persona_parameter", adjust_persona_parameter)

        logger.info(f"✓ LLM initialized with {DEEPINFRA_MODEL}")

        # ====================================================================
        # TARS ROBOT CLIENT (gRPC commands)
        # ====================================================================

        logger.info("🤖 Initializing TARS Robot Client (gRPC)...")
        robot_client = None
        if TARS_DISPLAY_ENABLED:
            try:
                robot_client = tars_robot.get_robot_client(address=robot_grpc_address)
                service_refs["robot_client"] = robot_client
                if robot_client and tars_robot.is_robot_available():
                    logger.info(f"✓ TARS Robot Client connected via gRPC at {robot_grpc_address}")
                    tars_robot.set_eye_state("idle")

                    # Check daemon version
                    logger.info("Checking TARS daemon version...")
                    update_checker = TarsUpdateChecker(robot_client)
                    await update_checker.check_on_connect()
                else:
                    logger.warning("⚠️ TARS Robot not available")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize TARS Robot: {e}")
        else:
            logger.info("ℹ️  TARS Robot control disabled")

        # Expose robot_client to UI so mute button can use it
        if ui is not None:
            ui.robot_client = robot_client

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
        if service_refs.get("robot_client"):
            try:
                tars_robot.close_robot_client()
            except:
                pass
        logger.info("✓ Cleanup complete")


def run_browser_mode(port: int = 7860):
    """Run browser audio mode: SmallWebRTC + Gradio UI on a single port."""
    from fastapi import FastAPI, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from pipecat.transports.smallwebrtc.request_handler import (
        SmallWebRTCPatchRequest,
        SmallWebRTCRequest,
        SmallWebRTCRequestHandler,
    )
    import gradio as gr
    import uvicorn
    from bot import run_bot
    from ui.gradio_app import TarsGradioUI

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    small_webrtc_handler = SmallWebRTCRequestHandler()

    @app.post("/api/offer")
    async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
        async def callback(connection):
            background_tasks.add_task(run_bot, connection)
        return await small_webrtc_handler.handle_web_request(request, callback)

    @app.patch("/api/offer")
    async def ice_candidate(request: SmallWebRTCPatchRequest):
        await small_webrtc_handler.handle_patch_request(request)
        return {"status": "success"}

    ui = TarsGradioUI()
    demo = ui.build_interface()
    app = gr.mount_gradio_app(app, demo, path="/")

    logger.info(f"Browser mode at http://localhost:{port}")
    logger.info(f"  WebRTC offer: http://localhost:{port}/api/offer")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TARS Conversation App - Robot Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--gradio",
        action="store_true",
        help="Launch Gradio web UI at http://localhost:7860"
    )
    parser.add_argument(
        "--gradio-port",
        type=int,
        default=7860,
        help="Gradio UI port (default: 7860)"
    )
    parser.add_argument(
        "--browser-audio",
        action="store_true",
        help="Use browser mic/speaker via WebRTC (requires --gradio)"
    )
    parser.add_argument(
        "--local-audio",
        action="store_true",
        help="Use local mic/speaker instead of robot (not implemented yet)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Set log level
    if args.debug:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    # Check for unsupported options
    if args.local_audio:
        logger.error("--local-audio not implemented yet. Use robot mode only.")
        sys.exit(1)

    if args.browser_audio and not args.gradio:
        logger.error("--browser-audio requires --gradio")
        sys.exit(1)

    # Mode 3: browser audio + Gradio on a single server
    if args.browser_audio:
        from shared_state import metrics_store
        metrics_store.set_audio_mode("Browser (SmallWebRTC)")
        run_browser_mode(port=args.gradio_port)
        sys.exit(0)

    # Launch UI if requested
    if args.gradio:
        # Ensure src directory is first in path to avoid conflicts with root ui/ directory
        src_dir_str = str(Path(__file__).parent.resolve())
        if src_dir_str in sys.path:
            sys.path.remove(src_dir_str)
        sys.path.insert(0, src_dir_str)
        from ui.gradio_app import TarsGradioUI

        ui = TarsGradioUI()

        # Launch Gradio in background daemon thread
        # Note: Gradio's launch() is blocking, but runs its own uvicorn server
        # Running in daemon thread allows main asyncio loop to continue
        ui_thread = threading.Thread(
            target=lambda: ui.launch(port=args.gradio_port, share=False),
            daemon=True,
            name="GradioUI"
        )
        ui_thread.start()
        logger.info(f"🌐 Gradio UI starting at http://localhost:{args.gradio_port}")

        # Give UI time to start
        import time
        time.sleep(1)

    # Mode 1 / Mode 2: robot audio
    from shared_state import metrics_store
    metrics_store.set_audio_mode("Robot (WebRTC to Pi)")
    metrics_store.set_daemon_address(f"{RPI_URL} / gRPC: {get_robot_grpc_address()}")

    # Run pipeline
    try:
        asyncio.run(run_robot_bot(ui=ui if args.gradio else None))
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        metrics_store.set_pipeline_status("error")
        raise
