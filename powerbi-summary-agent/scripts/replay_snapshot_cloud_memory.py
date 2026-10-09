"""Offline replay for Azure Blob-backed snapshot-memory lifecycle
(Ageing/SKU Overview/Daily Sales's cross-run memory - `snapshot_memory.py`).

This is the fix for a real gap found while provisioning Daily Sales'
scheduled job: a Container Apps Job gets a fresh, empty filesystem every
run, and `snapshot_memory.py` only ever read/wrote a local file, so
"already reported" would never actually have persisted in production - it
would have quietly reset to empty every single run. `hydrate_snapshot_memory`
/`publish_snapshot_memory` in `src/tools/azure_blob.py` close that gap the
same way `hydrate_insight_memory`/`publish_insight_memory` already do for
the LangGraph pipeline's own memory (see `replay_cloud_memory.py`, whose
fake blob service this reuses the shape of).

The central property this proves: memory correctly persists across a
LOCAL-DISK WIPE between runs, as long as the blob survives - simulating
exactly what a scheduled job's two runs look like.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import snapshot_memory  # noqa: E402
from src.tools import azure_blob  # noqa: E402

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in str(detail).splitlines():
            print(f"         {line}")
    _failures.append(label)


class _Downloader:
    def __init__(self, data: bytes, etag: str):
        self._data = data
        self.properties = SimpleNamespace(etag=etag)

    def readall(self):
        return self._data


class _Blob:
    def __init__(self, service, container: str, name: str):
        self.service = service
        self.container = container
        self.name = name

    def download_blob(self):
        try:
            data, etag = self.service.data[self.container][self.name]
        except KeyError as exc:
            raise ResourceNotFoundError("missing") from exc
        return _Downloader(data, etag)

    def upload_blob(self, data, overwrite=False, etag=None, **_kwargs):
        self.service.data.setdefault(self.container, {})
        existing = self.service.data[self.container].get(self.name)
        if existing and not overwrite:
            raise ResourceExistsError("exists")
        if etag is not None and (not existing or existing[1] != etag):
            raise ResourceModifiedError("etag changed")
        raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        self.service.version += 1
        self.service.data[self.container][self.name] = (raw, f'"etag-{self.service.version}"')


class _Container:
    """Just enough of a container client for the scan archive's listing."""

    def __init__(self, service, container: str):
        self.service = service
        self.container = container

    def list_blobs(self, name_starts_with: str = ""):
        for name in sorted(self.service.data.get(self.container, {})):
            if name.startswith(name_starts_with):
                yield SimpleNamespace(name=name)

    def get_blob_client(self, name: str):
        return _Blob(self.service, self.container, name)


class _Service:
    def __init__(self):
        self.data: dict[str, dict[str, tuple[bytes, str]]] = {}
        self.version = 0

    def get_blob_client(self, container: str, blob: str):
        return _Blob(self, container, blob)

    def get_container_client(self, container: str):
        return _Container(self, container)


CFG = {
    "snapshot_memory_storage": "azure_blob",
    "azure_blob_account": "account",
    "azure_blob_memory_container": "insightstate",
    "azure_blob_snapshot_memory_prefix": "snapshot-memory",
}

REPORT_ID = "daily_sales"
DATASET_ID = "dataset-abc"

SIGNAL = {
    "candidate_id": "daily_sales_department_bills:CONSUMER GOODS:",
    "story_key": "irrelevant", "report_id": REPORT_ID,
    "analysis_type": "daily_sales_department_bills_band", "dimension": "department",
    "affected_segment": "CONSUMER GOODS", "impact_value": -19.0, "score": 19.0,
    "severity": "critical", "description": "CONSUMER GOODS finished Bills underperforming.",
}


def test_disabled_by_default() -> None:
    print("\n=== off unless snapshot_memory_storage is explicitly 'azure_blob' ===")
    off = azure_blob.hydrate_snapshot_memory({}, "/tmp/x", REPORT_ID, DATASET_ID)
    check("no config key at all -> skipped, never touches the network", off["status"] == "skipped")
    check("cloud_snapshot_memory_enabled is False by default",
          azure_blob.cloud_snapshot_memory_enabled({}) is False)
    check("cloud_snapshot_memory_enabled is True when explicitly set to azure_blob",
          azure_blob.cloud_snapshot_memory_enabled(CFG) is True)


