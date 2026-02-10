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
        provider: "speechmatics", "deepgram", or "deepgram-flux"
        speechmatics_api_key: Speechmatics API key (if using speechmatics)
        deepgram_api_key: Deepgram API key (if using deepgram/deepgram-flux)
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
            from deepgram.clients.listen.v1.websocket.options import LiveOptions

            # Deepgram STT with server-side endpointing for turn detection
            # Note: This uses Deepgram's server-side silence detection, not local smart turn
            if not deepgram_api_key:
                raise ValueError("deepgram_api_key is required for Deepgram")

            logger.info("Using Deepgram STT with server-side endpointing")
            live_options = LiveOptions(
                language=language.value if hasattr(language, 'value') else str(language),
                model="nova-2",  # Deepgram's latest model
                interim_results=True,  # Enable interim transcription results
                smart_format=True,  # Auto-format transcripts
                punctuate=True,  # Add punctuation
                endpointing=300,  # 300ms silence to detect end of speech (server-side)
                vad_events=True,  # Enable VAD events for speech detection
            )

            stt = DeepgramSTTService(
                api_key=deepgram_api_key,
                live_options=live_options,
                stt_ttfb_timeout=5.0,  # TTFB timeout for transcription (seconds)
            )
            logger.info("✓ Deepgram STT service created")
            logger.info("  Turn detection: Server-side endpointing (300ms silence)")
            logger.info("  VAD events: Enabled for speech detection")
            logger.info("  TTFB timeout: 5.0s for transcription metrics")

        elif provider == "deepgram-flux":
            # Lazy import to avoid requiring package when not in use
            from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService

            # Deepgram Flux with built-in turn detection
            if not deepgram_api_key:
                raise ValueError("deepgram_api_key is required for Deepgram Flux")

            logger.info("Using Deepgram Flux STT with built-in turn detection")
            # Flux has different parameters - uses EOT (End of Transcript) detection
            # Default model is "flux-general-en" and encoding is "linear16"
            stt_params = DeepgramFluxSTTService.InputParams(
                min_confidence=0.3,  # Minimum confidence threshold for accepting transcriptions
                # Optional: Configure end-of-turn detection thresholds
                # eot_threshold: Confidence threshold for detecting end of turn (0.0-1.0)
                # eot_timeout_ms: Max time to wait before forcing turn end
                # eager_eot_threshold: More aggressive turn ending threshold
            )

            stt = DeepgramFluxSTTService(
                api_key=deepgram_api_key,
                model="flux-general-en",  # Flux model for general English
                params=stt_params,
            )

            # Set up debug event handler for Flux updates
            @stt.event_handler("on_update")
            async def on_flux_update(stt_service, transcript):
                logger.debug(f"[Deepgram Flux] Update: {transcript}")

            logger.info("✓ Deepgram Flux STT service created with built-in turn detection")
            logger.info("  Note: STT latency will be tracked via MetricsFrame if emitted by Flux")

        else:
            raise ValueError(f"Unknown STT provider: {provider}. Must be 'speechmatics', 'deepgram', or 'deepgram-flux'")

        return stt

    except Exception as e:
        logger.error(f"Failed to create STT service '{provider}': {e}", exc_info=True)
        raise
