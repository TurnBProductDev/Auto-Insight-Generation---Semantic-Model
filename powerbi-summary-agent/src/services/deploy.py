"""Deploying a client as an Azure Container Apps Job.

Deployment is three files becoming three job secrets, plus a job that mounts
them as base64 environment variables:

    AGENT_CONFIG_B64        -> config.json                (secret agent-config-b64)
    AGENT_RULES_B64         -> business_rules.md          (secret agent-rules-b64)
    AGENT_SUMMARY_RULES_B64 -> summary_business_rules.md  (secret agent-summary-rules-b64)

``src/container_entrypoint.py`` materialises all three into
``/app/outputs/runtime-config/`` and runs the agent against them, so the
rulebooks arrive as siblings of the config exactly as ``file_io`` expects.

Two details that break the obvious implementation:

* **The secrets exceed the command line.** A 45 KB rulebook base64s to ~61 KB,
  past the 32,767-character Windows limit, so ``az containerapp job secret set``
  fails. This module talks to ARM over HTTPS with the payload in the request
  body, where no such limit exists.
* **A naive PATCH drops secrets.** ARM replaces the whole secret array, and a
  secret's value is never returned by a GET - only its name. So an upsert must
  read the existing names, carry forward the ones it does not own, and write the
  union. :func:`merge_secrets` is pure, and it is the part worth testing.

Nothing here logs or echoes a secret value.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
API_VERSION = "2024-03-01"

CONFIG_SECRET = "agent-config-b64"
RULES_SECRET = "agent-rules-b64"
SUMMARY_RULES_SECRET = "agent-summary-rules-b64"

#: Secrets this tool owns. Anything else on the job is carried forward untouched.
OWNED_SECRETS = (CONFIG_SECRET, RULES_SECRET, SUMMARY_RULES_SECRET)

LogSink = Callable[[str], None]


class DeployError(RuntimeError):
    """An ARM call failed, or the request would have been unsafe to send."""


@dataclass
class JobSpec:
    """Everything about the deployment that is not in ``config.json``."""

    subscription_id: str
    resource_group: str
    job_name: str
    environment_id: str = ""
    location: str = ""
    image: str = ""
    cron: str = "30 3 * * *"
    cpu: float = 1.0
    memory: str = "2Gi"
    replica_timeout: int = 3600
    replica_retry_limit: int = 1
    identity_resource_id: str = ""
    registry_server: str = ""
    registry_identity: str = ""
    #: Plain environment variables (never secrets).
    env: dict = field(default_factory=dict)
    #: name -> value for additional secrets, e.g. the Azure OpenAI key.
    secrets: dict = field(default_factory=dict)
    #: env var name -> secret name, for secret-backed environment variables.
    secret_env: dict = field(default_factory=dict)

    @property
    def resource_id(self) -> str:
        return (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.App/jobs/{self.job_name}"
        )

    @property
    def url(self) -> str:
        return f"{ARM}{self.resource_id}?api-version={API_VERSION}"


# ---------------------------------------------------------------------------
# Pure payload construction - the part that must be right
# ---------------------------------------------------------------------------


def encode(text: str) -> str:
    """base64 exactly the bytes the container entry point will decode."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def secret_payload(config_json: str, business_rules: str, summary_rules: str) -> dict:
    """The three agent secrets, base64-encoded."""
    return {
        CONFIG_SECRET: encode(config_json),
        RULES_SECRET: encode(business_rules),
        SUMMARY_RULES_SECRET: encode(summary_rules),
    }


