"""Offline replay: Top Insights highlights for the Web App's Home (Ver 4).

Asserts (Web App docs/home-v4/PLAN.md 7a):

1. The item model: extra fields forbidden, absent fields left out (never null).
2. Stable ids: the same fact keeps its id across runs; different facts,
   kinds or reports do not collide.
3. Tone from direction and goodDirection.
4. Daily Sales extractor: the store furthest above its OWN benchmark (as a
   share), never a store below it; a streak only from a run_above fact; and
   the same on a page built by the real Daily Sales code (shape guard).
5. The shared list: one-day window, report-aware merge on reportSlug (a rerun
   replaces only its own report), dedupe, and a cap that keeps every report.
6. End to end: two reports publishing into one in-memory container, and the
   config flag documented in the catalogue with its default OFF.
7. Target Tracker extractor: what the month still needs (milestone / risk with
   the report's own bands), top and lowest branch, on a real built model too.
8. Sales vs Previous Year extractor: riser and faller from the ranked coverage,
   the headline relevance floor with no fallback, steady never; and on
   coverage built by the real coverage builder (shape guard).
9. The hooks in the three publishers: flag off reads and writes nothing; flag
   on publishes this report's items under its slug and GUIDs.
10. A highlights failure (extractor or storage) never costs the report.
11. Reports whose data ends on different days, published the same morning,
    share one day's list (the publisher stamps the run day).

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import ai_content_publisher as pub  # noqa: E402
from src.tools import highlights as hl  # noqa: E402

FAILURES: list[str] = []
GUID = "8d111712-0000-4000-8000-000000000001"
GUID_TT = "02e86e30-0000-4000-8000-000000000002"
GUID_YOY = "aafb8798-0000-4000-8000-000000000003"
NOW = datetime(2026, 9, 14, 6, 40, tzinfo=timezone.utc)   # 12:10 in Asia/Kolkata


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _item(slug: str, kind: str, subject: str, rank: int, iso: str = "2026-09-13") -> dict:
    return hl.dump([hl.Highlight(
        id=hl.highlight_id(slug, kind, subject), kind=kind, title=f"{slug} {subject}",
        value="1", rank=rank, isoDate=iso, reportIds=[GUID], reportSlug=slug)])[0]


# --- 1. model -----------------------------------------------------------------
def test_model() -> None:
    print("\n[1] Item model")
    item = hl.dump([hl.Highlight(id=1, kind="riser", title="Chocolate sales", value="+34%",
                                 reportIds=[GUID], reportSlug="sales_yoy")])[0]
    check("absent optional fields are left out, not null",
          "detail" not in item and "rank" not in item and None not in item.values())
    check("tone defaults to info", item.get("tone") == "info")
    try:
        hl.Highlight(id=1, kind="riser", title="t", value="v", reportIds=[], reportSlug="s", extra=1)
        check("extra fields are refused", False)
    except Exception:
        check("extra fields are refused", True)
    try:
        hl.Highlight(id=1, kind="banana", title="t", value="v", reportIds=[], reportSlug="s")
        check("an unknown kind is refused", False)
    except Exception:
        check("an unknown kind is refused", True)


# --- 2. ids -------------------------------------------------------------------
def test_ids() -> None:
    print("\n[2] Stable ids")
    a = hl.highlight_id("daily_sales", "leader", "net_sales")
    check("same fact, same id across runs", a == hl.highlight_id("daily_sales", "leader", "net_sales"))
    check("another kind differs", a != hl.highlight_id("daily_sales", "streak", "net_sales"))
    check("another report differs", a != hl.highlight_id("target_tracker", "leader", "net_sales"))
    check("fits a signed 32-bit column", 0 < a < 2**31)


# --- 3. tone ------------------------------------------------------------------
def test_tone() -> None:
    print("\n[3] Tone")
    check("up and good-up is positive", hl.tone_for("up", "up") == "positive")
    check("up and good-down is critical", hl.tone_for("up", "down") == "critical")
    check("unknown good direction is info", hl.tone_for("up", None) == "info")
    check("flat is info", hl.tone_for("flat", "up") == "info")


# --- 4. Daily Sales -----------------------------------------------------------
def _history(sides: list[str]) -> list[dict]:
    return [{"actual": 100.0, "p50": 90.0, "side": side} for side in sides]


def _page(stores: list[tuple[str, float, float]], margin_sides: list[str], as_at: str = "2026-09-13") -> dict:
    """The page's shape where the extractor reads it: raw store figures in
    ``store_bundles`` (``stores`` holds them formatted), the scorecard history."""
    return {
        "report_id": "daily_sales", "title": "Daily Sales", "currency": "USD", "as_at": as_at,
        "store_bundles": [{"name": n, "net_sales": {"actual": a, "p50": b}} for n, a, b in stores],
        "scorecard": {"margin": {"history": _history(margin_sides)}},
    }


def _real_page() -> dict:
    """A page built by the real Daily Sales code from the Daily Sales replay's scan."""
    from scripts.replay_daily_sales import CFG, synthetic_scan
    from src.domains.sales import daily_sales as ds
    from src.domains.sales import daily_sales_dashboard as dash

    return dash.build(ds.build(synthetic_scan(), CFG))


