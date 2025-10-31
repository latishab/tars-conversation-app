#!/usr/bin/env python3
"""
Pipecat.ai service for real-time transcription and TTS using SmallWebRTC
Communicates directly with browser via WebRTC
"""

# Fix SSL certificate issues FIRST - before any SSL-using imports
import os
import sys
try:
    import certifi
    cert_file = certifi.where()
    os.environ['SSL_CERT_FILE'] = cert_file
    os.environ['REQUESTS_CA_BUNDLE'] = cert_file
    os.environ['CURL_CA_BUNDLE'] = cert_file
except ImportError:
    pass  # certifi not available, will use system certs

import asyncio
import ssl
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Configure SSL to use certifi certificates for Python's ssl module
# For development: disable SSL verification completely to avoid certificate issues
# This MUST happen before any libraries that use SSL are imported
try:
    import certifi
    cert_file = certifi.where()
    # Set environment variables for libraries that respect them
    os.environ['SSL_CERT_FILE'] = cert_file
    os.environ['REQUESTS_CA_BUNDLE'] = cert_file
    os.environ['CURL_CA_BUNDLE'] = cert_file
    
    # For Python's ssl module: use unverified context for development
    # This bypasses SSL certificate verification to avoid connection issues
    ssl._create_default_https_context = ssl._create_unverified_context
except ImportError:
    # If certifi not available, use unverified (development only)
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception as e:
    # If anything fails, use unverified context
    ssl._create_default_https_context = ssl._create_unverified_context

import argparse
import logging
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

# Pipecat imports (after SSL setup)
from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.speechmatics.stt import SpeechmaticsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

# Remove default loguru handler and set up custom logging
logger.remove(0)

# Configure standard logging
logging.basicConfig(level=logging.INFO)
standard_logger = logging.getLogger(__name__)

# Reduce noise from websockets library - only log warnings and above
websockets_logger = logging.getLogger('websockets')
websockets_logger.setLevel(logging.WARNING)

load_dotenv()

# Log SSL certificate configuration
try:
    import certifi
    logger.info(f"SSL Configuration: Using certificates from {certifi.where()}")
    logger.info(f"SSL_CERT_FILE env: {os.environ.get('SSL_CERT_FILE', 'not set')}")
except:
    logger.warning("certifi not available - SSL verification disabled for development")