def merge_secrets(existing: Iterable[dict], updates: dict) -> tuple[list[dict], list[str]]:
    """Union of the job's current secrets and ours, preserving the rest.

    ARM never returns a secret's value, only its name (or a Key Vault
    reference). Sending back a name with no value tells ARM to keep the stored
    value, which is how an unrelated secret survives an update. Dropping the
    name is how it gets deleted - so this function exists to make that mistake
    impossible to make by accident.

    Returns the array to send, and the names that were carried forward.
    """
    out: list[dict] = []
    carried: list[str] = []
    seen: set[str] = set()
    for secret in existing or []:
        name = str(secret.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        if name in updates:
            continue  # replaced below
        if secret.get("keyVaultUrl"):
            entry = {"name": name, "keyVaultUrl": secret["keyVaultUrl"]}
            if secret.get("identity"):
                entry["identity"] = secret["identity"]
            out.append(entry)
        else:
            # Name only: ARM keeps the stored value untouched.
            out.append({"name": name})
        carried.append(name)
    for name, value in updates.items():
        out.append({"name": name, "value": value})
    return out, carried


def build_job_body(spec: JobSpec, secrets: list[dict], *, existing: dict | None = None) -> dict:
    """The ARM body for a create-or-update of the scheduled job."""
    template_env = [{"name": name, "value": str(value)} for name, value in sorted(spec.env.items())]
    # These three mappings are part of the deployment contract, not optional
    # caller configuration. Without them the secrets exist on the job but the
    # container cannot see or materialise its config and rulebooks.
    secret_env = {
        "AGENT_CONFIG_B64": CONFIG_SECRET,
        "AGENT_RULES_B64": RULES_SECRET,
        "AGENT_SUMMARY_RULES_B64": SUMMARY_RULES_SECRET,
        **spec.secret_env,
    }
    template_env += [
        {"name": name, "secretRef": secret} for name, secret in sorted(secret_env.items())
    ]

    existing_props = (existing or {}).get("properties") or {}
    environment_id = spec.environment_id or existing_props.get("environmentId") or ""
    if not environment_id:
        raise DeployError(
            "No Container Apps environment id: pass environment_id, or target an existing job."
        )
    existing_template = (existing_props.get("template") or {}).get("containers") or []
    image = spec.image or (existing_template[0].get("image") if existing_template else "")
    if not image:
        raise DeployError("No container image: pass image, or target an existing job.")

    body: dict[str, Any] = {
        "location": spec.location or (existing or {}).get("location") or "",
        "properties": {
            "environmentId": environment_id,
            "configuration": {
                "triggerType": "Schedule",
                "replicaTimeout": int(spec.replica_timeout),
                "replicaRetryLimit": int(spec.replica_retry_limit),
                "scheduleTriggerConfig": {
                    "cronExpression": spec.cron,
                    "parallelism": 1,
                    "replicaCompletionCount": 1,
                },
                "secrets": secrets,
            },
            "template": {
                "containers": [
                    {
                        "name": spec.job_name,
                        "image": image,
                        "resources": {"cpu": float(spec.cpu), "memory": spec.memory},
                        "env": template_env,
                    }
                ]
            },
        },
    }
    if not body["location"]:
        raise DeployError("No location: pass location, or target an existing job.")

    if spec.registry_server:
        body["properties"]["configuration"]["registries"] = [
            {"server": spec.registry_server, "identity": spec.registry_identity or "system"}
        ]
    elif existing_props.get("configuration", {}).get("registries"):
        body["properties"]["configuration"]["registries"] = existing_props["configuration"]["registries"]

    if spec.identity_resource_id:
        body["identity"] = {
            "type": "UserAssigned",
            "userAssignedIdentities": {spec.identity_resource_id: {}},
        }
    elif (existing or {}).get("identity"):
        body["identity"] = existing["identity"]

    return body


def redact(body: dict) -> dict:
    """A copy safe to log or show: secret values replaced by their length."""
    clone = json.loads(json.dumps(body))
    secrets = ((clone.get("properties") or {}).get("configuration") or {}).get("secrets")
    for secret in secrets or []:
        if "value" in secret:
            secret["value"] = f"<{len(secret['value'])} chars redacted>"
    return clone


# ---------------------------------------------------------------------------
# ARM transport
# ---------------------------------------------------------------------------


def _token(credential=None) -> str:
    if credential is None:
        from ..tools.azure_identity import default_credential

        credential = default_credential()
    return credential.get_token(ARM_SCOPE).token


class ArmClient:
    """A very small ARM client: bearer token in, JSON out, no secret logging."""

    def __init__(self, credential=None, *, session=None, on_log: LogSink | None = None) -> None:
        self._credential = credential
        self._session = session
        self._log = on_log or (lambda _line: None)

    @property
    def session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def request(self, method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        headers = {
            "Authorization": f"Bearer {_token(self._credential)}",
            "Content-Type": "application/json",
        }
        # The payload rides in the request body, so the 32,767-character command
        # line limit that breaks `az containerapp job secret set` never applies.
        data = json.dumps(body).encode("utf-8") if body is not None else None
        response = self.session.request(method, url, headers=headers, data=data, timeout=120)
        try:
            parsed = response.json() if response.content else {}
        except ValueError:
            parsed = {"raw": response.text[:2000]}
        return response.status_code, parsed


def get_job(spec: JobSpec, client: ArmClient) -> dict | None:
    status, body = client.request("GET", spec.url)
    if status == 404:
        return None
    if status >= 400:
        raise DeployError(f"GET job failed ({status}): {json.dumps(body)[:500]}")
    return body


def list_container_names(subscription_id: str, account: str, client: ArmClient) -> list[str]:
    """Blob containers on a storage account, for the ai_content_client pre-check.

    Uses ARM rather than the data plane so the same credential works, and a
    failure returns an empty list - the caller treats "unknown" and "missing"
    differently.
    """
    url = (
        f"{ARM}/subscriptions/{subscription_id}/providers/Microsoft.Storage/storageAccounts"
        f"?api-version=2023-05-01"
    )
    status, body = client.request("GET", url)
    if status >= 400:
        return []
    target = next(
        (item for item in body.get("value") or [] if str(item.get("name")) == account), None
    )
    if not target:
        return []
    status, body = client.request(
        "GET", f"{ARM}{target['id']}/blobServices/default/containers?api-version=2023-05-01"
    )
    if status >= 400:
        return []
    return [str(item.get("name")) for item in body.get("value") or [] if item.get("name")]


@dataclass
class DeployResult:
    status: str = "pending"  # ok | failed
    created: bool = False
    reason: str = ""
    job_id: str = ""
    provisioning_state: str = ""
    carried_secrets: list = field(default_factory=list)
    written_secrets: list = field(default_factory=list)
    logs: list = field(default_factory=list)

    def json(self) -> dict:
        return {
            "status": self.status,
            "created": self.created,
            "reason": self.reason,
            "jobId": self.job_id,
            "provisioningState": self.provisioning_state,
            "carriedSecrets": self.carried_secrets,
            "writtenSecrets": self.written_secrets,
            "logs": self.logs,
        }


def deploy(
    spec: JobSpec,
    *,
    config_json: str,
    business_rules: str,
    summary_business_rules: str,
    client: ArmClient | None = None,
    on_log: LogSink | None = None,
    poll_seconds: int = 120,
    allowed_job_names: Iterable[str] | None = None,
) -> DeployResult:
    """Create or update the scheduled job, carrying forward unrelated secrets."""
    result = DeployResult()

    def log(line: str) -> None:
        result.logs.append(line)
        if on_log:
            on_log(line)

    if allowed_job_names is not None and spec.job_name not in set(allowed_job_names):
        result.status = "failed"
        result.reason = f"Job name {spec.job_name!r} is not on the server-side allow-list."
        return result

    client = client or ArmClient(on_log=on_log)
    try:
        log(f"Reading {spec.job_name}...")
        existing = get_job(spec, client)
        result.created = existing is None
        log("Job does not exist yet; it will be created." if result.created else "Job exists; updating.")

        updates = secret_payload(config_json, business_rules, summary_business_rules)
        current = ((existing or {}).get("properties") or {}).get("configuration", {}).get("secrets") or []
        secrets, carried = merge_secrets(current, {**updates, **spec.secrets})
        result.carried_secrets = carried
        result.written_secrets = sorted({*updates, *spec.secrets})
        log(f"Writing {len(result.written_secrets)} secret(s); carrying forward {len(carried)}: "
            f"{', '.join(carried) or 'none'}")

        body = build_job_body(spec, secrets, existing=existing)
        status, response = client.request("PUT", spec.url, body)
        if status >= 400:
            raise DeployError(f"PUT job failed ({status}): {json.dumps(response)[:500]}")
        result.job_id = str(response.get("id") or spec.resource_id)
        state = str((response.get("properties") or {}).get("provisioningState") or "")
        log(f"Submitted; provisioningState={state or 'unknown'}")

        deadline = time.monotonic() + poll_seconds
        while state in {"", "InProgress", "Waiting", "Updating", "Creating"} and time.monotonic() < deadline:
            time.sleep(3)
            _, response = client.request("GET", spec.url)
            state = str((response.get("properties") or {}).get("provisioningState") or state)
        result.provisioning_state = state
        if state and state.lower() not in {"succeeded", "ready"}:
            result.status = "failed"
            result.reason = f"Job provisioning ended in state {state!r}."
        else:
            result.status = "ok"
            log(f"{'Created' if result.created else 'Updated'} {spec.job_name} ({state or 'submitted'}).")
    except Exception as exc:  # noqa: BLE001 - a deploy failure is a reported result
        result.status = "failed"
        result.reason = f"{type(exc).__name__}: {exc}"
        log(f"Deploy failed: {result.reason}")
    return result


def start_job(spec: JobSpec, client: ArmClient | None = None) -> dict:
    """Trigger one execution now - the 'Run now' button."""
    client = client or ArmClient()
    status, body = client.request(
        "POST", f"{ARM}{spec.resource_id}/start?api-version={API_VERSION}", {}
    )
    if status >= 400:
        raise DeployError(f"Starting the job failed ({status}): {json.dumps(body)[:500]}")
    return {
        "status": "started",
        "executionName": (body.get("name") or (body.get("properties") or {}).get("name") or ""),
        "id": body.get("id") or "",
    }


def list_executions(spec: JobSpec, client: ArmClient | None = None, *, limit: int = 10) -> list[dict]:
    client = client or ArmClient()
    status, body = client.request(
        "GET", f"{ARM}{spec.resource_id}/executions?api-version={API_VERSION}"
    )
    if status >= 400:
        raise DeployError(f"Listing executions failed ({status}): {json.dumps(body)[:500]}")
    out = []
    for item in (body.get("value") or [])[:limit]:
        properties = item.get("properties") or {}
        out.append(
            {
                "name": item.get("name"),
                "status": properties.get("status"),
                "startTime": properties.get("startTime"),
                "endTime": properties.get("endTime"),
            }
        )
    return out
