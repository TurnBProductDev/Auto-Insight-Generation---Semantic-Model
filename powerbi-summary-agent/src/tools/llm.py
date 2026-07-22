"""LLM factory. Provider-agnostic: Azure OpenAI (default), Anthropic, or plain OpenAI,
chosen via config / the LLM_PROVIDER env var.

Azure OpenAI is driven entirely by the AZURE_OPENAI_* environment variables
(see .env): endpoint, api key, deployment name, and api version. The `model`
config value is ignored for Azure -- the deployment name is what routes.
Switch providers by editing config.json (ai_provider / model / *_api_key_env)
or by setting LLM_PROVIDER in the environment.
"""

import os

from .azure_identity import auth_mode, default_credential


def get_llm(state: dict, structured_schema=None):
    """Return a LangChain chat model. If structured_schema is given, the model is
    wrapped with .with_structured_output so it returns a validated pydantic object."""
    provider = (state.get("ai_provider") or "azure_openai").lower()
    model = state.get("model") or "claude-sonnet-5"
    max_tokens = int(state.get("max_tokens", 4096))

    if provider in ("azure_openai", "azure"):
        from langchain_openai import AzureChatOpenAI

        key_env = state.get("config", {}).get("azure_openai_api_key_env", "AZURE_OPENAI_API_KEY")
        api_key = os.environ.get(key_env)
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or model
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

        configured_auth = state.get("config", {}).get("azure_openai_auth_mode", "auto")
        mode = auth_mode(
            "AZURE_OPENAI_AUTH_MODE",
            configured_auth,
            local_default="api_key",
        )
        if mode == "api_key" and not api_key:
            raise RuntimeError(
                f"Azure OpenAI API-key auth selected but {key_env} is not set."
            )
        if mode not in {"api_key", "managed_identity"}:
            raise RuntimeError(
                f"Unsupported AZURE_OPENAI_AUTH_MODE={mode!r}; "
                "use auto, api_key, or managed_identity"
            )

        missing = [
            name for name, val in (
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
        auth_kwargs = {"api_key": api_key}
        if mode == "managed_identity":
            from azure.identity import get_bearer_token_provider

            auth_kwargs = {
                "azure_ad_token_provider": get_bearer_token_provider(
                    default_credential(),
                    "https://cognitiveservices.azure.com/.default",
                )
            }

        llm = AzureChatOpenAI(
            azure_deployment=deployment,
            azure_endpoint=endpoint,
            api_version=api_version,
            max_tokens=max_tokens,
            timeout=120,
            max_retries=int(state.get("config", {}).get("llm_max_retries", 6)),
            **auth_kwargs,
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        key_env = state.get("config", {}).get("anthropic_api_key_env", "ANTHROPIC_API_KEY")
        if not os.environ.get(key_env):
            raise RuntimeError(
                f"Anthropic provider selected but {key_env} is not set in the environment."
            )
        llm = ChatAnthropic(model=model, max_tokens=max_tokens, timeout=120)

    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        key_env = state.get("config", {}).get("openai_api_key_env", "OPENAI_API_KEY")
        if not os.environ.get(key_env):
            raise RuntimeError(
                f"OpenAI provider selected but {key_env} is not set in the environment."
            )
        llm = ChatOpenAI(model=model, max_tokens=max_tokens, timeout=120)

    else:
        raise ValueError(f"Unknown ai_provider: {provider!r}")

    if structured_schema is not None:
        return llm.with_structured_output(structured_schema)
    return llm
