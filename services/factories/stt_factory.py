"""STT Service Factory - Centralized STT service creation."""

from loguru import logger
from pipecat.transcriptions.language import Language


def create_stt_service(
    provider: str,
    speechmatics_api_key: str = None,
    deepgram_api_key: str = None,
    language: Language = Language.EN,
    enable_diarization: bool = False,
):
    """
    Create and configure STT service based on provider.

    Args:
        provider: "speechmatics" or "deepgram"
        speechmatics_api_key: Speechmatics API key (if using speechmatics)
        deepgram_api_key: Deepgram API key (if using deepgram)
        language: Language for transcription (default: English)
        enable_diarization: Enable speaker diarization (default: False)

    Returns:
        Configured STT service instance

    Raises:
        ValueError: If provider is invalid or required parameters are missing
        Exception: If STT service initialization fails
    """

    logger.info(f"Creating STT service: {provider}")

    try:
        if provider == "speechmatics":
            # Lazy import to avoid requiring package when not in use
            from pipecat.services.speechmatics.stt import SpeechmaticsSTTService, TurnDetectionMode

            # Speechmatics with SMART_TURN mode for built-in turn detection
            if not speechmatics_api_key:
                raise ValueError("speechmatics_api_key is required for Speechmatics")

            logger.info("Using Speechmatics STT with SMART_TURN mode")
            stt_params = SpeechmaticsSTTService.InputParams(
                language=language,
                enable_diarization=enable_diarization,
                turn_detection_mode=TurnDetectionMode.SMART_TURN,
            )

            stt = SpeechmaticsSTTService(
                api_key=speechmatics_api_key,
                params=stt_params,
            )
            logger.info("✓ Speechmatics STT service created with SMART_TURN mode")

        elif provider == "deepgram":
            # Lazy import to avoid requiring package when not in use
            from pipecat.services.deepgram.stt import DeepgramSTTService

            # Deepgram STT
            if not deepgram_api_key:
                raise ValueError("deepgram_api_key is required for Deepgram")

            logger.info("Using Deepgram STT")
            stt_params = DeepgramSTTService.InputParams(
                language=language,
                model="nova-2",  # Deepgram's latest model
                interim_results=True,  # Enable interim transcription results
                smart_format=True,  # Auto-format transcripts
                punctuate=True,  # Add punctuation
                endpointing=300,  # 300ms silence for endpoint detection
            )

            stt = DeepgramSTTService(
                api_key=deepgram_api_key,
                params=stt_params,
            )
            logger.info("✓ Deepgram STT service created")

        else:
            raise ValueError(f"Unknown STT provider: {provider}. Must be 'speechmatics' or 'deepgram'")

        return stt

    except Exception as e:
        logger.error(f"Failed to create STT service '{provider}': {e}", exc_info=True)
        raise
