"""Container entry point for runtime-injected agent configuration.

Azure Container Apps secrets expose the real config and business rules as
base64 environment variables.  Materialize them only on the container's
ephemeral filesystem, then run the normal application entry point.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from .main import main as agent_main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _decode_env(name: str) -> bytes | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise SystemExit(f"{name} is not valid base64: {exc}") from exc


def main() -> int:
    config_bytes = _decode_env("AGENT_CONFIG_B64")
    rules_bytes = _decode_env("AGENT_RULES_B64")
    summary_rules_bytes = _decode_env("AGENT_SUMMARY_RULES_B64")

    if not config_bytes and not rules_bytes and not summary_rules_bytes:
        return agent_main()
    if not config_bytes:
        raise SystemExit(
            "AGENT_RULES_B64 / AGENT_SUMMARY_RULES_B64 require AGENT_CONFIG_B64."
        )

    runtime_dir = PROJECT_ROOT / "outputs" / "runtime-config"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / "config.json"
    config_path.write_bytes(config_bytes)

    rules_path = runtime_dir / "business_rules.md"
    if rules_bytes is not None:
        rules_path.write_bytes(rules_bytes)
    else:
        rules_path.unlink(missing_ok=True)

    # The summary branch reads its own rulebook as a sibling of the active
    # config.  Without this the file simply never exists in the container and
    # summary_business_rules_block() silently degrades to "".
    summary_rules_path = runtime_dir / "summary_business_rules.md"
    if summary_rules_bytes is not None:
        summary_rules_path.write_bytes(summary_rules_bytes)
    else:
        summary_rules_path.unlink(missing_ok=True)

    # AGENT_REPORT_ID names which report this job produces (WP1). Passed
    # explicitly rather than left to main's env-var default, so the container
    # path keeps working if that default is ever changed. Absent means "the
    # report named in the config", which is every pre-WP1 job.
    report_id = os.environ.get("AGENT_REPORT_ID")
    if report_id == "target_tracker":
        # Target Tracker deliberately has its own deterministic scan/model/render
        # path rather than the YoY LangGraph. Cloud jobs still share this image
        # and runtime-injected configuration contract.
        from scripts.run_target_tracker import main as target_tracker_main

        return target_tracker_main(["--config", str(config_path), "--publish"])

    argv = ["--config", str(config_path)]
    if report_id:
        argv += ["--report", report_id]
    return agent_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
