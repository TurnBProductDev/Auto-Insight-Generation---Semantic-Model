"""Small live smoke test for Power BI's executeDaxQueries Arrow endpoint.

It prints only query names and row counts; no model rows or tokens are logged.
The normal local interactive token cache is used unless POWERBI_AUTH_MODE is
explicitly set by the caller.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import powerbi_executor as pbi  # noqa: E402


QUERIES = {
    "basic": 'EVALUATE ROW("Status", "OK")',
    "tables": "EVALUATE INFO.VIEW.TABLES()",
    "columns": "EVALUATE INFO.VIEW.COLUMNS()",
    "measures": "EVALUATE INFO.VIEW.MEASURES()",
    "relationships": "EVALUATE INFO.VIEW.RELATIONSHIPS()",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.json")
    parser.add_argument("--api", choices=("arrow", "json"), default="arrow")
    parser.add_argument("--show-token-claims", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    # Explicit selection makes the script useful for a same-token comparison.
    os.environ["POWERBI_QUERY_API"] = args.api
    os.environ.pop("POWERBI_EFFECTIVE_USERNAME", None)
    os.environ.pop("POWERBI_RLS_ROLES", None)
    if cfg.get("tenant_id"):
        os.environ.setdefault("POWERBI_TENANT_ID", str(cfg["tenant_id"]))

    token = pbi.get_powerbi_token(tenant_id=cfg.get("tenant_id"))
    if args.show_token_claims:
        encoded = token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded))
        safe_claims = {
            key: claims.get(key) for key in ("aud", "appid", "scp", "roles")
        }
        print(f"token claims: {json.dumps(safe_claims, sort_keys=True)}")
    for name, dax in QUERIES.items():
        ok, payload = pbi.run_dax(
            cfg["workspace_id"], cfg["dataset_id"], dax, token=token
        )
        if not ok:
            raise SystemExit(f"{name}: FAILED: {payload}")
        print(f"{name}: OK ({len(pbi.extract_rows(payload))} rows)")

    print(
        f"Live Power BI {args.api} smoke test passed; "
        "RLS impersonation was disabled."
    )


if __name__ == "__main__":
    main()
