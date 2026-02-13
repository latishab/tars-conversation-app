"""
Connection mode detection and configuration.

Auto-detects whether running locally (on Pi) or remotely (Mac/computer)
and provides appropriate TarsClient and audio transport.
"""

import socket
from typing import Tuple, Optional
from loguru import logger

from . import config, is_raspberry_pi, get_robot_grpc_address


def detect_local_daemon() -> bool:
    """
    Check if tars_daemon is running on localhost.

    Returns:
        True if gRPC daemon is available on localhost:50051
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex(("localhost", 50051))
        sock.close()
        return result == 0
    except Exception as e:
        logger.debug(f"Error checking local daemon: {e}")
        return False


def get_connection_mode() -> str:
    """
    Detect connection mode: 'local' or 'remote'.

    Detection logic:
    1. Check explicit config.ini setting (if mode=local/remote)
    2. Check if running on Raspberry Pi (/proc/cpuinfo)
    3. Check if daemon running on localhost:50051
    4. Default to remote

    Returns:
        'local' or 'remote'
    """
    # Check explicit config
    explicit_mode = config.get("Connection", "deployment_mode", fallback=None)
    if explicit_mode in ("local", "remote"):
        logger.info(f"Using explicit connection mode from config: {explicit_mode}")
        return explicit_mode

    # Check if running on Raspberry Pi
    if is_raspberry_pi():
        logger.info("Detected Raspberry Pi - using local mode")
        return "local"

    # Check if daemon running on localhost
    if detect_local_daemon():
        logger.info("Detected local daemon on localhost:50051 - using local mode")
        return "local"

    # Default to remote
    logger.info("Using remote mode")
    return "remote"


def get_tars_client(mode: Optional[str] = None):
    """
    Get configured TarsClient for current mode.

    Args:
        mode: Override mode ('local' or 'remote'). None for auto-detect.

    Returns:
        TarsClient instance configured for the mode
    """
    try:
        from tars_sdk import TarsClient
    except ImportError:
        logger.error("tars_sdk not installed. Install with: pip install tars-sdk")
        raise

    if mode is None:
        mode = get_connection_mode()

    address = get_robot_grpc_address() if mode == "local" else config.get(
        "Connection", "rpi_grpc", fallback="100.115.193.41:50051"
    )

    logger.info(f"Creating TarsClient for {mode} mode: {address}")
    return TarsClient(address=address)


def get_async_tars_client(mode: Optional[str] = None):
    """
    Get configured AsyncTarsClient for current mode.

    Args:
        mode: Override mode ('local' or 'remote'). None for auto-detect.

    Returns:
        AsyncTarsClient instance configured for the mode
    """
    try:
        from tars_sdk import AsyncTarsClient
    except ImportError:
        logger.error("tars_sdk not installed. Install with: pip install tars-sdk")
        raise

    if mode is None:
        mode = get_connection_mode()

    address = get_robot_grpc_address() if mode == "local" else config.get(
        "Connection", "rpi_grpc", fallback="100.115.193.41:50051"
    )

    logger.info(f"Creating AsyncTarsClient for {mode} mode: {address}")
    return AsyncTarsClient(address=address)


def get_audio_transport(mode: Optional[str] = None) -> Tuple:
    """
    Get appropriate audio transport for current mode.

    Args:
        mode: Override mode ('local' or 'remote'). None for auto-detect.

    Returns:
        Tuple of (audio_source, audio_sink) configured for the mode.
        - Local mode: (LocalAudioSource, LocalAudioSink)
        - Remote mode: (RPiAudioInputTrack, RPiAudioOutputTrack)
    """
    if mode is None:
        mode = get_connection_mode()

    if mode == "local":
        logger.info("Using local audio transport (sounddevice)")
        try:
            from ..transport.local_audio import LocalAudioSource, LocalAudioSink
            return (LocalAudioSource(), LocalAudioSink())
        except ImportError as e:
            logger.error(f"Failed to import local audio transport: {e}")
            raise
    else:
        logger.info("Using remote audio transport (WebRTC)")
        try:
            from ..transport.audio_bridge import RPiAudioInputTrack, RPiAudioOutputTrack
            # Note: These need to be configured with aiortc tracks after WebRTC connection
            return (RPiAudioInputTrack, RPiAudioOutputTrack)
        except ImportError as e:
            logger.error(f"Failed to import WebRTC audio transport: {e}")
            raise


def get_audio_config(mode: Optional[str] = None) -> dict:
    """
    Get audio configuration for current mode.

    Args:
        mode: Override mode ('local' or 'remote'). None for auto-detect.

    Returns:
        Dictionary with audio configuration:
        - mode: 'local' or 'remote'
        - input_sample_rate: Microphone sample rate
        - output_sample_rate: Speaker sample rate
        - input_device: Microphone device (None for default)
        - output_device: Speaker device (None for default)
    """
    if mode is None:
        mode = get_connection_mode()

    return {
        "mode": mode,
        "input_sample_rate": 16000,  # 16kHz for STT
        "output_sample_rate": 24000,  # 24kHz for TTS
        "input_device": None,  # Use default
        "output_device": None,  # Use default
    }
