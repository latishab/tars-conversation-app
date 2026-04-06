"""LLM Service Factory - Centralized LLM service creation."""

from loguru import logger


def _sanitise_tool_calls(messages: list) -> list:
    """Remove orphaned tool call entries that lack a matching tool result.

    When a tool call response (role: "tool") is dropped from the conversation
    history (e.g. due to an interruption or context compaction), the preceding
    assistant message still contains a tool_calls entry whose ID no longer has
    a matching result. LLM providers reject this with a 422 error.

    This function scans the messages list and removes any tool_call entries
    from assistant messages that don't have a corresponding tool result. If
    all tool_calls on an assistant message are orphaned, the entire message
    is removed.
    """
    # Collect all tool_call_ids that have a matching tool result
    result_ids = set()
    for m in messages:
        if m.get("role") == "tool" and "tool_call_id" in m:
            result_ids.add(m["tool_call_id"])

    # Collect all tool_call_ids that assistant messages request
    call_ids = set()
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                if "id" in tc:
                    call_ids.add(tc["id"])

    sanitised = []
    dropped = 0
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            matched = [tc for tc in m["tool_calls"] if tc.get("id") in result_ids]
            if not matched:
                # All tool_calls are orphaned — drop the entire message
                dropped += len(m["tool_calls"])
                continue
            if len(matched) < len(m["tool_calls"]):
                dropped += len(m["tool_calls"]) - len(matched)
                m = {**m, "tool_calls": matched}
        elif m.get("role") == "tool" and m.get("tool_call_id") not in call_ids:
            # Orphaned tool result with no matching assistant tool_call
            dropped += 1
            continue
        sanitised.append(m)

    if dropped:
        logger.warning(f"Sanitised {dropped} orphaned tool call(s) from conversation history")
    return sanitised


def _patch_sanitisation(llm):
    """Wrap build_chat_completion_params to sanitise messages before every LLM call."""
    original = llm.build_chat_completion_params

    def sanitised_build(params_from_context):
        if "messages" in params_from_context:
            params_from_context["messages"] = _sanitise_tool_calls(
                params_from_context["messages"]
            )
        return original(params_from_context)

    llm.build_chat_completion_params = sanitised_build
    return llm


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
        return _patch_sanitisation(llm)

    except Exception as e:
        logger.error(f"Failed to create LLM service '{provider}': {e}", exc_info=True)
        raise