def test_memory_survives_a_local_disk_wipe_between_runs() -> None:
    print("\n=== the central property: memory survives even when the local "
         "disk is wiped between runs, exactly like a scheduled job ===")
    service = _Service()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
        azure_blob, "_service_client", return_value=(service, "fake")
    ):
        out1 = Path(tmp) / "run1_outputs"

        # "Day 1": a fresh container, an empty blob.
        h1 = azure_blob.hydrate_snapshot_memory(CFG, out1, REPORT_ID, DATASET_ID)
        check("first-ever hydration finds no blob yet, reported as 'missing' not 'failed'",
              h1["status"] == "missing", h1)

        r1 = snapshot_memory.filter_signals(
            [SIGNAL], report_id=REPORT_ID, out_dir=out1, dataset_id=DATASET_ID,
            observed_at="2026-08-12")
        check("day 1: a brand-new finding is reportable", len(r1["reportable"]) == 1)
        snapshot_memory.commit(r1)

        p1 = azure_blob.publish_snapshot_memory(CFG, out1, REPORT_ID, DATASET_ID, h1)
        check("day 1: publish succeeds", p1["status"] == "ok", p1)

        # "Day 2": simulate the scheduled job's next run - a BRAND NEW
        # container, so a different, empty local directory. Nothing links
        # run 2 to run 1 except the blob.
        out2 = Path(tmp) / "run2_outputs_completely_different_directory"
        check("run 2's local directory does not exist yet (genuinely fresh)",
              not out2.exists())

        h2 = azure_blob.hydrate_snapshot_memory(CFG, out2, REPORT_ID, DATASET_ID)
        check("day 2: hydration finds day 1's blob", h2["status"] == "ok" and h2["etag"], h2)

        r2 = snapshot_memory.filter_signals(
            [SIGNAL], report_id=REPORT_ID, out_dir=out2, dataset_id=DATASET_ID,
            observed_at="2026-08-13")
        check("day 2: the SAME finding is suppressed, proving memory crossed the "
             "local-disk wipe via the blob - this is the fix",
              len(r2["reportable"]) == 0, r2)
        snapshot_memory.commit(r2)
        p2 = azure_blob.publish_snapshot_memory(CFG, out2, REPORT_ID, DATASET_ID, h2)
        check("day 2: publish succeeds", p2["status"] == "ok", p2)


def test_etag_conflict_is_refused_not_clobbered() -> None:
    print("\n=== a concurrent writer's change is never silently overwritten ===")
    service = _Service()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
        azure_blob, "_service_client", return_value=(service, "fake")
    ):
        out = Path(tmp) / "outputs"
        h = azure_blob.hydrate_snapshot_memory(CFG, out, REPORT_ID, DATASET_ID)
        r = snapshot_memory.filter_signals(
            [SIGNAL], report_id=REPORT_ID, out_dir=out, dataset_id=DATASET_ID,
            observed_at="2026-08-12")
        snapshot_memory.commit(r)
        first = azure_blob.publish_snapshot_memory(CFG, out, REPORT_ID, DATASET_ID, h)
        check("first publish (no blob yet) succeeds", first["status"] == "ok")

        # A second run hydrates the same starting point...
        stale_hydration = azure_blob.hydrate_snapshot_memory(CFG, out, REPORT_ID, DATASET_ID)
        # ...but a third party changes the blob in between.
        account, container, name = azure_blob._snapshot_memory_location(CFG, REPORT_ID, DATASET_ID)
        blob = service.get_blob_client(container, name)
        blob.upload_blob(blob.download_blob().readall(), overwrite=True)

        conflict = azure_blob.publish_snapshot_memory(CFG, out, REPORT_ID, DATASET_ID, stale_hydration)
        check("publishing against a stale etag is refused as a conflict, never "
             "silently overwritten", conflict["status"] == "conflict", conflict)


def test_blob_path_is_scoped_by_both_dataset_and_report() -> None:
    print("\n=== the blob path never collides across reports or datasets ===")
    a = azure_blob._snapshot_memory_location(CFG, "ageing", "dataset-1")
    b = azure_blob._snapshot_memory_location(CFG, "sku_overview", "dataset-1")
    c = azure_blob._snapshot_memory_location(CFG, "ageing", "dataset-2")
    check("two reports over the same dataset get different blob names", a[2] != b[2], (a, b))
    check("the same report over two datasets gets different blob names", a[2] != c[2], (a, c))
    check("the report id and dataset id both appear in the path",
          "ageing" in a[2] and "dataset-1" in a[2], a)


