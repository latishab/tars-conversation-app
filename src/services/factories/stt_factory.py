"""STT Service Factory - Centralized STT service creation."""

from loguru import logger
from pipecat.transcriptions.language import Language


def create_stt_service(
    provider: str,
    speechmatics_api_key: str = None,
    deepgram_api_key: str = None,
    soniox_api_key: str = None,
    deepgram_model: str = "nova-3",
    deepgram_endpointing: int = 100,
    soniox_model: str = "stt-rt-v4",
    language: Language = Language.EN,
    enable_diarization: bool = False,
):
    """
    Create and configure STT service based on provider.

    Args:
        provider: "speechmatics", "deepgram", "deepgram-flux", "parakeet", "soniox-jp", or "soniox-us"
        speechmatics_api_key: Speechmatics API key (if using speechmatics)
        deepgram_api_key: Deepgram API key (if using deepgram/deepgram-flux)
        soniox_api_key: Soniox API key (if using soniox-jp or soniox-us)
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

            logger.info(f"Using Deepgram STT ({deepgram_model}) with Silero VAD turn detection")
            live_options = LiveOptions(
                language=language.value if hasattr(language, 'value') else str(language),
                model=deepgram_model,
                interim_results=True,
                smart_format=True,
                punctuate=True,
                # endpointing: VAD is inside LLMUserAggregator (downstream of Deepgram),
                # so VADUserStoppedSpeakingFrame never reaches Deepgram and finalize() is
                # never called. Without server-side endpointing, short utterances never get
                # a final transcript. Value should be < VAD stop_secs (200ms) so the
                # transcript arrives before the turn closes.
                endpointing=deepgram_endpointing,
            )

            stt = DeepgramSTTService(
                api_key=deepgram_api_key,
                live_options=live_options,
                stt_ttfb_timeout=1.0,  # TTFB timeout; must be < next turn gap to avoid wrong-turn attribution
            )
            logger.info("✓ Deepgram STT service created")
            logger.info(f"  Model: {deepgram_model}, endpointing: {deepgram_endpointing}ms")
            logger.info("  TTFB timeout: 1.0s for transcription metrics")

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

        elif provider == "parakeet":
            from src.services.stt.parakeet import ParakeetSTTService

            # Requires Silero VAD upstream in pipeline (same as nova-3 branch)
            logger.info("Using Parakeet TDT v3 STT (local MLX, streaming)")
            stt = ParakeetSTTService()
            logger.info("✓ Parakeet STT service created")

        elif provider in ("soniox-jp", "soniox-us"):
            from pipecat.services.soniox.stt import (
                SonioxSTTService, SonioxInputParams,
                SonioxContextObject, SonioxContextGeneralItem,
            )

            if not soniox_api_key:
                raise ValueError(f"soniox_api_key is required for {provider}")

            region_urls = {
                "soniox-jp": "wss://stt-rt.jp.soniox.com/transcribe-websocket",
                "soniox-us": "wss://stt-rt.soniox.com/transcribe-websocket",
            }
            url = region_urls[provider]
            region = provider.split("-")[1].upper()

            stt_context = SonioxContextObject(
                general=[
                    SonioxContextGeneralItem(key="assistant_name", value="TARS"),
                    SonioxContextGeneralItem(key="domain", value="conversational AI assistant"),
                ],
                terms=["TARS"],
            )

            # vad_force_turn_endpoint=True: VAD-driven finalization instead of Soniox's
            # built-in semantic endpoint detection. Reduces time to final segment to
            # ~250ms median.
            logger.info(f"Using Soniox STT ({region}) with VAD-driven endpoint")
            stt = SonioxSTTService(
                api_key=soniox_api_key,
                url=url,
                params=SonioxInputParams(model=soniox_model, context=stt_context),
                vad_force_turn_endpoint=True,
            )
            logger.info(f"✓ Soniox STT service created ({region}, {soniox_model})")

        else:
            raise ValueError(f"Unknown STT provider: {provider}. Must be 'speechmatics', 'deepgram', 'deepgram-flux', 'parakeet', 'soniox-jp', or 'soniox-us'")

        return stt

    except Exception as e:
        logger.error(f"Failed to create STT service '{provider}': {e}", exc_info=True)
        raise


_STT_DISPLAY_NAMES = {
    "speechmatics": "Speechmatics",
    "deepgram": "Deepgram Nova-3",
    "deepgram-flux": "Deepgram Flux",
    "parakeet": "Parakeet TDT v3 (local)",
    "soniox-jp": "Soniox v4 (JP)",
    "soniox-us": "Soniox v4 (US)",
}


def stt_display_name(provider: str) -> str:
    """Return a human-readable display name for an STT provider."""
    return _STT_DISPLAY_NAMES.get(provider, provider.capitalize())
