"""LLM Service Factory - Centralized LLM service creation."""

from loguru import logger


class _GoogleAILLMService:
    """OpenAILLMService subclass that injects reasoning_effort=none to disable thinking."""

    @classmethod
    def create(cls, **kwargs):
        from pipecat.services.openai.llm import OpenAILLMService

        class GoogleAILLMService(OpenAILLMService):
            def build_chat_completion_params(self, params_from_context):
                params = super().build_chat_completion_params(params_from_context)
                params["reasoning_effort"] = "none"
                return params

        return GoogleAILLMService(**kwargs)


def create_llm_service(
    provider: str,
    model: str,
    api_key: str = None,
    base_url: str = None,
    **kwargs,
):
    """
    Create and configure an LLM service based on provider.

    Args:
        provider: "cerebras", "google", or "openai" (also covers DeepInfra/compatible endpoints)
        model: Model name / path
        api_key: API key for the provider
        base_url: Base URL for OpenAI-compatible endpoints
        **kwargs: Passed through to the service (e.g. function_call_timeout_secs)

    Returns:
        Configured LLM service instance
    """
    logger.info(f"Creating LLM service: {provider} / {model}")

    try:
        if provider == "cerebras":
            from pipecat.services.cerebras.llm import CerebrasLLMService
            llm = CerebrasLLMService(api_key=api_key, model=model, **kwargs)

        elif provider == "google":
            # Google AI Studio via OpenAI-compat endpoint, thinking disabled
            llm = _GoogleAILLMService.create(
                api_key=api_key,
                base_url=base_url,
                model=model,
                **kwargs,
            )

        else:
            # OpenAI-compatible: DeepInfra, OpenAI, etc.
            from pipecat.services.openai.llm import OpenAILLMService
            llm = OpenAILLMService(
                api_key=api_key,
                base_url=base_url,
                model=model,
                **kwargs,
            )

        logger.info(f"LLM service created: {provider} / {model}")
        return llm

    except Exception as e:
        logger.error(f"Failed to create LLM service '{provider}': {e}", exc_info=True)
        raise