def test_scan_archive_survives_a_disk_wipe() -> None:
    """The archive had the same defect the memory file was fixed for.

    `archive.write` keeps a dated scan beside the outputs and
    `archive.compare_window` reads it back the next morning. In a scheduled job
    the filesystem is new every run, so the archive was write-only: every
    morning found no prior and every page stated that today was the first
    position ever kept.
    """
    print("\n=== the kept stock positions survive a wiped disk too ===")
    from src.domains.inventory import archive

    cfg = dict(CFG, azure_blob_scan_archive_prefix="scan-archive")
    service = _Service()
    scan_day_one = {"snapshot": [{"[as_at]": "2026-08-26T00:00:00",
                                  "[stock_value]": 13801247.91}]}
    scan_day_two = {"snapshot": [{"[as_at]": "2026-08-27T00:00:00",
                                  "[stock_value]": 13966417.0}]}

    with tempfile.TemporaryDirectory() as tmp, patch.object(
        azure_blob, "_service_client", return_value=(service, "fake")
    ):
        day_one = Path(tmp) / "run1"
        day_one.mkdir()
        first = azure_blob.hydrate_scan_archive(cfg, day_one, REPORT_ID, DATASET_ID)
        check("the first run finds nothing to pull, and says so rather than failing",
              first["status"] == "ok" and first["pulled"] == [], first)
        check("and there is genuinely no prior to compare against",
              archive.latest_prior(day_one, cfg,
                                   run_date=date(2026, 8, 27)) is None)

        archive.write(scan_day_one, day_one, cfg, run_date=date(2026, 8, 26))
        pushed = azure_blob.publish_scan_archive(cfg, day_one, REPORT_ID, DATASET_ID)
        check("day one's position is published",
              pushed["status"] == "ok" and pushed["pushed"] == ["scan_2026-08-26.json"],
              pushed)

        # A brand-new machine, exactly as the scheduled job gets each morning.
        day_two = Path(tmp) / "run2"
        day_two.mkdir()
        check("the new machine starts with an empty archive",
              archive.archived_runs(day_two, cfg) == [])
        second = azure_blob.hydrate_scan_archive(cfg, day_two, REPORT_ID, DATASET_ID)
        check("hydration pulls yesterday's position down",
              second["status"] == "ok"
              and second["pulled"] == ["scan_2026-08-26.json"], second)

        prior = archive.latest_prior(day_two, cfg, run_date=date(2026, 8, 27))
        check("so today CAN be compared against yesterday", prior is not None)
        check("and it is yesterday's actual position, not an empty file",
              prior is not None and prior[0] == date(2026, 8, 26)
              and prior[1] == scan_day_one)

        window = archive.compare_window(scan_day_two, day_two, cfg,
                                        run_date=date(2026, 8, 27))
        check("the page may state a comparison rather than 'first position kept'",
              window["comparable"] is True, window["reason"])

        archive.write(scan_day_two, day_two, cfg, run_date=date(2026, 8, 27))
        azure_blob.publish_scan_archive(cfg, day_two, REPORT_ID, DATASET_ID)
        blobs = sorted(service.data["insightstate"])
        check("both positions are now kept in the cloud",
              blobs == [
                  "scan-archive/dataset-abc/reports/daily_sales/scan_2026-08-26.json",
                  "scan-archive/dataset-abc/reports/daily_sales/scan_2026-08-27.json"],
              blobs)

    print("\n--- it stays off unless the storage switch is on ---")
    off = azure_blob.hydrate_scan_archive({}, "/tmp/x", REPORT_ID, DATASET_ID)
    check("no config -> skipped, never touches the network",
          off["status"] == "skipped")
    check("publishing is skipped on the same switch",
          azure_blob.publish_scan_archive({}, "/tmp/x", REPORT_ID,
                                          DATASET_ID)["status"] == "skipped")
    # The defect this pins: Inventory Management uses no snapshot memory, so
    # `snapshot_memory_storage` is absent from its config - and keying the
    # archive on that key alone left the fix inert on the one report that has
    # the problem it fixes. It follows where the output already goes instead.
    check("a report that publishes to blob keeps its positions there too",
          azure_blob.cloud_scan_archive_enabled(
              {"azure_blob_upload": True}) is True)
    check("a report whose snapshot memory is in the cloud does as well",
          azure_blob.cloud_scan_archive_enabled(
              {"snapshot_memory_storage": "azure_blob"}) is True)
    check("a purely local run keeps them on the local disk",
          azure_blob.cloud_scan_archive_enabled({}) is False)
    check("it can be forced off even where the output is published",
          azure_blob.cloud_scan_archive_enabled(
              {"azure_blob_upload": True,
               "inventory_archive_storage": "local"}) is False)
    check("and forced on where nothing else is",
          azure_blob.cloud_scan_archive_enabled(
              {"inventory_archive_storage": "azure_blob"}) is True)


    print("\n--- one folder per dataset AND report, like the memory beside it ---")
    _acct, _cont, folder = azure_blob._scan_archive_location(
        dict(CFG, azure_blob_scan_archive_prefix="scan-archive"), "r-1", "d-1")
    other = azure_blob._scan_archive_location(
        dict(CFG, azure_blob_scan_archive_prefix="scan-archive"), "r-2", "d-1")[2]
    check("two reports over one model do not share an archive", folder != other,
          f"{folder} vs {other}")


def main() -> int:
    print("=" * 72)
    print("Snapshot memory - Azure Blob persistence (Ageing/SKU Overview/Daily Sales)")
    print("=" * 72)

    test_disabled_by_default()
    test_memory_survives_a_local_disk_wipe_between_runs()
    test_etag_conflict_is_refused_not_clobbered()
    test_blob_path_is_scoped_by_both_dataset_and_report()
    test_scan_archive_survives_a_disk_wipe()

    print("\n" + "=" * 72)
    if _failures:
        print(f"SNAPSHOT CLOUD MEMORY FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