def test_daily_sales() -> None:
    print("\n[4] Daily Sales extractor")
    page = _page([("ST1", 50_000, 40_000), ("ST2", 12_000, 8_000), ("ST3", 30_000, 31_000)],
                 ["inside", "above", "above", "above"])
    items = hl.from_daily_sales(page, [GUID])
    leader = next((i for i in items if i.kind == "leader"), None)
    check("the leader is the largest lead as a SHARE of its benchmark (ST2 +50%, not ST1 +25%)",
          leader is not None and leader.value == "ST2", str(leader))
    check("the leader carries its figure and the lead",
          leader is not None and leader.detail and "+50.0%" in (leader.comparisonLabel or ""))
    streak = next((i for i in items if i.kind == "streak"), None)
    check("a run above the normal range becomes a streak with its length",
          streak is not None and streak.value == "3 days" and streak.title.startswith("Margin"), str(streak))
    check("every item is tagged with the report's GUIDs and slug; the date is the publisher's",
          all(i.reportIds == [GUID] and i.reportSlug == "daily_sales" and i.isoDate is None for i in items))
    named = hl.from_daily_sales(page, [GUID], report_slug="ds_sbmart", report_name="SB Mart Daily Sales")
    check("the caller's slug and name win over the page's",
          all(i.reportSlug == "ds_sbmart" and i.reportName == "SB Mart Daily Sales" for i in named))

    below = hl.from_daily_sales(_page([("ST1", 30_000, 31_000)], ["inside", "below", "below"]), [GUID])
    check("no store above its benchmark: no leader", not any(i.kind == "leader" for i in below))
    check("a run BELOW the range is not a highlight", not any(i.kind == "streak" for i in below))

    # Shape guard: the session-3 fixture read `stores[].net_sales`, which the
    # real page does not have, and passed. Run on the real page instead.
    real = _real_page()
    bundles = real.get("store_bundles") or []
    check("the real page still carries raw figures in store_bundles",
          bool(bundles) and all("name" in b and "actual" in (b.get("net_sales") or {}) for b in bundles))
    if bundles:
        lifted = json.loads(json.dumps(real, default=str))
        target = lifted["store_bundles"][-1]
        target["net_sales"]["actual"] = float(target["net_sales"]["p50"]) * 1.5
        leader = next((i for i in hl.from_daily_sales(lifted, [GUID]) if i.kind == "leader"), None)
        check("on the real page, a store lifted above its benchmark leads",
              leader is not None and leader.value == target["name"] and "+50.0%" in (leader.comparisonLabel or ""),
              str(leader))


