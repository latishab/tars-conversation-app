#!/usr/bin/env python3
"""
Test WebRTC connection to Raspberry Pi TARS robot.

This script tests the basic WebRTC connection without the full pipeline.
"""

import asyncio
import sys
from loguru import logger

from config import RPI_URL
from transport import AiortcRPiClient, StateSync


async def test_connection():
    """Test WebRTC connection to RPi."""
    logger.info("=" * 60)
    logger.info("🧪 Testing WebRTC Connection to RPi")
    logger.info("=" * 60)
    logger.info(f"RPi URL: {RPI_URL}")

    # Create client
    client = AiortcRPiClient(
        rpi_url=RPI_URL,
        auto_reconnect=False,
        reconnect_delay=5,
        max_reconnect_attempts=0,
    )

    # Create state sync
    state_sync = StateSync()

    # Set up event handlers
    connection_established = asyncio.Event()
    audio_track_received = asyncio.Event()

    @client.on_connected
    async def on_connected():
        logger.info("✅ WebRTC connection established!")
        state_sync.set_send_callback(client.send_data_channel_message)
        connection_established.set()

    @client.on_disconnected
    async def on_disconnected():
        logger.warning("⚠️  WebRTC connection lost")

    @client.on_audio_track
    async def on_audio_track(track):
        logger.info(f"✅ Audio track received: {track.kind}")
        audio_track_received.set()

    @client.on_data_channel_message
    def on_data_message(message: str):
        logger.info(f"📡 DataChannel message: {message}")
        state_sync.handle_message(message)

    # Register message handlers
    state_sync.on_battery_update(lambda level, charging:
        logger.info(f"🔋 Battery: {level}% ({'charging' if charging else 'discharging'})"))

    state_sync.on_connected(lambda client_name:
        logger.info(f"👋 Connected client: {client_name}"))

    state_sync.on_movement_status(lambda moving, movement:
        logger.info(f"🚶 Movement: {movement} ({'active' if moving else 'idle'})"))

    try:
        # Connect to RPi
        logger.info("🔌 Connecting to RPi...")
        success = await client.connect()

        if not success:
            logger.error("❌ Failed to connect to RPi")
            logger.error("   Make sure:")
            logger.error("   1. RPi is running (sudo systemctl status tars)")
            logger.error("   2. RPi IP address is correct in config.ini")
            logger.error("   3. Network connection is working")
            return False

        # Wait for connection to be established
        logger.info("⏳ Waiting for connection to establish...")
        try:
            await asyncio.wait_for(connection_established.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("❌ Connection timeout")
            return False

        # Wait for audio track
        logger.info("⏳ Waiting for audio track...")
        try:
            await asyncio.wait_for(audio_track_received.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("⚠️  No audio track received (this is expected in test mode)")

        # Test DataChannel
        logger.info("📤 Testing DataChannel...")
        state_sync.send_eye_state("listening")
        state_sync.send_emotion("happy")
        state_sync.send_transcript("user", "Hello TARS!")

        # Keep connection alive for a bit
        logger.info("✅ Connection test successful!")
        logger.info("🔗 Keeping connection alive for 5 seconds...")
        await asyncio.sleep(5)

        # Test state updates
        logger.info("📤 Sending more state updates...")
        state_sync.send_eye_state("thinking")
        await asyncio.sleep(1)
        state_sync.send_eye_state("speaking")
        await asyncio.sleep(1)
        state_sync.send_tts_state(True)
        await asyncio.sleep(1)
        state_sync.send_tts_state(False)
        await asyncio.sleep(1)
        state_sync.send_eye_state("idle")

        logger.info("✅ All tests passed!")
        return True

    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
        return False
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False
    finally:
        # Cleanup
        logger.info("🧹 Disconnecting...")
        await client.disconnect()
        logger.info("✓ Test complete")


if __name__ == "__main__":
    # Set up logging
    logger.remove(0)
    logger.add(sys.stderr, level="INFO")

    # Run test
    result = asyncio.run(test_connection())
    sys.exit(0 if result else 1)
