#!/usr/bin/env python
"""Test TARS gestures and movements."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from services.tars_robot import execute_movement, get_robot_client

async def test_gestures():
    """Test various TARS gestures."""
    # Connect to Pi
    get_robot_client("tars.local:50051")

    print("\nTest 1: side_side movement...")
    result = await execute_movement(["side_side"])
    print(f"Result: {result}")

    print("\nTest 2: wave_right movement...")
    result = await execute_movement(["wave_right"])
    print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(test_gestures())
