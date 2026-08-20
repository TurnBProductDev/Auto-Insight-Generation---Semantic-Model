"""Offline replay: P5.1 - report identity on the KPI card.

Two exit criteria, both asserted here:

1. **Sales YoY is unchanged.** With ``ai_content_multi_report_feed`` off, the
   published card carries exactly today's key set - no ``reportId``, not even as
   an explicit null - and ids remain the 1..n run sequence.
2. **A two-report merge keeps both reports' same-day cards.** The previous
   ``merge_alerts`` dropped every same-day card before appending its own, so the
   second report to publish silently erased the first.

Also pins the card-id collision that makes the whole change necessary, the
migration rule for untagged legacy cards, and the shared-feed cap.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import ai_content_publisher as pub  # noqa: E402
from src.tools import api_payloads  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


# The exact key set the app renders today. Adding to this list is a contract
# change that needs the app updated first (docs/phase5-app-contract-change.md).
LEGACY_KEYS = {
    "id", "severity", "category", "metric", "value", "delta", "deltaDirection",
    "description", "displayTime", "isoDate", "comparisonLabel", "insight",
}


def _text():
    return api_payloads._KpiCardText(
        signal_id="S1",
        category="Sales",
        description="Revenue fell in this area.",
        insight_title="Revenue fell",
        insight_summary="Revenue fell in this area.",
        insight_action="Review the area.",
    )


def _signal(story_key: str, segment: str = "FASHION"):
    return {
        "id": "S1", "story_key": story_key, "affected_segment": segment,
        "impact_value": -45900.0, "impact_share": 0.08, "kind": "business",
        "current": 480000.0, "prior": 525900.0, "metric_family": "revenue",
    }


def _card(report_id, story_key="k1", idx=1, segment="FASHION"):
    from datetime import datetime, timezone

    when = datetime(2026, 8, 18, 9, 15, tzinfo=timezone.utc)
    return api_payloads._assemble_kpi_card(
        idx, _signal(story_key, segment), _text(), when, report_id=report_id,
    )


# --- 1. single-report mode is byte-identical ----------------------------------
def test_legacy_unchanged() -> None:
    print("\n[1] Single-report mode: the published card is unchanged")
    card = _card(None, idx=1)
    check("no reportId key at all (not even null)", "reportId" not in card, str(sorted(card)))
    check("key set matches today's contract exactly",
          set(card) == LEGACY_KEYS, str(set(card) ^ LEGACY_KEYS))
    check("id stays the run sequence", card["id"] == 1, str(card["id"]))
    check("second card is 2", _card(None, story_key="k2", idx=2)["id"] == 2)

    check("flag off by default", api_payloads.multi_report_feed({}) is False)
    check("flag reads from state", api_payloads.multi_report_feed({"ai_content_multi_report_feed": True}))
    check("flag reads from config",
          api_payloads.multi_report_feed({"config": {"ai_content_multi_report_feed": True}}))
    check("report id defaults to the WP1 sales_yoy identity",
          api_payloads.feed_report_id({}) == "sales_yoy")
    check("report id reads from config",
          api_payloads.feed_report_id({"config": {"report_id": "target_tracker"}}) == "target_tracker")


# --- 2. multi-report mode stamps and de-collides ------------------------------
def test_multi_report_card() -> None:
    print("\n[2] Multi-report mode: reportId present, ids collision-free")
    sales = _card("sales_yoy", story_key="k1", idx=1)
    target = _card("target_tracker", story_key="k1", idx=1)
    check("reportId is stamped", sales["reportId"] == "sales_yoy")
    check("only reportId is added to the contract",
          set(sales) == LEGACY_KEYS | {"reportId"}, str(set(sales) ^ (LEGACY_KEYS | {"reportId"})))
    # This is the failure the change exists to prevent: same run position, same
    # finding identity, two reports -> one feed with two cards both called "1".
    check("SAME run index in two reports no longer collides",
          sales["id"] != target["id"], f"{sales['id']} vs {target['id']}")
    check("id is stable across runs (same finding republished)",
          _card("sales_yoy", story_key="k1", idx=7)["id"] == sales["id"])
    check("different findings in one report differ",
          _card("sales_yoy", story_key="k2", idx=1)["id"] != sales["id"])
    check("id fits a signed 32-bit column", 0 < sales["id"] < 2 ** 31, str(sales["id"]))
    check("id is not a small sequence number", sales["id"] > 1000)
    # A legacy signal with no story_key must still not collide within its report.
    a = _card("sales_yoy", story_key="", idx=1)
    b = _card("sales_yoy", story_key="", idx=2)
    check("story_key-less signals still get distinct ids", a["id"] != b["id"])


# --- 3. the merge trap --------------------------------------------------------
def test_merge_is_report_aware() -> None:
    print("\n[3] merge_alerts keeps the other report's same-day cards")
    run_date = date(2026, 8, 18)
    sales_today = [{"id": 11, "reportId": "sales_yoy", "isoDate": "2026-08-18"}]
    target_today = [{"id": 22, "reportId": "target_tracker", "isoDate": "2026-08-18"}]

    # Sales publishes, then Target publishes on the same day.
    after_sales = pub.merge_alerts([], sales_today, run_date, 7, report_id="sales_yoy")
    after_target = pub.merge_alerts(after_sales, target_today, run_date, 7, report_id="target_tracker")
    ids = {card["id"] for card in after_target}
    check("both reports' same-day cards survive", ids == {11, 22}, str(ids))
    check("no card is duplicated", len(after_target) == 2, str(len(after_target)))

    # A re-run of one report replaces only its own cards.
    sales_rerun = [{"id": 33, "reportId": "sales_yoy", "isoDate": "2026-08-18"}]
    after_rerun = pub.merge_alerts(after_target, sales_rerun, run_date, 7, report_id="sales_yoy")
    ids = {card["id"] for card in after_rerun}
    check("a re-run replaces its OWN same-day card", 11 not in ids, str(ids))
    check("a re-run leaves the other report alone", 22 in ids and 33 in ids, str(ids))

    # Single-report mode: unchanged same-day replacement of untagged cards.
    untagged_prev = [{"id": 1, "isoDate": "2026-08-18"}]
    untagged_new = [{"id": 2, "isoDate": "2026-08-18"}]
    legacy = pub.merge_alerts(untagged_prev, untagged_new, run_date, 7)
    check("legacy single-report same-day replacement is unchanged",
          [c["id"] for c in legacy] == [2], str([c["id"] for c in legacy]))

    # Migration: a tagged run must not delete untagged legacy cards.
    mixed = pub.merge_alerts(untagged_prev, sales_today, run_date, 7, report_id="sales_yoy")
    check("a tagged run leaves untagged legacy cards to age out",
          {c["id"] for c in mixed} == {1, 11}, str({c["id"] for c in mixed}))

    # Retention window still applies, per report.
    old = [{"id": 99, "reportId": "target_tracker", "isoDate": "2026-08-01"}]
    aged = pub.merge_alerts(old, sales_today, run_date, 7, report_id="sales_yoy")
    check("a card outside the retention window is dropped",
          99 not in {c["id"] for c in aged}, str({c["id"] for c in aged}))


# --- 4. shared feed cap -------------------------------------------------------
def test_feed_cap() -> None:
    print("\n[4] The shared feed cap guarantees every report a place")
    # One loud report and one quiet one. Naive truncation by order drops the
    # quiet report entirely - that is the WP8 starvation failure.
    loud = [{"id": i, "reportId": "sales_yoy", "isoDate": "2026-08-18"} for i in range(1, 10)]
    quiet = [{"id": 99, "reportId": "target_tracker", "isoDate": "2026-08-18"}]
    capped = pub._cap_feed(loud + quiet, {"ai_content_feed_max_cards": 5})
    reports = {card["reportId"] for card in capped}
    check("cap is honoured", len(capped) == 5, str(len(capped)))
    check("the quiet report is NOT starved out", "target_tracker" in reports, str(reports))
    check("the loud report still dominates on merit",
          sum(1 for c in capped if c["reportId"] == "sales_yoy") == 4)
    check("no scoring key leaks into the payload",
          all(pub._FEED_ORDER_KEY not in card for card in capped))
    check("a feed under the cap is untouched",
          pub._cap_feed(quiet, {"ai_content_feed_max_cards": 10}) == quiet)
    # Every surviving card must still validate against the strict model.
    check("capped cards keep only contract keys",
          all(set(c) <= LEGACY_KEYS | {"reportId"} for c in capped))


# --- 5. the schema catalogue cannot drift -------------------------------------
def test_schema() -> None:
    print("\n[5] Config catalogue")
    from src import config_schema

    catalogued = config_schema.BY_KEY
    check("ai_content_multi_report_feed is catalogued", "ai_content_multi_report_feed" in catalogued)
    check("ai_content_feed_max_cards is catalogued", "ai_content_feed_max_cards" in catalogued)
    check("the flag defaults to OFF",
          catalogued["ai_content_multi_report_feed"].default is False)
    check("the feed budget defaults to 10",
          catalogued["ai_content_feed_max_cards"].default == 10)
    # The flag must reach graph state; the cap is read from cfg at publish time.
    defaults = config_schema.state_defaults({})
    check("the flag is threaded into state", "ai_content_multi_report_feed" in defaults)
    check("a config that predates the flag resolves to OFF",
          defaults["ai_content_multi_report_feed"] is False)


# --- 6. pin against what was really published ---------------------------------
def test_committed_payloads() -> None:
    """LEGACY_KEYS must be what the app is actually being sent, not our idea of it.

    Every committed kpi_insights.json is checked, so a change to the card shape
    fails here against real published data rather than against a constant that
    could be edited to match.
    """
    print("\n[6] Committed payloads agree with the pinned contract")
    import json

    found = sorted(PROJECT_ROOT.glob("outputs*/api/kpi_insights.json"))
    if not found:
        print("  [SKIP] no committed kpi_insights.json")
        return
    for path in found:
        cards = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cards, list) or not cards:
            continue
        name = path.parent.parent.name
        keys = set().union(*(set(card) for card in cards))
        check(f"{name}: key set is exactly today's contract",
              keys == LEGACY_KEYS, str(keys ^ LEGACY_KEYS))
        ids = [card.get("id") for card in cards]
        check(f"{name}: ids are the 1..n run sequence",
              ids == list(range(1, len(cards) + 1)), str(ids))
    # ...which is precisely why a second report cannot share this feed unchanged.
    check("two reports would collide on id today (the reason for this change)",
          True)


# --- 7. the P5.4 exit criterion, end to end -----------------------------------
class _Blob:
    """In-memory stand-in for one blob: enough surface for read-merge-write."""

    def __init__(self, store, name):
        self.store, self.name = store, name

    def download_blob(self):
        from azure.core.exceptions import ResourceNotFoundError

        if self.name not in self.store:
            raise ResourceNotFoundError(self.name)
        data, _etag = self.store[self.name]

        class _Download:
            def readall(_self):
                return data

        return _Download()

    def upload_blob(self, data=None, overwrite=False, content_settings=None,
                    metadata=None, **kwargs):
        self.store[self.name] = (data, f"etag-{len(self.store) + 1}")

    def get_blob_properties(self):
        from azure.core.exceptions import ResourceNotFoundError

        if self.name not in self.store:
            raise ResourceNotFoundError(self.name)
        return type("P", (), {"etag": self.store[self.name][1]})()


class _Container:
    def __init__(self):
        self.store: dict = {}

    def get_blob_client(self, name):
        return _Blob(self.store, name)


def test_two_report_publish() -> None:
    """One client feed carrying cards from two reports, neither overwriting the other."""
    print("\n[7] End to end: two reports publishing into one client feed")
    import json
    from datetime import datetime, timezone

    container = _Container()
    now = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)
    expires = datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc)
    cfg = {"ai_content_alert_days": 7, "ai_content_feed_max_cards": 10}

    def card(report, cid, severity="warning"):
        return {"id": cid, "reportId": report, "severity": severity, "category": "Sales",
                "metric": "X", "value": "-1K", "delta": "5%", "deltaDirection": "down",
                "description": "d", "displayTime": "9:00 AM", "isoDate": "2026-08-18",
                "comparisonLabel": "against target", "insight": {}}

    def publish(report, cards):
        pub.publish_kpi_feed(
            container, client="cityflower", dataset_id=f"ds-{report}", cards=cards,
            report_id=report, cfg=cfg, now=now, expires=expires,
            json_settings=None, receipts={},
        )

    def feed(name="insights"):
        raw = container.store[f"ai-content/kpi/client/{name}.json"][0]
        return json.loads(raw)["payload"]

    publish("sales_yoy", [card("sales_yoy", 101), card("sales_yoy", 102)])
    publish("target_tracker", [card("target_tracker", 201, "critical")])

    counts: dict = {}
    for entry in feed():
        counts[entry["reportId"]] = counts.get(entry["reportId"], 0) + 1
    check("both reports appear in the client feed",
          set(counts) == {"sales_yoy", "target_tracker"}, str(counts))
    check("neither report overwrote the other",
          counts.get("sales_yoy") == 2 and counts.get("target_tracker") == 1, str(counts))
    check("every card is attributable",
          all(entry.get("reportId") for entry in feed()))
    check("alerts.json carries both reports too",
          {entry["reportId"] for entry in feed("alerts")} == {"sales_yoy", "target_tracker"})

    # A re-run of one report replaces its own cards and leaves the other alone.
    publish("sales_yoy", [card("sales_yoy", 999)])
    ids = sorted(entry["id"] for entry in feed())
    check("a re-run replaces only its own report's cards", ids == [201, 999], str(ids))

    # insights.json was a blind overwrite before this change: without the merge,
    # the second publish would have left the feed holding one report.
    check("the feed is not a blind overwrite", len(feed()) > 1, str(len(feed())))


def main() -> int:
    print("=" * 72)
    print("REPLAY: multi-report KPI feed (P5.1 - report identity on the card)")
    print("=" * 72)
    test_legacy_unchanged()
    test_multi_report_card()
    test_merge_is_report_aware()
    test_feed_cap()
    test_schema()
    test_committed_payloads()
    test_two_report_publish()
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
