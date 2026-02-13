"""TTS Service Factory - Centralized TTS service creation."""

from loguru import logger
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from ..tts.tts_qwen import Qwen3TTSService


def create_tts_service(
    provider: str,
    elevenlabs_api_key: str = None,
    elevenlabs_voice_id: str = None,
    qwen_model: str = None,
    qwen_device: str = None,
    qwen_ref_audio: str = None,
):
    """
    Create and configure TTS service based on provider.

    Args:
        provider: "elevenlabs" or "qwen3"
        elevenlabs_api_key: ElevenLabs API key (if using elevenlabs)
        elevenlabs_voice_id: ElevenLabs voice ID (if using elevenlabs)
        qwen_model: Qwen3-TTS model name (if using qwen3)
        qwen_device: Device for Qwen3-TTS (if using qwen3)
        qwen_ref_audio: Reference audio path for Qwen3-TTS (if using qwen3)

    Returns:
        Configured TTS service instance

    Raises:
        ValueError: If provider is invalid or required parameters are missing
        Exception: If TTS service initialization fails
    """

    logger.info(f"Creating TTS service: {provider}")

    try:
        if provider == "qwen3":
            # Local Qwen3-TTS with voice cloning
            if not qwen_model:
                raise ValueError("qwen_model is required for Qwen3-TTS")

            logger.info("Using Qwen3-TTS (local, voice cloning)")
            tts = Qwen3TTSService(
                model_name=qwen_model,
                device=qwen_device or "mps",
                ref_audio_path=qwen_ref_audio,
                x_vector_only_mode=True,
                sample_rate=24000,
            )
            logger.info(f"✓ Qwen3-TTS service created (device: {qwen_device})")

        elif provider == "elevenlabs":
            # Cloud ElevenLabs TTS
            if not elevenlabs_api_key or not elevenlabs_voice_id:
                raise ValueError("elevenlabs_api_key and elevenlabs_voice_id are required for ElevenLabs")

            logger.info("Using ElevenLabs TTS")
            tts = ElevenLabsTTSService(
                api_key=elevenlabs_api_key,
                voice_id=elevenlabs_voice_id,
                model="eleven_flash_v2_5",
                output_format="pcm_24000",
                enable_word_timestamps=False,
                voice_settings={
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "use_speaker_boost": True
                },
                params=ElevenLabsTTSService.InputParams(
                    enable_logging=True,  # Enable ElevenLabs logging for metrics
                ),
            )
            logger.info("✓ ElevenLabs TTS service created")

        else:
            raise ValueError(f"Unknown TTS provider: {provider}. Must be 'qwen3' or 'elevenlabs'")

        return tts

    except Exception as e:
        logger.error(f"Failed to create TTS service '{provider}': {e}", exc_info=True)
        raise
