#!/usr/bin/env python
"""Test TARS audio: speaker and microphone."""

import asyncio
import subprocess
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_audio_via_ssh():
    """Test Pi speaker and microphone directly via SSH."""

    print("\n=== TARS Audio Test ===\n")
    print("Testing audio at 100.84.133.74...")

    # ============ SPEAKER TESTS ============
    print("\n" + "="*50)
    print("SPEAKER TESTS")
    print("="*50)

    # Test 1: Check speaker device
    print("\n1. Checking audio output device...")
    result = subprocess.run(
        ["ssh", "tars-pi", "aplay -l | grep -i usb"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(f"✓ USB audio device found:\n{result.stdout}")
    else:
        print("✗ USB audio device not found")
        print("Checking all devices:")
        subprocess.run(["ssh", "tars-pi", "aplay -l"])

    # Test 2: Play friendly test melody
    print("\n2. Playing friendly test melody...")
    print("   (You should hear a pleasant melody from the Pi speaker)")

    # Play a friendly C-E-G ascending melody using beep command
    # If beep not available, fall back to softer speaker-test
    melody_cmd = (
        "if command -v beep >/dev/null 2>&1; then "
        "beep -f 523 -l 200 -n -f 659 -l 200 -n -f 784 -l 300 2>/dev/null; "
        "else "
        "speaker-test -t sine -f 523 -c 1 -l 1 -D default >/dev/null 2>&1 & "
        "sleep 0.2 && killall speaker-test 2>/dev/null; "
        "speaker-test -t sine -f 659 -c 1 -l 1 -D default >/dev/null 2>&1 & "
        "sleep 0.2 && killall speaker-test 2>/dev/null; "
        "speaker-test -t sine -f 784 -c 1 -l 1 -D default >/dev/null 2>&1 & "
        "sleep 0.3 && killall speaker-test 2>/dev/null; "
        "fi"
    )

    result = subprocess.run(
        ["ssh", "tars-pi", melody_cmd],
        timeout=5,
        capture_output=True,
        text=True
    )

    if result.returncode == 0 or "speaker-test" in str(result.stderr):
        print("✓ Test melody completed")
    else:
        print("✗ Failed to play test melody")

    # Test 3: Check daemon speaker status
    print("\n3. Checking daemon speaker status...")
    result = subprocess.run(
        ["ssh", "tars-pi", "tail -10 /tmp/tars_daemon.log | grep -i speaker"],
        capture_output=True,
        text=True
    )
    if result.stdout:
        print("Daemon speaker log:")
        print(result.stdout)
    else:
        print("No recent speaker activity in daemon logs")

    # ============ MICROPHONE TESTS ============
    print("\n" + "="*50)
    print("MICROPHONE TESTS")
    print("="*50)

    # Test 4: Check microphone device
    print("\n4. Checking audio input device...")
    result = subprocess.run(
        ["ssh", "tars-pi", "arecord -l | grep -i usb"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(f"✓ USB microphone found:\n{result.stdout}")
    else:
        print("✗ USB microphone not found")
        print("Checking all input devices:")
        subprocess.run(["ssh", "tars-pi", "arecord -l"])

    # Test 5: Record short audio sample
    print("\n5. Recording 5-second audio test...")
    print("   (Speak into the Pi microphone now!)")

    record_cmd = (
        "arecord -D hw:2,0 -f S16_LE -r 16000 -c 2 -d 5 "
        "/tmp/mic_test.wav 2>&1"
    )

    result = subprocess.run(
        ["ssh", "tars-pi", record_cmd],
        timeout=10,
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("✓ Recording completed")
        if result.stdout:
            print(f"  {result.stdout.strip()}")

        # Check file size
        size_result = subprocess.run(
            ["ssh", "tars-pi", "ls -lh /tmp/mic_test.wav | awk '{print $5}'"],
            capture_output=True,
            text=True
        )
        if size_result.stdout.strip():
            print(f"  Recorded file size: {size_result.stdout.strip()}")
    else:
        print("✗ Failed to record audio")
        if result.stderr:
            print(f"  Error: {result.stderr}")

    # Test 6: Play back the recording
    print("\n6. Playing back the recorded audio...")
    print("   (You should hear your voice from the Pi speaker)")

    playback_cmd = "aplay /tmp/mic_test.wav 2>&1 | head -1"

    result = subprocess.run(
        ["ssh", "tars-pi", playback_cmd],
        capture_output=True,
        text=True,
        timeout=10
    )

    if result.returncode == 0:
        print("✓ Playback completed")
        if result.stdout:
            print(f"  {result.stdout.strip()}")
    else:
        print("✗ Failed to play audio")

    # Test 7: Check daemon microphone status
    print("\n7. Checking daemon microphone status...")
    result = subprocess.run(
        ["ssh", "tars-pi", "tail -10 /tmp/tars_daemon.log | grep -i 'microphone\\|mic'"],
        capture_output=True,
        text=True
    )
    if result.stdout:
        print("Daemon microphone log:")
        print(result.stdout)
    else:
        print("No recent microphone activity in daemon logs")

    # ============ SUMMARY ============
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    print("\n✓ Audio hardware tests complete")
    print("\nTo test full audio pipeline:")
    print("  1. Make sure tars_bot.py is running and connected")
    print("  2. Talk to TARS via microphone")
    print("  3. TARS response should play through Pi speaker")

if __name__ == "__main__":
    test_audio_via_ssh()