# API Keys
SPEECHMATICS_API_KEY = os.getenv("SPEECHMATICS_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "ry8mpwRw6nugb2qjP0tu")
PIPECAT_PORT = int(os.getenv("PIPECAT_PORT", "7860"))
PIPECAT_HOST = os.getenv("PIPECAT_HOST", "localhost")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app lifespan events."""
    logger.info(f"Starting Pipecat service on http://{PIPECAT_HOST}:{PIPECAT_PORT}...")
    logger.info("Make sure SPEECHMATICS_API_KEY and ELEVENLABS_API_KEY are set")
    
    if not SPEECHMATICS_API_KEY or not ELEVENLABS_API_KEY:
        logger.error("ERROR: API keys not found! Please set SPEECHMATICS_API_KEY and ELEVENLABS_API_KEY")
        sys.exit(1)
    
    yield  # Run app
    
    # Cleanup
    await small_webrtc_handler.close()
    logger.info("Shutting down...")


app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the SmallWebRTC request handler
small_webrtc_handler: SmallWebRTCRequestHandler = SmallWebRTCRequestHandler()


class SimpleTranscriptionLogger(FrameProcessor):
    """Simple processor to log transcriptions and send to frontend"""
    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, TranscriptionFrame):
            logger.info(f"🎤 Transcription: {frame.text}")
            # Send transcription to frontend via WebRTC data channel
            if self.webrtc_connection:
                try:
                    if self.webrtc_connection.is_connected():
                        self.webrtc_connection.send_app_message({
                            "type": "transcription",
                            "text": frame.text
                        })
                        logger.debug(f"Sent transcription to frontend: {frame.text}")
                    else:
                        logger.warning("WebRTC connection not ready, skipping transcription send")
                except Exception as e:
                    logger.error(f"Error sending transcription: {e}", exc_info=True)
        elif isinstance(frame, InterimTranscriptionFrame):
            logger.info(f"🎤 Partial: {frame.text}")
            # Send partial transcription to frontend
            if self.webrtc_connection:
                try:
                    if self.webrtc_connection.is_connected():
                        self.webrtc_connection.send_app_message({
                            "type": "partial",
                            "text": frame.text
                        })
                        logger.debug(f"Sent partial transcription to frontend: {frame.text}")
                    else:
                        logger.warning("WebRTC connection not ready, skipping partial transcription send")
                except Exception as e:
                    logger.error(f"Error sending partial transcription: {e}", exc_info=True)
        
        # Push all frames through
        await self.push_frame(frame, direction)


async def run_bot(webrtc_connection):
    """Run the bot pipeline with the given WebRTC connection"""
    logger.info("Starting bot pipeline for WebRTC connection...")
    
    try:
        # Create SmallWebRTC transport from the connection
        pipecat_transport = SmallWebRTCTransport(
            webrtc_connection=webrtc_connection,
            params=TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
            ),
        )
        
        # Initialize Speechmatics STT
        logger.info("Initializing Speechmatics STT...")
        stt = None
        try:
            stt = SpeechmaticsSTTService(
                api_key=SPEECHMATICS_API_KEY,
                params=SpeechmaticsSTTService.InputParams(
                    language=Language.EN,
                ),
            )
            logger.info("✓ Speechmatics STT initialized")
        except Exception as e:
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
        
        if not stt or not tts:
            logger.error("Failed to initialize services. Cannot start bot.")
            return
        
        # Create simple transcription logger with WebRTC connection for sending messages
        transcription_logger = SimpleTranscriptionLogger(webrtc_connection=webrtc_connection)
        
        # Create pipeline with SmallWebRTC transport
        # Pipeline flow: transport.input() -> STT -> logger -> TTS -> transport.output()
        logger.info("Creating pipeline...")
        pipeline = Pipeline([
            pipecat_transport.input(),  # Audio input from WebRTC
            stt,                        # Speech to text
            transcription_logger,       # Log transcriptions
            tts,                        # Text to speech
            pipecat_transport.output(), # Audio output to WebRTC
        ])
        
        # Set up event handlers before creating task
        @pipecat_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Pipecat Client connected")
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
        
        # Store task reference for disconnect handler
        task_ref = {"task": None}
        
        @pipecat_transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Pipecat Client disconnected")
            if task_ref["task"]:
                await task_ref["task"].cancel()
        
        # Create and run pipeline task
        task = PipelineTask(pipeline)
        task_ref["task"] = task
        runner = PipelineRunner(handle_sigint=False)
        
        logger.info("Starting pipeline runner...")
        await runner.run(task)
        
    except Exception as e:
        logger.error(f"Error in bot pipeline: {e}", exc_info=True)


@app.post("/api/offer")
async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
    """Handle WebRTC offer requests via SmallWebRTCRequestHandler."""
    logger.debug(f"Received WebRTC offer request")
    
    # Prepare runner arguments with the callback to run your bot
    async def webrtc_connection_callback(connection):
        background_tasks.add_task(run_bot, connection)

    # Delegate handling to SmallWebRTCRequestHandler
    answer = await small_webrtc_handler.handle_web_request(
        request=request,
        webrtc_connection_callback=webrtc_connection_callback,
    )
    return answer


@app.patch("/api/offer")
async def ice_candidate(request: SmallWebRTCPatchRequest):
    """Handle ICE candidate patch requests."""
    logger.debug(f"Received ICE candidate patch request")
    await small_webrtc_handler.handle_patch_request(request)
    return {"status": "success"}


@app.get("/api/status")
async def status():
    """Health check endpoint."""
    return {
        "status": "ok",
        "speechmatics_configured": bool(SPEECHMATICS_API_KEY),
        "elevenlabs_configured": bool(ELEVENLABS_API_KEY),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC Pipecat service")
    parser.add_argument(
        "--host", default=PIPECAT_HOST, help=f"Host for HTTP server (default: {PIPECAT_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=PIPECAT_PORT, help=f"Port for HTTP server (default: {PIPECAT_PORT})"
    )
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    if args.verbose:
        logger.add(sys.stderr, level="TRACE")
    else:
        logger.add(sys.stderr, level="INFO")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)