# --- 5. the shared list -------------------------------------------------------
def test_merge_and_cap() -> None:
    print("\n[5] Shared list: merge and cap")
    run = date(2026, 9, 13)
    previous = [
        _item("target_tracker", "leader", "branch", 1),
        _item("daily_sales", "leader", "old", 1),
        _item("sales_yoy", "riser", "choc", 1, iso="2026-09-12"),
    ]
    today = [_item("daily_sales", "leader", "net_sales", 1), _item("daily_sales", "streak", "margin", 2)]
    merged = pub.merge_highlights(previous, today, run, "daily_sales")
    slugs = [m["reportSlug"] for m in merged]
    check("another report's same-day item survives", "target_tracker" in slugs)
    check("this report's earlier same-day item is replaced",
          not any(m["title"].endswith("old") for m in merged))
    check("yesterday's item is dropped (one-day window)", "sales_yoy" not in slugs)
    check("ordered by rank, interleaving reports", [m["rank"] for m in merged] == sorted(m["rank"] for m in merged))
    dup = pub.merge_highlights([], today + today, run, "daily_sales")
    check("duplicate (reportSlug, id) pairs collapse", len(dup) == 2)

    many = [_item("daily_sales", "streak", f"m{i}", i + 1) for i in range(6)] + [_item("target_tracker", "leader", "b", 9)]
    capped = pub._cap_highlights(many, {"ai_content_highlights_max_items": 3})
    check("the cap holds", len(capped) == 3)
    check("a quieter report keeps a place under the cap", any(c["reportSlug"] == "target_tracker" for c in capped))
    check("the temporary ordering key never reaches the payload",
          all(not any(k.startswith("__") for k in c) for c in capped))


# --- in-memory Azure ----------------------------------------------------------
class _Download:
    def __init__(self, item):
        self.item = item
        self.properties = SimpleNamespace(etag=item["etag"])

    def readall(self):
        return self.item["data"]


class _Blob:
    def __init__(self, service, container, name):
        self.service, self.container, self.name = service, container, name

    def download_blob(self):
        from azure.core.exceptions import ResourceNotFoundError

        self.service.reads.append((self.container, self.name))
        try:
            return _Download(self.service.data[self.container][self.name])
        except KeyError as exc:
            raise ResourceNotFoundError(self.name) from exc

    def upload_blob(self, data=None, overwrite=False, content_settings=None, metadata=None,
                    etag=None, match_condition=None, **kwargs):
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

        if self.name in self.service.fail_on:
            raise RuntimeError("storage down")
        current = self.service.data[self.container].get(self.name)
        if current and not overwrite:
            raise ResourceExistsError("exists")
        if overwrite and etag is not None and (not current or current["etag"] != etag):
            raise ResourceModifiedError("etag mismatch")
        raw = data.read() if hasattr(data, "read") else data
        raw = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        self.service.version += 1
        self.service.data[self.container][self.name] = {"data": raw, "etag": f'"etag-{self.service.version}"'}


class _Container:
    def __init__(self, service, name):
        self.service, self.name = service, name

    def get_blob_client(self, name):
        return _Blob(self.service, self.name, name)


class _Service:
    def __init__(self, fail_on: tuple = ()):
        self.data: dict = defaultdict(dict)
        self.reads: list = []
        self.fail_on = set(fail_on)
        self.version = 0

    def get_container_client(self, name):
        return _Container(self, name)

    def highlights(self, container: str = "sb-mart") -> list[dict] | None:
        item = self.data[container].get(pub.HIGHLIGHTS_BLOB)
        return None if item is None else json.loads(item["data"]).get("payload")

    def touched_highlights(self) -> bool:
        return any(name == pub.HIGHLIGHTS_BLOB for _, name in self.reads) or any(
            pub.HIGHLIGHTS_BLOB in blobs for blobs in self.data.values())


