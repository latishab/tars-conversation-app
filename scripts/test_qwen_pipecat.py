#!/usr/bin/env python3
"""
Test Qwen3-TTS Pipecat service integration
"""

import asyncio
import soundfile as sf
import numpy as np
from services.tts_qwen import Qwen3TTSService
from loguru import logger
import sys

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


async def test_tts_service():
    """Test the Qwen3TTS Pipecat service"""
    print("=" * 60)
    print("Testing Qwen3-TTS Pipecat Service")
    print("=" * 60)

    # Initialize service
    print("\n🎤 Initializing Qwen3TTS service...")
    service = Qwen3TTSService(
        model_name="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        device="mps",
        ref_audio_path="tars-clean-compressed.mp3",
        x_vector_only_mode=True,
        sample_rate=24000,
    )

    # Test text
    test_texts = [
        "Hello, I am TARS. Your versatile AI companion.",
        "The mission is critical. We must maintain course.",
        "Humor setting is at seventy-five percent.",
    ]

    all_audio = []
    sample_rate = 24000

    for i, text in enumerate(test_texts):
        print(f"\n🔊 Test {i+1}: Generating: '{text}'")

        frames = []
        async for frame in service.run_tts(text):
            from pipecat.frames.frames import TTSAudioRawFrame

            if isinstance(frame, TTSAudioRawFrame):
                frames.append(frame)
                print(f"   ✓ Received audio frame: {len(frame.audio)} bytes")

        # Collect audio
        for frame in frames:
            audio_bytes = frame.audio
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            all_audio.append(audio_array)

    # Concatenate all audio
    if all_audio:
        full_audio = np.concatenate(all_audio)

        # Save output
        output_path = "test_pipecat_tts.wav"
        sf.write(output_path, full_audio, sample_rate)
        print(f"\n✓ Saved combined audio to: {output_path}")

        duration = len(full_audio) / sample_rate
        print(f"   Total duration: {duration:.2f}s")

    # Cleanup
    await service.close()

    print("\n" + "=" * 60)
    print("✅ Pipecat service test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_tts_service())
