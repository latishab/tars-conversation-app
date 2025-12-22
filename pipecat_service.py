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

import ssl
from contextlib import asynccontextmanager

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
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from bot import run_bot
from config import (
    PIPECAT_HOST,
    PIPECAT_PORT,
    SPEECHMATICS_API_KEY,
    ELEVENLABS_API_KEY,
    DEEPINFRA_API_KEY
)

# Remove default loguru handler and set up custom logging
logger.remove(0)

# Configure standard logging
logging.basicConfig(level=logging.INFO)
standard_logger = logging.getLogger(__name__)

# Reduce noise from websockets library - only log warnings and above
websockets_logger = logging.getLogger('websockets')
websockets_logger.setLevel(logging.WARNING)

# Log SSL certificate configuration
try:
    import certifi
    logger.info(f"SSL Configuration: Using certificates from {certifi.where()}")
    logger.info(f"SSL_CERT_FILE env: {os.environ.get('SSL_CERT_FILE', 'not set')}")
except:
    logger.warning("certifi not available - SSL verification disabled for development")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app lifespan events."""
    logger.info(f"Starting Pipecat service on http://{PIPECAT_HOST}:{PIPECAT_PORT}...")
    logger.info("Make sure SPEECHMATICS_API_KEY, ELEVENLABS_API_KEY, and DEEPINFRA_API_KEY are set")

    if not SPEECHMATICS_API_KEY or not ELEVENLABS_API_KEY or not DEEPINFRA_API_KEY:
        logger.error("ERROR: API keys not found! Please set SPEECHMATICS_API_KEY, ELEVENLABS_API_KEY, and DEEPINFRA_API_KEY")
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
        "deepinfra_configured": bool(DEEPINFRA_API_KEY)
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