# --- 6. end to end ------------------------------------------------------------
def test_end_to_end() -> None:
    print("\n[6] End to end: two reports into one container; config catalogue")
    container = _Service().get_container_client("sb-mart")
    kwargs = dict(client="sbmart", dataset_id="ds", cfg={}, now=NOW,
                  expires=NOW + timedelta(hours=24), json_settings=None, receipts={})
    pub.publish_highlights(container, items=[_item("daily_sales", "leader", "net_sales", 1)],
                           report_slug="daily_sales", **kwargs)
    pub.publish_highlights(container, items=[_item("target_tracker", "leader", "branch", 1)],
                           report_slug="target_tracker", **kwargs)
    pub.publish_highlights(container, items=[_item("daily_sales", "streak", "margin", 2)],
                           report_slug="daily_sales", **kwargs)
    raw = container.service.data["sb-mart"][pub.HIGHLIGHTS_BLOB]["data"]
    body = json.loads(raw)
    payload = body.get("payload") or []
    check("published inside the v1 envelope", body.get("schemaVersion") == 1 and isinstance(payload, list))
    check("both reports present after three runs",
          {p["reportSlug"] for p in payload} == {"daily_sales", "target_tracker"})
    check("the daily_sales rerun replaced its own first item",
          [p["kind"] for p in payload if p["reportSlug"] == "daily_sales"] == ["streak"])
    check("the receipt records the write", kwargs["receipts"].get(pub.HIGHLIGHTS_BLOB, {}).get("status") == "ok")
    try:
        pub.publish_highlights(container, items=[_item("sales_yoy", "riser", "x", 1)],
                               report_slug="daily_sales", **kwargs)
        check("an item tagged with another report's slug is refused", False)
    except ValueError:
        check("an item tagged with another report's slug is refused", True)

    from src import config_schema

    keys = {k.key: k for k in config_schema.all_keys()} if hasattr(config_schema, "all_keys") else {}
    if not keys:
        text = (PROJECT_ROOT / "src" / "config_schema.py").read_text(encoding="utf-8")
        check("ai_content_highlights is catalogued", '"ai_content_highlights", "bool", False' in text)
    else:
        check("ai_content_highlights is catalogued, default OFF",
              "ai_content_highlights" in keys and keys["ai_content_highlights"].default is False)


# --- 7. Target Tracker --------------------------------------------------------
def _tt_model(*, full=1000.0, mtd_actual=900.0, mtd_target=950.0, days_in_month=31,
              days_elapsed=27, branches=()) -> dict:
    """The model fields the extractor reads, related as target_tracker.build relates them."""
    remaining, needed = full - mtd_target, full - mtd_actual
    return {
        "report_id": "target_tracker", "report_name": "Target Tracker",
        "periods": {"mtd": {"actual": mtd_actual, "target": mtd_target,
                            "attainment": mtd_actual / mtd_target * 100.0}},
        "month_full_target": full,
        "month_close": {"needed": needed, "remaining_target": remaining,
                        "needed_vs_target": (needed / remaining * 100.0) if remaining else None},
        "days_in_month": days_in_month, "days_elapsed": days_elapsed,
        "branches": [{"name": n, "mtd": {"attainment": a}} for n, a in branches],
    }


def _month(items):
    return next((i for i in items if i.title.startswith("Month target")), None)


