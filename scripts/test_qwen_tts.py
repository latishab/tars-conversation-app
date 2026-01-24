#!/usr/bin/env python3
"""
Test script for Qwen3-TTS voice cloning with TARS audio
"""

import time
import torch
import soundfile as sf
from qwen_tts import Qwen3TTSModel

def test_voice_clone():
    """Test voice cloning with TARS audio file"""
    print("🎤 Loading Qwen3-TTS Base model for voice cloning...")
    print(f"   Device: MPS (Metal Performance Shaders)")
    start = time.time()

    # Load the 0.6B model for voice cloning
    # IMPORTANT: Must use float32 for voice cloning on MPS
    model = Qwen3TTSModel.from_pretrained(
        "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        device_map="mps",
        dtype=torch.float32,  # Required for MPS voice cloning
    )
    load_time = time.time() - start
    print(f"✓ Model loaded in {load_time:.2f}s")

    # Load reference audio
    print("\n🎵 Loading TARS reference audio...")
    ref_audio_path = "tars-clean-compressed.mp3"

    # Test text to synthesize
    test_text = "Hello, I am TARS. Your versatile AI companion ready to assist."

    print(f"\n🔊 Generating speech with voice cloning...")
    print(f"   Text: '{test_text}'")

    # Measure inference latency
    start = time.time()

    # Use x_vector_only_mode=True to clone voice without transcript
    # This uses speaker embedding only (faster and simpler)
    wavs, sr = model.generate_voice_clone(
        text=test_text,
        language="English",
        ref_audio=ref_audio_path,
        x_vector_only_mode=True,  # Use speaker embedding only
    )

    inference_time = time.time() - start
    print(f"✓ Generated in {inference_time:.2f}s ({inference_time*1000:.0f}ms)")

    # Save output
    output_path = "test_tars_clone.wav"
    sf.write(output_path, wavs[0], sr)
    print(f"✓ Saved to: {output_path}")

    # Calculate audio duration
    duration = len(wavs[0]) / sr
    print(f"   Audio duration: {duration:.2f}s")
    print(f"   Real-time factor: {inference_time/duration:.2f}x")

    # Clear MPS cache
    torch.mps.empty_cache()

    return output_path, model

def test_custom_voice(model=None):
    """Test CustomVoice model with predefined speakers"""
    print("\n\n🎭 Testing CustomVoice with predefined speaker...")

    if model is None:
        print("🎤 Loading Qwen3-TTS CustomVoice model...")
        start = time.time()
        model = Qwen3TTSModel.from_pretrained(
            "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            device_map="mps",
            dtype=torch.float16,  # Can use float16 for CustomVoice
        )
        print(f"✓ Model loaded in {time.time() - start:.2f}s")

    test_text = "This is a test with emotion control. Feeling excited!"

    print(f"\n🔊 Generating with emotion...")
    start = time.time()

    wavs, sr = model.generate_custom_voice(
        text=test_text,
        language="English",
        speaker="Vivian",
        instruct="Very happy and excited."
    )

    inference_time = time.time() - start
    print(f"✓ Generated in {inference_time:.2f}s ({inference_time*1000:.0f}ms)")

    # Save output
    output_path = "test_custom_voice.wav"
    sf.write(output_path, wavs[0], sr)
    print(f"✓ Saved to: {output_path}")

    # Clear MPS cache
    torch.mps.empty_cache()

if __name__ == "__main__":
    print("=" * 60)
    print("Qwen3-TTS Voice Cloning Test")
    print("=" * 60)

    try:
        # Test voice cloning
        output_path, model = test_voice_clone()

        print(f"\n🎧 Test completed! Listen to: {output_path}")

        print("\n" + "=" * 60)
        print("✅ Voice cloning test completed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
