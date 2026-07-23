"""Offline contract checks for the Power BI Arrow compatibility layer.

Run from the project directory:

    python scripts/replay_powerbi_arrow.py

No Azure, Power BI, LLM, or network access is required.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import sys
from decimal import Decimal
from pathlib import Path

import pyarrow as pa

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import powerbi_executor as pbi


def _stream(rows: list[dict], metadata: dict[bytes, bytes] | None = None) -> bytes:
    table = pa.Table.from_pylist(rows)
    if metadata:
        table = table.replace_schema_metadata(metadata)
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue()


def _without_rls_env():
    saved = {
        name: os.environ.pop(name, None)
        for name in ("POWERBI_EFFECTIVE_USERNAME", "POWERBI_RLS_ROLES")
    }
    return saved


def _restore_env(saved: dict):
    for name, value in saved.items():
        if value is not None:
            os.environ[name] = value


def main() -> None:
    payload = pbi._decode_arrow_payload(
        _stream([
            {
                "'Sales'[Store]": "CFH014",
                "[Revenue]": Decimal("123.45"),
                "[As Of]": dt.date(2026, 7, 23),
            }
        ])
    )
    rows = pbi.extract_rows(payload)
    assert rows == [{
        "'Sales'[Store]": "CFH014",
        "[Revenue]": 123.45,
        "[As Of]": "2026-07-23",
    }]

    two_tables = pbi._decode_arrow_payload(
        _stream([{"[First]": 1}]) + _stream([{"[Second]": 2}])
    )
    assert len(two_tables["results"][0]["tables"]) == 2

    try:
        pbi._decode_arrow_payload(_stream(
            [{"ErrorCode": "ModelError", "ErrorMessage": "bad DAX"}],
            {b"IsError": b"true", b"FaultCode": b"0xDEMO", b"FaultString": b"bad DAX"},
        ))
    except pbi.ArrowQueryError as exc:
        assert "0xDEMO" in str(exc) and "bad DAX" in str(exc)
    else:
        raise AssertionError("Arrow error rowset was not rejected")

    saved = _without_rls_env()
    try:
        body = pbi._arrow_request_body("EVALUATE ROW(\"Status\", \"OK\")")
        assert "effectiveUsername" not in body
        assert "roles" not in body

        os.environ["POWERBI_EFFECTIVE_USERNAME"] = "regional.user@example.com"
        os.environ["POWERBI_RLS_ROLES"] = '["RegionalSales", "RegionalSales"]'
        body = pbi._arrow_request_body("EVALUATE ROW(\"Status\", \"OK\")")
        assert body["effectiveUsername"] == "regional.user@example.com"
        assert body["roles"] == ["RegionalSales"]
    finally:
        os.environ.pop("POWERBI_EFFECTIVE_USERNAME", None)
        os.environ.pop("POWERBI_RLS_ROLES", None)
        _restore_env(saved)

    saved_modes = {
        name: os.environ.get(name)
        for name in ("POWERBI_QUERY_API", "POWERBI_AUTH_MODE")
    }
    try:
        os.environ["POWERBI_QUERY_API"] = "auto"
        os.environ["POWERBI_AUTH_MODE"] = "interactive"
        assert pbi._resolve_query_api() == "json"
        os.environ["POWERBI_AUTH_MODE"] = "managed_identity"
        assert pbi._resolve_query_api() == "arrow"
        os.environ["POWERBI_QUERY_API"] = "json"
        assert pbi._resolve_query_api() == "json"
    finally:
        for name, value in saved_modes.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    print("Power BI Arrow replay checks passed.")


if __name__ == "__main__":
    main()