def test_target_tracker() -> None:
    print("\n[7] Target Tracker extractor")
    crit = _month(hl.from_target_tracker(_tt_model(mtd_actual=855.0), [GUID_TT]))
    check("behind, in the Below-target band: a critical risk, the share of plan the days left need",
          crit is not None and crit.kind == "risk" and crit.tone == "critical" and crit.value == "290.0%"
          and crit.comparisonLabel == "of plan needed on the 4 days left", str(crit))
    watch = _month(hl.from_target_tracker(_tt_model(mtd_actual=922.0), [GUID_TT]))
    check("behind, in the Watch band: a warning", watch is not None and watch.kind == "risk"
          and watch.tone == "warning", str(watch))
    reach = _month(hl.from_target_tracker(_tt_model(mtd_actual=980.0), [GUID_TT]))
    check("ahead: a positive milestone (the days left need under their plan)",
          reach is not None and reach.kind == "milestone" and reach.tone == "positive"
          and reach.value == "40.0%", str(reach))
    done = _month(hl.from_target_tracker(_tt_model(mtd_actual=1010.0), [GUID_TT]))
    check("the full month's target already reached is the milestone",
          done is not None and done.title == "Month target reached" and done.value == "101.0%"
          and done.comparisonLabel == "of the full month, 4 days left", str(done))
    last = _month(hl.from_target_tracker(_tt_model(mtd_actual=980.0, days_elapsed=30), [GUID_TT]))
    check("one day left says '1 day'", last is not None and last.comparisonLabel.endswith("the 1 day left"))
    over = hl.from_target_tracker(_tt_model(mtd_actual=900.0, mtd_target=1000.0, days_elapsed=31), [GUID_TT])
    check("a finished month gives no month-target item", _month(over) is None)

    branches = hl.from_target_tracker(
        _tt_model(branches=[("ST1", 91.3), ("ST2", 104.0), ("Unassigned", 50.0)]), [GUID_TT])
    top = next((i for i in branches if i.kind == "leader"), None)
    low = next((i for i in branches if i.kind == "laggard"), None)
    check("top branch: the best month-so-far share, on target",
          top is not None and top.value == "ST2" and top.detail == "104.0%" and top.tone == "positive", str(top))
    check("lowest branch: the worst, in the Below-target band ('Unassigned' is not a branch)",
          low is not None and low.value == "ST1" and low.tone == "critical", str(low))
    quiet = hl.from_target_tracker(_tt_model(branches=[("A", 96.0), ("B", 99.0)]), [GUID_TT])
    check("every branch behind but in Watch: no top branch, no lowest branch",
          not any(i.kind in ("leader", "laggard") for i in quiet))
    alone = hl.from_target_tracker(_tt_model(branches=[("A", 120.0)]), [GUID_TT])
    check("one branch has nothing to be compared with", not any(i.kind in ("leader", "laggard") for i in alone))
    check("ranks: month 1, top branch 2, lowest branch 3",
          [i.rank for i in hl.from_target_tracker(
              _tt_model(mtd_actual=855.0, branches=[("ST1", 91.3), ("ST2", 104.0)]), [GUID_TT])] == [1, 2, 3])

    from scripts.replay_target_tracker import synthetic
    from src.domains.sales import target_tracker as tt

    real = hl.from_target_tracker(tt.build(synthetic()), [GUID_TT])
    kinds = {i.kind: i for i in real}
    check("on a real built model: a month item and both branch items",
          _month(real) is not None and "leader" in kinds and "laggard" in kinds, str([i.kind for i in real]))
    check("on a real built model: the best and worst branches by month-so-far share",
          kinds.get("leader") is not None and kinds["leader"].value == "CFH018"
          and kinds.get("laggard") is not None and kinds["laggard"].value == "CFH017",
          str([(i.kind, i.value) for i in real]))


# --- 8. Sales vs Previous Year -------------------------------------------------
def _row(member: str, change_pct: float, impact: float, score: float, severity: str = "watch") -> dict:
    return {"member": member, "change_pct": change_pct, "change": change_pct * 1000.0,
            "global_impact_pct": impact, "rank_score": score, "severity": severity,
            "comparable": True,
            "direction": "up" if change_pct > 0 else "down" if change_pct < 0 else "flat"}


def _coverage(store_rows: list[dict], division_rows: list[dict] = ()) -> dict:
    levels = [{"role": "store", "rows": store_rows}]
    if division_rows:
        levels.append({"role": "division", "rows": list(division_rows)})
    return {"status": "ok", "metric_family": "revenue",
            "thresholds": {"headline_min_impact_pct": 0.05}, "levels": levels}


