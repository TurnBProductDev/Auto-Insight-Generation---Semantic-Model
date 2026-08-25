"""Read-only semantic probe for an Ageing model.

Usage: python scripts/probe_ageing_semantics.py --config config/sbmart-ageing/config.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools import powerbi_executor as pbi  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    path = Path(args.config)
    if not path.is_absolute():
        path = ROOT / path
    cfg = json.loads(path.read_text(encoding="utf-8"))
    token = pbi.get_powerbi_token(cfg["tenant_id"])
    query = """EVALUATE
ROW(
  "STOCK VALUE", [STOCK VALUE],
  "age stock share", [age stock share],
  "aged stock share", [aged stock share],
  "raw VALUE", SUM('REP_SSR_SAG'[VALUE]),
  "agingstock", SUM('REP_SSR_SAG'[agingstock]),
  "closing", SUM('REP_SSR_SAG'[CLOSING_STOCK]),
  "qty", SUM('REP_SSR_SAG'[QTY])
)"""
    ok, body = pbi.run_dax(cfg["workspace_id"], cfg["dataset_id"], query, token)
    print(json.dumps({"ok": ok, "rows": pbi.extract_rows(body) if ok else body},
                     indent=2, default=str))
    fabric = pbi.get_fabric_token(False, cfg["tenant_id"])
    definitions, error = pbi.fetch_measure_definitions_tmsl(
        cfg["workspace_id"], cfg["dataset_id"], token=fabric,
        tenant_id=cfg["tenant_id"])
    wanted = {"stock value", "age stock share", "aged stock share",
              "stock_above_12", "stock_above_24"}
    print(json.dumps({
        "definition_error": error,
        "measures": {name: value for name, value in definitions.items()
                     if name.lower() in wanted},
    }, indent=2, default=str))
    ok_meta, meta_body = pbi.run_dax(
        cfg["workspace_id"], cfg["dataset_id"], "EVALUATE INFO.VIEW.COLUMNS()", token)
    if ok_meta:
        rows = pbi.extract_rows(meta_body)
        fact = [row for row in rows if str(row.get("[Table]") or row.get("Table") or "")
                == "REP_SSR_SAG"]
        print(json.dumps({"fact_columns": fact}, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
