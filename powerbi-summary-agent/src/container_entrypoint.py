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

    if not config_bytes and not rules_bytes:
        return agent_main()
    if not config_bytes:
        raise SystemExit("AGENT_RULES_B64 requires AGENT_CONFIG_B64.")

    runtime_dir = PROJECT_ROOT / "outputs" / "runtime-config"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / "config.json"
    config_path.write_bytes(config_bytes)

    rules_path = runtime_dir / "business_rules.md"
    if rules_bytes is not None:
        rules_path.write_bytes(rules_bytes)
    else:
        rules_path.unlink(missing_ok=True)

    return agent_main(["--config", str(config_path)])


if __name__ == "__main__":
    raise SystemExit(main())