def test_sales_yoy() -> None:
    print("\n[8] Sales vs Previous Year extractor")
    cov = _coverage(
        [_row("ST9", 300.0, 0.01, 0.95, "critical"),      # a spectacular ratio worth nothing
         _row("ST2", -5.7, 1.2, 0.40),
         _row("ST4", 10.6, 2.9, 0.24, "critical"),
         _row("ST7", 2.0, 0.5, 0.90, "steady")],          # no material change
        [_row("CONSUMER GOODS", 10.0, 4.8, 0.68)])
    items = hl.from_sales_yoy(cov, [GUID_YOY], report_name="SB Mart Sales vs Previous Year")
    riser = next((i for i in items if i.kind == "riser"), None)
    faller = next((i for i in items if i.kind == "faller"), None)
    check("riser: the highest-ranked rise across levels",
          riser is not None and riser.title == "CONSUMER GOODS" and riser.value == "+10.0%"
          and riser.comparisonLabel == "division sales vs last year" and riser.tone == "positive", str(riser))
    check("faller: the highest-ranked fall",
          faller is not None and faller.title == "ST2" and faller.value == "-5.7%"
          and faller.comparisonLabel == "store sales vs last year" and faller.tone == "critical", str(faller))
    check("a big percentage under the relevance floor never qualifies",
          not any(i.title == "ST9" for i in items))
    check("a steady member never qualifies, whatever its score", not any(i.title == "ST7" for i in items))
    check("riser rank 1, faller rank 2", riser is not None and faller is not None
          and (riser.rank, faller.rank) == (1, 2))
    check("tagged with the run's GUIDs, slug and name",
          all(i.reportIds == [GUID_YOY] and i.reportSlug == "sales_yoy"
              and i.reportName == "SB Mart Sales vs Previous Year" for i in items))
    quiet = hl.from_sales_yoy(_coverage([_row("ST1", 40.0, 0.02, 0.9), _row("ST2", -30.0, 0.01, 0.8)]),
                              [GUID_YOY])
    check("nothing above the floor: no highlight (the headline's fallback does not apply)", quiet == [])
    check("no coverage: no highlight, no error", hl.from_sales_yoy({}, [GUID_YOY]) == [])

    from src.tools import summary_coverage

    def member(name, current, prior, share, impact):
        return {"member": name, "current": current, "prior": prior, "change": current - prior,
                "change_pct": (current - prior) / prior * 100.0,
                "business_share_pct": share, "global_impact_pct": impact}

    universe = {"metric_family": "revenue", "roles": {"store": {
        "status": "ok", "column": "store_no", "level": None,
        "members": [member("ST1", 120.0, 100.0, 40.0, 6.0), member("ST2", 85.0, 100.0, 30.0, 4.5),
                    member("ST3", 101.0, 100.0, 30.0, 0.3)]}}}
    built = hl.from_sales_yoy(summary_coverage.build_coverage(universe), [GUID_YOY])
    check("on coverage built by the real builder: ST1 rises, ST2 falls",
          [(i.kind, i.title, i.value) for i in built] == [("riser", "ST1", "+20.0%"), ("faller", "ST2", "-15.0%")],
          str([(i.kind, i.title, i.value) for i in built]))


# --- 9-11. the hooks -----------------------------------------------------------
def _ds_cfg(**over) -> dict:
    return {"azure_blob_account": "acct", "ai_content_report_ids": [GUID],
            "ai_content_publish_enabled": True, "ai_content_client": "sb-mart",
            "report_id": "daily_sales", "report_name": "SB Mart Daily Sales", "dataset_id": "ds-1",
            "ai_content_highlights": True, **over}


def _tt_cfg(**over) -> dict:
    return {**_ds_cfg(**over), "ai_content_report_ids": [GUID_TT], "report_id": "target_tracker",
            "report_name": "SB Mart Target Tracker", "target_tracker_currency": "USD",
            "azure_blob_prefix": "targettracker"}


def _publish_ds(svc, cfg, page=None, now=NOW) -> dict:
    from src.domains.sales import daily_sales_publish

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "report_daily_sales.html").write_text("<html></html>", encoding="utf-8")
        page = page or _page([("ST1", 50_000, 40_000)], ["inside", "above", "above"])
        return daily_sales_publish.publish(cfg, out, page, service_client=svc, generated_at=now)


def _publish_tt(svc, cfg, model=None, now=NOW) -> dict:
    from scripts.replay_target_tracker import synthetic
    from src.domains.sales import target_tracker as tt
    from src.domains.sales import target_tracker_publish

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "report_target_tracker.html").write_text("<html></html>", encoding="utf-8")
        (out / "report_target_tracker.md").write_text("# Target Tracker", encoding="utf-8")
        return target_tracker_publish.publish(cfg, out, model or tt.build(synthetic()),
                                              service_client=svc, generated_at=now)


