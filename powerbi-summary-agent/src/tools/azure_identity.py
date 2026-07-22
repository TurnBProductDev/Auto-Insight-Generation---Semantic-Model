"""Shared Azure identity helpers for local development and Container Apps Jobs."""

from __future__ import annotations

import os
from functools import lru_cache


def is_azure_runtime() -> bool:
    """True when Azure injected managed-identity or Container Apps metadata."""
    return bool(
        os.environ.get("IDENTITY_ENDPOINT")
        or os.environ.get("CONTAINER_APP_JOB_NAME")
        or os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME")
    )


def auth_mode(
    env_name: str,
    config_value: str | None = None,
    *,
    local_default: str,
) -> str:
    """Resolve ``auto`` to managed identity in Azure and a local-safe fallback."""
    mode = str(os.environ.get(env_name) or config_value or "auto").strip().lower()
    aliases = {
        "mi": "managed_identity",
        "managed-identity": "managed_identity",
        "aad": "managed_identity",
        "entra": "managed_identity",
        "local": local_default,
    }
    mode = aliases.get(mode, mode)
    if mode == "auto":
        return "managed_identity" if is_azure_runtime() else local_default
    return mode


def managed_identity_client_id() -> str | None:
    """Return the optional user-assigned identity client id.

    ``AZURE_MANAGED_IDENTITY_CLIENT_ID`` is explicit and preferred. Azure SDKs
    also conventionally use ``AZURE_CLIENT_ID``; accept it only in an Azure
    runtime so a developer's service-principal environment is not misclassified.
    """
    explicit = os.environ.get("AZURE_MANAGED_IDENTITY_CLIENT_ID")
    if explicit:
        return explicit
    if is_azure_runtime():
        return os.environ.get("AZURE_CLIENT_ID")
    return None


@lru_cache(maxsize=1)
def default_credential():
    """One process-wide non-interactive Azure credential chain."""
    from azure.identity import DefaultAzureCredential

    client_id = managed_identity_client_id()
    kwargs = {
        "exclude_interactive_browser_credential": True,
    }
    if client_id:
        kwargs["managed_identity_client_id"] = client_id
    return DefaultAzureCredential(**kwargs)


def access_token(scope: str) -> str:
    return default_credential().get_token(scope).token
