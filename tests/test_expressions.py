#!/usr/bin/env python
"""Test TARS expressions: emotions and eye states."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from services.tars_robot import set_emotion, set_eye_state, get_robot_client

async def test_emotions():
    """Test all available emotions."""
    print("\n" + "="*50)
    print("EMOTION TESTS")
    print("="*50)

    # Connect to Pi
    get_robot_client("100.84.133.74:50051")

    # Available emotions based on Mood enum in modules_roboeyes.py
    emotions = [
        ("default", "Neutral/default expression"),
        ("happy", "Happy expression"),
        ("angry", "Angry expression"),
        ("tired", "Tired expression"),
        ("surprised", "Surprised expression"),
        ("confused", "Confused expression"),
    ]

    for emotion, description in emotions:
        print(f"\n{emotion.upper()}: {description}")
        result = await set_emotion(emotion)
        print(f"  Result: {result}")
        await asyncio.sleep(2)  # Show each emotion for 2 seconds

    print("\n✓ All emotions tested")

async def test_eye_states():
    """Test all available eye states."""
    print("\n" + "="*50)
    print("EYE STATE TESTS")
    print("="*50)

    # Connect to Pi
    get_robot_client("100.84.133.74:50051")

    # Available eye states based on EyeState enum
    eye_states = [
        ("idle", "Default state - relaxed eyes"),
        ("listening", "Microphone active - attentive eyes (triggered by audio input)"),
        ("thinking", "Processing - contemplative eyes (LLM processing)"),
        ("speaking", "TTS output - animated eyes (during speech)"),
    ]

    for state, description in eye_states:
        print(f"\n{state.upper()}: {description}")
        set_eye_state(state)
        print(f"  ✓ Set eye state to {state}")
        await asyncio.sleep(2)  # Show each state for 2 seconds

    print("\n✓ All eye states tested")

async def test_combined():
    """Test combined emotion + eye state scenarios."""
    print("\n" + "="*50)
    print("COMBINED EXPRESSION TESTS")
    print("="*50)

    # Connect to Pi
    get_robot_client("100.84.133.74:50051")

    scenarios = [
        ("listening", "confused", "TARS is listening to something confusing"),
        ("thinking", "confused", "TARS is processing something confusing"),
        ("speaking", "happy", "TARS is speaking happily"),
        ("idle", "default", "TARS returns to default state"),
    ]

    for eye_state, emotion, description in scenarios:
        print(f"\n{description}")
        print(f"  Eye state: {eye_state}, Emotion: {emotion}")
        set_eye_state(eye_state)
        await set_emotion(emotion)
        await asyncio.sleep(3)  # Show combination for 3 seconds

    print("\n✓ All combined scenarios tested")

async def run_all_tests():
    """Run all expression tests."""
    print("\n=== TARS Expression Test ===\n")

    # Test emotions
    await test_emotions()

    # Wait between test sections
    await asyncio.sleep(1)

    # Test eye states
    await test_eye_states()

    # Wait between test sections
    await asyncio.sleep(1)

    # Test combined
    await test_combined()

    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    print("\n✓ Expression tests complete")
    print("\nSupported emotions: default, happy, angry, tired, surprised, confused")
    print("Supported eye states: idle, listening, thinking, speaking")
    print("\nNOTE: In normal operation:")
    print("  - 'listening' auto-triggers when microphone receives audio")
    print("  - 'thinking' auto-triggers when LLM is processing")
    print("  - 'speaking' auto-triggers when TTS is playing")
    print("  - 'idle' is the default state")

if __name__ == "__main__":
    asyncio.run(run_all_tests())
