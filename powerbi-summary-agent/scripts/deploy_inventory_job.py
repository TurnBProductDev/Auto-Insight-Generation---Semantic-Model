"""Create (or update) the Inventory Management scheduled job.

    python scripts/deploy_inventory_job.py --preview   # render the ARM body, make no call
    python scripts/deploy_inventory_job.py             # create or update the job

Every other SB Mart report has a Container Apps job; Inventory Management did
not, so its cards only reached the client feed when someone ran it by hand.

The spec mirrors ``insightgen-sbmart-ageing-daily`` - same environment, image,
managed identity and registry - and differs in exactly the three things that
make it a different report: ``AGENT_RUNNER``, ``AGENT_REPORT_ID``, and its own
config secrets. The cron follows sku (07:30) at 08:00 so the inventory scan
does not contend with another report's REST budget.

Deliberately goes through ``services.deploy`` rather than ``az containerapp job
create``: a 43 KB rulebook base64s past the 32,767-character command line, and
an ARM PATCH replaces the whole secret array, so unrelated secrets have to be
carried forward by name. Both are already handled there.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a runner dependency
    load_dotenv = None
else:
    load_dotenv(PROJECT_ROOT / ".env")

from src.services import deploy  # noqa: E402

SUBSCRIPTION = "0300da4d-3a63-4241-a129-42b4f8b0c5cc"
RESOURCE_GROUP = "Summary_generator_PBI"
#: ARM caps a ContainerAppsJob name at 32 characters, and
#: `insightgen-sbmart-inventory-daily` is 33 - the create fails with
#: ContainerAppInvalidName. `stock` also matches the report's own module name
#: (`stock_health`) rather than abbreviating "inventory" to nothing readable.
JOB_NAME = "insightgen-sbmart-stock-daily"
CONFIG_DIR = PROJECT_ROOT / "config" / "inventory"

#: The only writable path in the image.
CONTAINER_OUTPUT_FOLDER = "outputs"

#: Read from insightgen-sbmart-ageing-daily on 2026-08-27.
ENVIRONMENT_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"
    "/providers/Microsoft.App/managedEnvironments/insightgen-container-env"
)
IDENTITY_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourcegroups/{RESOURCE_GROUP}"
    "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/insightgen-mi"
)
IMAGE = "insightgenacr.azurecr.io/insightgen-agent:20260825-daily-sales-bands"

#: AGENT_OUTPUT_FOLDER overrides the config's `outputs_inventory`: inside the
#: container the entry point materialises the runtime config under `outputs`,
#: and `services.validate` refuses any other value for a container deploy.
ENV = {
    "AGENT_OUTPUT_FOLDER": "outputs",
    "AGENT_RUNNER": "inventory",
    "AGENT_REPORT_ID": "inventory_stock_health",
    "AI_CONTENT_PUBLISH_ENABLED": "true",
    "AZURE_BLOB_UPLOAD": "true",
    "AZURE_CLIENT_ID": "8eeb4a99-90f5-4793-af93-0c955e2e861e",
    "AZURE_MANAGED_IDENTITY_CLIENT_ID": "8eeb4a99-90f5-4793-af93-0c955e2e861e",
    "AZURE_OPENAI_API_VERSION": "2025-04-01-preview",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-5.4",
    "AZURE_OPENAI_ENDPOINT": "https://test-agentpbi-resource.cognitiveservices.azure.com",
    "INSIGHT_MEMORY_STORAGE": "azure_blob",
    "LLM_PROVIDER": "azure_openai",
    "POWERBI_AUTH_MODE": "managed_identity",
    "POWERBI_QUERY_API": "auto",
    "SUMMARY_MEMORY_STORAGE": "azure_blob",
    "POWERBI_TENANT_ID": "315642c5-e14a-4c12-bf77-41ee070def79",
}


def _spec(cron: str) -> "deploy.JobSpec":
    return deploy.JobSpec(
        subscription_id=SUBSCRIPTION,
        resource_group=RESOURCE_GROUP,
        job_name=JOB_NAME,
        environment_id=ENVIRONMENT_ID,
        location="East US 2",
        image=IMAGE,
        cron=cron,
        cpu=1.0,
        memory="2Gi",
        replica_timeout=3600,
        replica_retry_limit=1,
        identity_resource_id=IDENTITY_ID,
        registry_server="insightgenacr.azurecr.io",
        registry_identity=IDENTITY_ID,
        env=ENV,
        secret_env={"AZURE_OPENAI_API_KEY": "azure-openai-api-key"},
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true",
                    help="render the ARM body with secrets redacted; make no call")
    ap.add_argument("--cron", default="0 8 * * *",
                    help="UTC cron; default follows sku (07:30) at 08:00")
    args = ap.parse_args(argv)

    config_json = (CONFIG_DIR / "config.json").read_text(encoding="utf-8")
    summary_rules = (CONFIG_DIR / "summary_business_rules.md").read_text(encoding="utf-8")

    # In the container only /app/outputs is writable, and `services.validate`
    # refuses any other `output_folder` for a container deploy. The committed
    # config keeps `outputs_inventory` because that is right for a local run,
    # so the value is rewritten for the shipped copy only - the file on disk is
    # untouched. Belt and braces: the runner now also honours
    # AGENT_OUTPUT_FOLDER, but an image built before that fix reads the config
    # alone, which is how the first execution died on PermissionError.
    config = json.loads(config_json)
    if config.get("output_folder") != CONTAINER_OUTPUT_FOLDER:
        config["output_folder"] = CONTAINER_OUTPUT_FOLDER
        config_json = json.dumps(config, indent=2) + "\n"
    # Inventory ships one rulebook; there is no separate business_rules.md, and
    # an empty string is what `file_io.read_business_rules` already tolerates.
    business_rules = ""

    # A NEW job has no secrets to carry forward, so the `azure-openai-api-key`
    # that `secret_env` references must be supplied here or the secretRef would
    # dangle and the container would start with an empty key. ARM never returns
    # an existing secret's value, so it cannot be copied off another job; it is
    # read from the environment instead and never written to this file.
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    if not api_key and not args.preview:
        print("AZURE_OPENAI_API_KEY is not set. Load powerbi-summary-agent/.env "
              "(or export the key) before deploying: the new job has no secret "
              "to inherit and would run with an empty key.", file=sys.stderr)
        return 2
    spec = _spec(args.cron)
    spec.secrets["azure-openai-api-key"] = api_key

    if args.preview:
        secrets = deploy.secret_payload(config_json, business_rules, summary_rules)
        secrets["azure-openai-api-key"] = api_key
        body = deploy.build_job_body(
            spec, [{"name": name, "value": value} for name, value in secrets.items()])
        print(json.dumps(deploy.redact(body), indent=2))
        print(f"\nPREVIEW ONLY - no call made."
              f" Would create/update {JOB_NAME} at cron {args.cron!r}.")
        return 0

    result = deploy.deploy(
        spec,
        config_json=config_json,
        business_rules=business_rules,
        summary_business_rules=summary_rules,
        on_log=print,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