def _publish_yoy(svc, flag: bool, coverage: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "api").mkdir()
        (root / "api" / "kpi_insights.json").write_text("[]", encoding="utf-8")
        (root / "api" / "report_summary.json").write_text(json.dumps({
            "title": "Sales vs Previous Year", "generatedAt": "2026-09-14", "headline": "Up on last year",
            "metrics": [], "sections": []}), encoding="utf-8")
        (root / "report_summary.html").write_text("<html></html>", encoding="utf-8")
        state = {"dataset_id": "ds-yoy", "output_folder": str(root), "summary_coverage": coverage,
                 "config": {"ai_content_publish_enabled": True, "ai_content_client": "sb-mart",
                            "azure_blob_account": "acct", "ai_content_multi_report_feed": True,
                            "report_id": "sales_yoy", "report_name": "SB Mart Sales vs Previous Year",
                            "ai_content_highlights": flag}}
        return pub.publish(state, generated_at=NOW, service_client=svc, report_ids=[GUID_YOY])


def _yoy_coverage() -> dict:
    return _coverage([_row("ST2", -5.7, 1.2, 0.40), _row("ST4", 10.6, 2.9, 0.24, "critical")])


def test_hooks() -> None:
    print("\n[9] Hooks: flag off reads and writes nothing; on publishes under the report's slug")
    off = _Service()
    receipt = _publish_ds(off, _ds_cfg(ai_content_highlights=False))
    check("Daily Sales, flag off: report ok, highlights skipped, the list never read or written",
          receipt.get("status") == "ok" and receipt.get("highlightsStatus") == "skipped"
          and not off.touched_highlights(), str(receipt.get("highlightsStatus")))
    off = _Service()
    receipt = _publish_tt(off, _tt_cfg(ai_content_highlights=False))
    check("Target Tracker, flag off: same", receipt.get("status") == "ok"
          and receipt.get("highlightsStatus") == "skipped" and not off.touched_highlights())
    off = _Service()
    receipt = _publish_yoy(off, False, _yoy_coverage())
    check("Sales YoY, flag off: same", receipt.get("status") == "ok"
          and receipt.get("highlightsStatus") == "skipped" and not off.touched_highlights(), str(receipt))
    off = _Service()
    _publish_ds(off, _ds_cfg(ai_content_highlights=True, ai_content_publish_enabled=False))
    check("app publishing off: nothing, even with the highlights flag on", not off.touched_highlights())

    svc = _Service()
    ds = _publish_ds(svc, _ds_cfg())
    tt_receipt = _publish_tt(svc, _tt_cfg())
    yoy = _publish_yoy(svc, True, _yoy_coverage())
    payload = svc.highlights() or []
    by_slug = defaultdict(list)
    for item in payload:
        by_slug[item["reportSlug"]].append(item)
    check("all three report ok with highlights ok",
          [r.get("status") for r in (ds, tt_receipt, yoy)] == ["ok"] * 3
          and [r.get("highlightsStatus") for r in (ds, tt_receipt, yoy)] == ["ok"] * 3,
          str([r.get("highlightsStatus") for r in (ds, tt_receipt, yoy)]))
    check("the shared list holds all three reports", set(by_slug) == {"daily_sales", "target_tracker", "sales_yoy"},
          str(sorted(by_slug)))
    check("each report's items carry its own GUIDs",
          all(i["reportIds"] == [GUID] for i in by_slug["daily_sales"])
          and all(i["reportIds"] == [GUID_TT] for i in by_slug["target_tracker"])
          and all(i["reportIds"] == [GUID_YOY] for i in by_slug["sales_yoy"]))
    check("each report's items carry its configured name",
          {i["reportName"] for i in payload} == {"SB Mart Daily Sales", "SB Mart Target Tracker",
                                                  "SB Mart Sales vs Previous Year"})
    check("per-report cap (default 2) holds", all(len(v) <= 2 for v in by_slug.values()))
    check("the Sales YoY receipt keeps insight and summary ok",
          yoy.get("insightStatus") == "ok" and yoy.get("summaryStatus") == "ok", str(yoy))

    # A rerun with nothing to say clears the report's own items for the day.
    quiet_page = _page([("ST1", 30_000, 31_000)], ["inside", "below"])
    _publish_ds(svc, _ds_cfg(), page=quiet_page)
    after = svc.highlights() or []
    check("a rerun with no facts clears its own items and keeps the others'",
          not any(i["reportSlug"] == "daily_sales" for i in after)
          and {i["reportSlug"] for i in after} == {"target_tracker", "sales_yoy"})


