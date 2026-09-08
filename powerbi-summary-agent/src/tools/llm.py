"""LLM factory. Provider-agnostic: Azure OpenAI (default), Anthropic, or plain OpenAI,
chosen via config / the LLM_PROVIDER env var.

Azure OpenAI is driven entirely by the AZURE_OPENAI_* environment variables
(see .env): endpoint, api key, deployment name, and api version. The `model`
config value is ignored for Azure -- the deployment name is what routes.
Switch providers by editing config.json (ai_provider / model / *_api_key_env)
or by setting LLM_PROVIDER in the environment.
"""

import os

from . import token_usage


def get_llm(state: dict, structured_schema=None):
    """Return a LangChain chat model. If structured_schema is given, the model is
    wrapped with .with_structured_output so it returns a validated pydantic object.

    Every model is built with a `token_usage.UsageRecorder` attached, labelled
    with the calling module, so a run's spend is auditable per node from
    `token_usage.json` without correlating billing metrics after the fact.
    Recording never raises and never sees the model's output.
    """
    provider = (state.get("ai_provider") or "azure_openai").lower()
    model = state.get("model") or "claude-sonnet-5"
    max_tokens = int(state.get("max_tokens", 4096))
    label = token_usage.caller_label()
    token_usage.set_dump_path(state.get("output_folder") or "outputs")

    if provider in ("azure_openai", "azure"):
        from langchain_openai import AzureChatOpenAI

        key_env = state.get("config", {}).get("azure_openai_api_key_env", "AZURE_OPENAI_API_KEY")
        api_key = os.environ.get(key_env)
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or model
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

        # Per-node model routing. Schema-bound, structured-output nodes (DAX
        # generation and repair) are already gated by a deterministic validator
        # and a repair loop, so a cheaper model that writes worse DAX is caught
        # rather than published - while the prose nodes stay on the flagship,
        # where quality is the product. Absent config routes everything to
        # AZURE_OPENAI_DEPLOYMENT exactly as before.
        overrides = state.get("node_model_overrides") or {}
        if isinstance(overrides, dict) and label in overrides:
            candidate = str(overrides[label] or "").strip()
            if candidate:
                deployment = candidate

        missing = [
            name for name, val in (
                (key_env, api_key),
                ("AZURE_OPENAI_ENDPOINT", endpoint),
                ("AZURE_OPENAI_DEPLOYMENT", deployment),
            ) if not val
        ]
        if missing:
            raise RuntimeError(
                "Azure OpenAI provider selected but these env vars are not set: "
                + ", ".join(missing)
                + ". Populate powerbi-summary-agent/.env."
            )
        # max_retries lets the SDK ride out transient 429 bursts (it honors the
        # Retry-After header). It does NOT help if the deployment's TPM quota is
        # structurally smaller than a single request -- raise the quota for that.
        llm = AzureChatOpenAI(
            azure_deployment=deployment,
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            max_tokens=max_tokens,
            timeout=120,
            max_retries=int(state.get("config", {}).get("llm_max_retries", 6)),
            callbacks=[token_usage.UsageRecorder(label, deployment)],
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        key_env = state.get("config", {}).get("anthropic_api_key_env", "ANTHROPIC_API_KEY")
        if not os.environ.get(key_env):
            raise RuntimeError(
                f"Anthropic provider selected but {key_env} is not set in the environment."
            )
        llm = ChatAnthropic(model=model, max_tokens=max_tokens, timeout=120,
                            callbacks=[token_usage.UsageRecorder(label, model)])

    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        key_env = state.get("config", {}).get("openai_api_key_env", "OPENAI_API_KEY")
        if not os.environ.get(key_env):
            raise RuntimeError(
                f"OpenAI provider selected but {key_env} is not set in the environment."
            )
        llm = ChatOpenAI(model=model, max_tokens=max_tokens, timeout=120,
                         callbacks=[token_usage.UsageRecorder(label, model)])

    else:
        raise ValueError(f"Unknown ai_provider: {provider!r}")

    if structured_schema is not None:
        return llm.with_structured_output(structured_schema)
    return llm