def test_failures() -> None:
    print("\n[10] A highlights failure never costs the report")
    down = _Service(fail_on=(pub.HIGHLIGHTS_BLOB,))
    ds = _publish_ds(down, _ds_cfg())
    check("storage failure, Daily Sales: report ok, the failure is in the receipt",
          ds.get("status") == "ok" and ds.get("appStatus") == "ok"
          and str(ds.get("highlightsStatus")).startswith("failed: RuntimeError"), str(ds.get("highlightsStatus")))
    tt_receipt = _publish_tt(_Service(fail_on=(pub.HIGHLIGHTS_BLOB,)), _tt_cfg())
    check("storage failure, Target Tracker: report ok",
          tt_receipt.get("status") == "ok" and str(tt_receipt.get("highlightsStatus")).startswith("failed"))
    yoy = _publish_yoy(_Service(fail_on=(pub.HIGHLIGHTS_BLOB,)), True, _yoy_coverage())
    check("storage failure, Sales YoY: report, insight and summary ok",
          yoy.get("status") == "ok" and yoy.get("insightStatus") == "ok"
          and yoy.get("summaryStatus") == "ok" and str(yoy.get("highlightsStatus")).startswith("failed"),
          str(yoy))

    original = hl.from_target_tracker

    def broken(*args, **kwargs):
        raise KeyError("branches")

    hl.from_target_tracker = broken
    try:
        tt_receipt = _publish_tt(_Service(), _tt_cfg())
    finally:
        hl.from_target_tracker = original
    check("an extractor fault: report ok, the fault is in the receipt",
          tt_receipt.get("status") == "ok" and tt_receipt.get("highlightsStatus") == "failed: KeyError: 'branches'",
          str(tt_receipt.get("highlightsStatus")))


def test_run_day() -> None:
    print("\n[11] Different data dates, one run day")
    svc = _Service()
    _publish_ds(svc, _ds_cfg(), page=_page([("ST1", 50_000, 40_000)], ["inside", "above", "above"],
                                           as_at="2026-09-13"))
    _publish_tt(svc, _tt_cfg())                        # its model's anchor is 2026-07-16
    payload = svc.highlights() or []
    check("Daily Sales (data to 13 Sep) and Target Tracker (data to 16 Jul) share the morning's list",
          {i["reportSlug"] for i in payload} == {"daily_sales", "target_tracker"},
          str(sorted({i["reportSlug"] for i in payload})))
    check("every item is stamped with the run day in the configured timezone",
          {i.get("isoDate") for i in payload} == {"2026-09-14"}, str({i.get("isoDate") for i in payload}))
    _publish_ds(svc, _ds_cfg(), now=NOW + timedelta(days=1))
    nextday = svc.highlights() or []
    check("next day: the first report to run starts a new list (one-day window)",
          {i["reportSlug"] for i in nextday} == {"daily_sales"}
          and {i.get("isoDate") for i in nextday} == {"2026-09-15"})


def main() -> int:
    print("=" * 72)
    print("REPLAY: Top Insights highlights (Web App Home Ver 4, PLAN 7a)")
    print("=" * 72)
    test_model()
    test_ids()
    test_tone()
    test_daily_sales()
    test_merge_and_cap()
    test_end_to_end()
    test_target_tracker()
    test_sales_yoy()
    test_hooks()
    test_failures()
    test_run_day()
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
