"""Offline replay: the executive brief for the Web App's Home (Ver 4, PLAN 7b).

Asserts:

1. Off by default and off means off: the job reads and writes nothing.
2. Configuration: a malformed ``brief_reports`` fails visibly; the committed
   SB Mart brief config is catalogued, typed, and ships with the flag off.
3. Facts: each report's summary, cards and Top Insights land on its own fact
   sheet (by GUID for summaries, by slug for the feeds); a corrupt blob costs
   only itself; no-break spaces and minus signs read as plain text.
4. Selection: no summary, no line; most severe first, then how many findings
   share that severity, then configured order; the line cap.
5. Validation: a figure must be in its report's facts (as written, without
   separators or a zero fraction); names with digits are names; causes,
   forecasts, jargon, prior-year talk without a prior year, two sentences and
   long lines are refused; questions likewise, ending in one '?'.
6. Authoring with a stub model: a wrong number is sent back once, and a line
   that fails twice is replaced by the report's own headline; the
   deterministic tier and a failed call fall back without error; bad
   questions are dropped, never replaced.
7. End to end: the brief.json envelope, lines tagged with GUIDs, slug, name,
   rank and tone; questions tagged; nothing uploaded when app publishing is off.
8. The container routes AGENT_RUNNER=executive_brief to it, publishing.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.replay_highlights import _Service  # noqa: E402
from src.brief import author, facts, select, validate  # noqa: E402
from src.brief import publish as brief_publish  # noqa: E402
from src.brief import run as brief_run  # noqa: E402

FAILURES: list[str] = []
NOW = datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc)
DS_GUID = "6ddd2afa-0000-4000-8000-000000000001"
TT_GUID = "02e86e30-0000-4000-8000-000000000002"
YOY_GUID = "aafb8798-0000-4000-8000-000000000003"
AGE_GUID = "5a6e0000-0000-4000-8000-000000000004"
NBSP, MINUS = " ", "−"


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


# --- fixtures -----------------------------------------------------------------
DS_SUMMARY = {
    "title": "SB Mart Daily Sales", "generatedAt": "2026-09-14T06:10:00Z", "dataAsOf": "2026-09-13",
    "headline": f"Net Sales landed USD{NBSP}7.1K under the floor of its normal band, and "
                f"USD{NBSP}17.7K under the benchmark.",
    "metrics": [
        {"label": "Net Sales", "value": f"USD{NBSP}55.3K", "tone": "critical", "verdict": "Underperforming",
         "note": f"{MINUS}USD{NBSP}17.7K against the benchmark USD{NBSP}73.0K",
         "takeaway": "Below its normal range for 3 days in a row"},
        {"label": "Bills", "value": "4,353", "tone": "critical", "verdict": "Underperforming",
         "note": f"{MINUS}1,338 against the benchmark 5,691"},
        {"label": "Margin", "value": "22.23%", "tone": "info", "verdict": "In band",
         "note": "+0.50 points against the benchmark 21.73%"}],
    "sections": [{"heading": "What needs attention first", "tone": "critical", "points": [
        f"CONSUMER GOODS (department): USD{NBSP}26.3K vs 29.9K - {MINUS}USD{NBSP}3.6K below its normal band."]}],
}
TT_SUMMARY = {
    "title": "SB Mart Target Tracker", "generatedAt": "2026-09-14T06:20:00Z", "dataAsOf": "2026-08-27",
    "headline": "Today was 102.6% of target, but this month so far is still 1.21M below target at 92.0%.",
    "metrics": [
        {"label": "Today", "value": "102.6% of target", "tone": "positive", "verdict": "On target",
         "takeaway": "Back on target after 20 days below it"},
        {"label": "This month so far", "value": "92.0% of target", "tone": "critical",
         "verdict": "Below target"}],
    "sections": [{"heading": "Performance against target", "tone": "critical", "points": [
        "The month so far is 92.0% of target. With 4 days left the rest of the month needs 149.6% of plan."]}],
}
YOY_SUMMARY = {
    "title": "SB Mart Sales vs Previous Year", "generatedAt": "2026-09-14T05:50:00Z",
    "headline": "July 2026 revenue increased by +3.5M year on year across ST1, ST2, ST3, ST4 and ST5.",
    "metrics": [],
    "sections": [{"heading": "Overall Performance", "tone": "info", "points": [
        "For July 2026, across ST1, ST2, ST3, ST4 and ST5, revenue increased by +3.5M (9.3%), from 37.9M "
        "to 41.4M compared with the same period last year. Quantity increased by +1.3M (6.0%). "
        "Transactions changed by +859.7K."]}],
}
FEED = [
    {"id": 11, "reportId": "target_tracker", "severity": "critical", "rank": 1,
     "label": "Whole business — Sales against target", "value": "-1.21M", "delta": "", "deltaDirection": "down",
     "comparisonLabel": "against the remaining month target",
     "insight": {"title": "Month target now out of reach pace"}},
    {"id": 12, "reportId": "target_tracker", "severity": "critical", "rank": 2,
     "label": "Branch ST2 — Sales against target", "value": "-200.8K", "delta": "7.7%",
     "deltaDirection": "down", "comparisonLabel": "against its target for this month so far"},
    {"id": 13, "reportId": "target_tracker", "severity": "critical", "rank": 3,
     "label": "Branch ST1 — Sales against target", "value": "-180.2K", "delta": "8.7%",
     "deltaDirection": "down", "comparisonLabel": "against its target for this month so far"},
    {"id": 21, "reportId": "daily_sales", "severity": "critical", "metric": "SPICE MARKET", "value": "-33",
     "deltaDirection": "down", "comparisonLabel": "the normal bills band for SPICE MARKET on this weekday"},
    {"id": 31, "reportId": "sales_yoy", "severity": "positive", "rank": 1, "label": "ST5 — Revenue",
     "value": "+2.61M", "delta": "429.6%", "deltaDirection": "up", "comparison": {"label": "vs last year"}},
    {"id": 41, "reportId": "inventory_stock_health", "severity": "critical", "label": "Stock-outs",
     "value": "17,215"},
]
HIGHLIGHTS = [
    {"id": 1, "kind": "risk", "title": "Month target", "value": "149.6%",
     "comparisonLabel": "of plan needed on the 4 days left", "tone": "critical", "rank": 1,
     "reportIds": [TT_GUID], "reportSlug": "target_tracker"},
    {"id": 2, "kind": "riser", "title": "CONSUMER GOODS", "value": "+10.0%",
     "comparisonLabel": "division sales vs last year", "tone": "positive", "rank": 1,
     "reportIds": [YOY_GUID], "reportSlug": "sales_yoy"},
]


def _cfg(**over) -> dict:
    return {
        "azure_blob_account": "acct", "ai_content_client": "sb-mart", "dataset_id": "ds-1",
        "ai_content_publish_enabled": True, "ai_content_executive_brief": True,
        "report_ai_tier": "narrated", "brief_max_lines": 5, "brief_suggested_questions": 4,
        "brief_reports": [
            {"report_id": "daily_sales", "report_name": "SB Mart Daily Sales", "ai_content_report_ids": [DS_GUID]},
            {"report_id": "target_tracker", "report_name": "SB Mart Target Tracker",
             "ai_content_report_ids": [TT_GUID]},
            {"report_id": "sales_yoy", "report_name": "SB Mart Sales vs Previous Year",
             "ai_content_report_ids": [YOY_GUID]},
            {"report_id": "stock_age", "report_name": "SB Mart Stock Age", "ai_content_report_ids": [AGE_GUID]},
        ],
        **over,
    }


def _seed(svc: _Service, *, corrupt: tuple = ()) -> _Service:
    def put(name, payload):
        body = {"schemaVersion": 1, "client": "sb-mart", "payload": payload}
        data = b"{not json" if name in corrupt else json.dumps(body).encode("utf-8")
        svc.data["sb-mart"][name] = {"data": data, "etag": '"seed"'}

    put(facts.SUMMARY_BLOB.format(guid=DS_GUID), DS_SUMMARY)
    put(facts.SUMMARY_BLOB.format(guid=TT_GUID), TT_SUMMARY)
    put(facts.SUMMARY_BLOB.format(guid=YOY_GUID), YOY_SUMMARY)
    put(facts.FEED_BLOB, FEED)
    put(facts.HIGHLIGHTS_BLOB, HIGHLIGHTS)
    return svc


def _gathered(**over) -> list:
    svc = _seed(_Service())
    reports = facts.configured_reports(_cfg(**over))
    return facts.gather(svc.get_container_client("sb-mart"), reports, log=lambda *_: None)


class _StubLLM:
    """Returns scripted drafts in order; records every call's messages."""

    def __init__(self, *drafts):
        self.drafts = list(drafts)
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append([dict(m) for m in messages])
        draft = self.drafts.pop(0) if self.drafts else {"lines": [], "questions": []}
        if isinstance(draft, Exception):
            raise draft
        return author.BriefDraft(**draft)


GOOD_LINES = [
    {"report": "target_tracker",
     "text": "This month so far is at 92.0% of target, 1.21M below plan, although today reached 102.6%."},
    {"report": "daily_sales",
     "text": "Net Sales were USD 55.3K on Sunday 13 September, USD 17.7K under the benchmark, "
             "with Bills at 4,353 against 5,691."},
    {"report": "sales_yoy",
     "text": "July 2026 revenue rose 9.3% on last year to 41.4M, with ST5 adding 2.61M."},
]
GOOD_QUESTIONS = [
    {"report": "target_tracker", "text": "Which branches are furthest behind target this month?"},
    {"report": "daily_sales", "text": "Which departments fell below their normal range?"},
    {"report": "sales_yoy", "text": "Which stores grew most on last year?"},
    {"report": "daily_sales", "text": "How far were Bills from the benchmark of 5,691?"},
]


def _lines(**replace) -> list:
    return [dict(line, text=replace.get(line["report"], line["text"])) for line in GOOD_LINES]


# --- 1. off -------------------------------------------------------------------
def test_off() -> None:
    print("\n[1] Off by default, and off means off")
    from src import config_schema

    entry = config_schema.get("ai_content_executive_brief")
    check("ai_content_executive_brief is catalogued, default off", entry is not None and entry.default is False)
    svc = _seed(_Service())
    receipt = brief_run.run(_cfg(ai_content_executive_brief=False), publish=True, service_client=svc, now=NOW)
    check("flag off: skipped, nothing read, nothing written",
          receipt.get("status") == "skipped" and not svc.reads
          and brief_publish.BRIEF_BLOB not in svc.data["sb-mart"], str(receipt))


# --- 2. configuration ---------------------------------------------------------
def test_config() -> None:
    print("\n[2] Configuration")
    bad = brief_run.run(_cfg(brief_reports=[{"report_id": "daily_sales"}]), service_client=_Service(), now=NOW)
    check("an entry without report GUIDs fails visibly, naming it",
          bad.get("status") == "failed" and "ai_content_report_ids" in str(bad.get("error")), str(bad))
    twice = _cfg()
    twice["brief_reports"] = twice["brief_reports"][:1] * 2
    check("a report named twice fails visibly",
          brief_run.run(twice, service_client=_Service(), now=NOW).get("status") == "failed")
    check("no reports configured fails visibly",
          brief_run.run(_cfg(brief_reports=[]), service_client=_Service(), now=NOW).get("reason")
          == "brief_reports_missing")

    from src import config_schema

    path = PROJECT_ROOT / "config" / "sbmart-brief" / "config.json"
    shipped = json.loads(path.read_text(encoding="utf-8"))
    check("config/sbmart-brief has no uncatalogued key", not config_schema.unknown_keys(shipped),
          str(config_schema.unknown_keys(shipped)))
    check("config/sbmart-brief matches the declared types", not config_schema.type_errors(shipped),
          "; ".join(config_schema.type_errors(shipped)[:3]))
    check("config/sbmart-brief ships with the brief OFF (the owner turns it on, PLAN 9.3)",
          shipped.get("ai_content_executive_brief") is False)
    check("config/sbmart-brief names the three SB Mart reports with valid GUIDs",
          [r.slug for r in facts.configured_reports(shipped)] == ["daily_sales", "target_tracker", "sales_yoy"])


# --- 3. facts -----------------------------------------------------------------
def test_facts() -> None:
    print("\n[3] Facts")
    reports = {r.slug: r for r in _gathered()}
    ds, tt, yoy, age = reports["daily_sales"], reports["target_tracker"], reports["sales_yoy"], reports["stock_age"]
    check("each summary is read by its GUID", ds.headline.startswith("Net Sales landed")
          and tt.data_as_of == "2026-08-27" and yoy.headline.startswith("July 2026"))
    check("a report with no published summary has no summary", not age.has_summary)
    check("cards are attributed by slug; another report's card never leaks in",
          [c["id"] for c in tt.cards] == [11, 12, 13] and [c["id"] for c in ds.cards] == [21]
          and not any(c["id"] == 41 for r in reports.values() for c in r.cards))
    check("Top Insights are attributed by slug",
          [h["id"] for h in tt.highlights] == [1] and [h["id"] for h in yoy.highlights] == [2])
    sheet = ds.sheet()
    check("the sheet reads no-break spaces and minus signs as plain text",
          NBSP not in sheet and MINUS not in sheet and "-USD 17.7K against the benchmark USD 73.0K" in sheet)
    check("the sheet carries the headline, figures, context, findings and the date in words",
          "Headline: Net Sales landed" in sheet and "- Bills: 4,353 (Underperforming" in sheet
          and "Context:" in sheet and "[critical] SPICE MARKET: -33" in sheet
          and "Sunday 13 September 2026" in sheet, sheet)
    check("Top Insights reach the sheet", "Month target: 149.6% (of plan needed on the 4 days left)" in tt.sheet())
    check("context keeps the first two sentences of a point",
          "Quantity increased by +1.3M (6.0%)." in yoy.sheet() and "859.7K" not in yoy.sheet())

    svc = _seed(_Service(), corrupt=(facts.SUMMARY_BLOB.format(guid=DS_GUID),))
    survived = facts.gather(svc.get_container_client("sb-mart"), facts.configured_reports(_cfg()),
                            log=lambda *_: None)
    check("a corrupt summary costs only its own report",
          not survived[0].has_summary and survived[1].has_summary and survived[2].has_summary)


# --- 4. selection -------------------------------------------------------------
def test_select() -> None:
    print("\n[4] Selection")
    reports = _gathered()
    order = [r.slug for r in select.rank_reports(reports, 5)]
    check("no summary, no line", "stock_age" not in order)
    check("most severe first; more findings at that severity break the tie (TT 4 critical, DS 3)",
          order == ["target_tracker", "daily_sales", "sales_yoy"], str(order))
    check("tone is the most severe card or figure",
          [r.tone() for r in select.rank_reports(reports, 5)] == ["critical", "critical", "positive"])
    check("the line cap holds", [r.slug for r in select.rank_reports(reports, 2)] == ["target_tracker", "daily_sales"])


# --- 5. validation ------------------------------------------------------------
def test_validate() -> None:
    print("\n[5] Validation")
    reports = {r.slug: r for r in _gathered()}
    ds, tt, yoy = reports["daily_sales"].sheet(), reports["target_tracker"].sheet(), reports["sales_yoy"].sheet()
    for line in GOOD_LINES:
        errors = validate.validate_line(line["text"], reports[line["report"]].sheet())
        check(f"a grounded line passes ({line['report']})", not errors, str(errors))
    check("a figure not in the facts is refused",
          any("'91.5'" in e for e in validate.validate_line("The month so far is at 91.5% of target.", tt)))
    check("92% stands for 92.0%, 4353 for 4,353",
          not validate.validate_line("The month so far is at 92% of target.", tt)
          and not validate.validate_line("Bills reached 4353 against 5691.", ds))
    check("another report's figure is refused",
          bool(validate.validate_line("Net Sales were USD 55.3K.", tt)))
    check("a name with digits is a name (ST5), and an unknown one is refused (ST9)",
          not validate.validate_line("Revenue rose 9.3% with ST5 adding 2.61M.", yoy)
          and any("ST9" in e for e in validate.validate_line("Revenue rose 9.3% with ST9 adding 2.61M.", yoy)))
    check("a cause is refused", any("because" in e for e in validate.validate_line(
        "Net Sales were USD 55.3K because of the weather.", ds)))
    check("a forecast is refused", any("forecast" in e for e in validate.validate_line(
        "The month will finish below target at 92.0%.", tt)))
    check("prior-year talk is refused where the facts make no prior-year comparison",
          any("prior-year" in e for e in validate.validate_line("Net Sales were USD 55.3K, down on last year.", ds)))
    check("and allowed where they do", not validate.validate_line("Revenue rose 9.3% on last year to 41.4M.", yoy))
    check("two sentences are refused", bool(validate.validate_line(
        "The month so far is at 92.0% of target. Today reached 102.6%.", tt)))
    check("more than 35 words is refused", any("words" in e for e in validate.validate_line(
        " ".join(["target"] * 36), tt)))
    check("a word number must be a figure too ('three' days: 3 is in the facts, 'eleven' is not)",
          not validate.validate_line("Net Sales were below their normal range for three days in a row.", ds)
          and bool(validate.validate_line("Net Sales were below their normal range for eleven days.", ds)))
    check("a good question passes", not validate.validate_question(
        "Which branches are furthest behind target this month?", tt))
    check("a question must end in one '?'", bool(validate.validate_question("Which branches are behind target", tt)))
    check("a forecasting question is refused", bool(validate.validate_question("Will we reach the month target?", tt)))
    check("a question's figures come from its report", bool(validate.validate_question("Why did sales drop 12%?", ds)))


# --- 6. authoring -------------------------------------------------------------
def test_author() -> None:
    print("\n[6] Authoring with a stub model")
    selected = select.rank_reports(_gathered(), 5)
    quiet = lambda *_: None  # noqa: E731

    stub = _StubLLM({"lines": GOOD_LINES, "questions": GOOD_QUESTIONS})
    out = author.author(selected, _cfg(), llm=stub, log=quiet)
    check("valid drafts are used, in one call", len(stub.calls) == 1
          and all(v["mode"] == "llm" for v in out["lines"].values()), str(out["lines"]))
    check("valid questions are kept, up to the configured number",
          [q["text"] for q in out["questions"]] == [q["text"] for q in GOOD_QUESTIONS])
    check("the model is shown each report's key and facts",
          "## Report key: target_tracker" in stub.calls[0][1]["content"]
          and "Headline: Today was 102.6% of target" in stub.calls[0][1]["content"])

    wrong = _lines(target_tracker="This month so far is at 91.5% of target.")
    stub = _StubLLM({"lines": wrong, "questions": GOOD_QUESTIONS}, {"lines": GOOD_LINES, "questions": []})
    out = author.author(selected, _cfg(), llm=stub, log=quiet)
    check("a wrong number is sent back once with the reason",
          len(stub.calls) == 2 and "'91.5' is not a figure" in stub.calls[1][-1]["content"])
    check("and the corrected line is used", out["lines"]["target_tracker"]["mode"] == "llm"
          and "92.0%" in out["lines"]["target_tracker"]["text"])

    stub = _StubLLM({"lines": wrong, "questions": []}, {"lines": wrong, "questions": []})
    out = author.author(selected, _cfg(), llm=stub, log=quiet)
    check("wrong twice: the report's own headline stands in",
          out["lines"]["target_tracker"] == {"text": TT_SUMMARY["headline"], "mode": "headline"})
    check("the other reports keep their written lines",
          out["lines"]["daily_sales"]["mode"] == "llm" and out["lines"]["sales_yoy"]["mode"] == "llm")

    bad_questions = [{"report": "target_tracker", "text": "Will we reach the month target?"},
                     {"report": "inventory", "text": "Which items are out of stock?"},
                     {"report": "daily_sales", "text": "Why did sales drop 12%?"}]
    stub = _StubLLM({"lines": GOOD_LINES, "questions": bad_questions},
                    {"lines": GOOD_LINES, "questions": bad_questions})
    out = author.author(selected, _cfg(), llm=stub, log=quiet)
    check("bad questions are dropped, never replaced (the app keeps its defaults)", out["questions"] == [])

    stub = _StubLLM(RuntimeError("model unavailable"))
    out = author.author(selected, _cfg(), llm=stub, log=quiet)
    check("a failed call: every line is its report's headline, no questions, no error",
          all(v["mode"] == "headline" for v in out["lines"].values()) and out["questions"] == [])

    stub = _StubLLM({"lines": GOOD_LINES, "questions": GOOD_QUESTIONS})
    out = author.author(selected, _cfg(report_ai_tier="deterministic"), llm=stub, log=quiet)
    check("the deterministic tier never calls the model", not stub.calls
          and all(v["mode"] == "headline" for v in out["lines"].values()))


# --- 7. end to end ------------------------------------------------------------
def test_end_to_end() -> None:
    print("\n[7] End to end")
    svc = _seed(_Service())
    stub = _StubLLM({"lines": _lines(target_tracker="This month so far is at 91.5% of target."),
                     "questions": GOOD_QUESTIONS},
                    {"lines": _lines(target_tracker="This month so far is at 91.5% of target."),
                     "questions": []})
    with tempfile.TemporaryDirectory() as tmp:
        receipt = brief_run.run(_cfg(), publish=True, service_client=svc, now=NOW, llm=stub,
                                out_dir=Path(tmp), log=lambda *_: None)
        local = json.loads((Path(tmp) / "brief.json").read_text(encoding="utf-8"))
    check("the run succeeds and publishes", receipt.get("status") == "ok" and receipt.get("published") is True,
          str(receipt))
    stored = svc.data["sb-mart"].get(brief_publish.BRIEF_BLOB)
    body = json.loads(stored["data"]) if stored else {}
    brief = body.get("payload") or {}
    check("published in the v1 envelope, the same brief as the local copy",
          body.get("schemaVersion") == 1 and body.get("client") == "sb-mart" and brief == local)
    try:
        brief_publish.Brief(**brief)
        check("the payload validates against the contract (extra fields refused)", True)
    except Exception as exc:  # noqa: BLE001
        check("the payload validates against the contract (extra fields refused)", False, str(exc))
    lines = brief.get("lines") or []
    check("one line per report with a summary, in rank order",
          [(l["rank"], l["reportSlug"]) for l in lines]
          == [(1, "target_tracker"), (2, "daily_sales"), (3, "sales_yoy")], str(lines))
    check("lines are tagged with the report's GUIDs and name, and its tone",
          lines and lines[0]["reportIds"] == [TT_GUID] and lines[0]["reportName"] == "SB Mart Target Tracker"
          and [l["tone"] for l in lines] == ["critical", "critical", "positive"])
    check("the wrong-twice line is the report's headline; the receipt says so",
          lines and lines[0]["text"] == TT_SUMMARY["headline"]
          and receipt["lines"][0] == {"report": "target_tracker", "mode": "headline"})
    questions = brief.get("suggestedQuestions") or []
    check("questions carry their report's GUIDs",
          len(questions) == 4 and questions[0]["reportIds"] == [TT_GUID] and questions[2]["reportIds"] == [YOY_GUID])
    check("dataAsOf is the newest report date; generatedAt is the run",
          brief.get("dataAsOf") == "2026-09-13" and brief.get("generatedAt") == "2026-09-14T07:00:00Z")

    svc = _seed(_Service())
    receipt = brief_run.run(_cfg(ai_content_publish_enabled=False), publish=True, service_client=svc, now=NOW,
                            llm=_StubLLM({"lines": GOOD_LINES, "questions": []}), log=lambda *_: None)
    check("app publishing off: the brief is written locally only",
          receipt.get("status") == "ok" and receipt.get("published") is False
          and brief_publish.BRIEF_BLOB not in svc.data["sb-mart"])
    svc = _Service()
    receipt = brief_run.run(_cfg(), publish=True, service_client=svc, now=NOW, llm=_StubLLM(), log=lambda *_: None)
    check("nothing published yet by any report: skipped, nothing written",
          receipt.get("status") == "skipped" and brief_publish.BRIEF_BLOB not in svc.data["sb-mart"], str(receipt))
    down = _seed(_Service(fail_on=(brief_publish.BRIEF_BLOB,)))
    receipt = brief_run.run(_cfg(), publish=True, service_client=down, now=NOW,
                            llm=_StubLLM({"lines": GOOD_LINES, "questions": []}), log=lambda *_: None)
    check("a storage failure is a failed receipt, not a crash", receipt.get("status") == "failed", str(receipt))


# --- 8. container -------------------------------------------------------------
def test_container() -> None:
    print("\n[8] Container routing")
    from src import container_entrypoint as ce

    check("AGENT_RUNNER=executive_brief is a known runner", ce.RUNNERS.get("executive_brief") == "src.brief.run")
    seen: list = []
    original = brief_run.main
    brief_run.main = lambda argv=None: seen.append(list(argv or [])) or 0
    saved = os.environ.pop("AGENT_PUBLISH", None)
    try:
        rc = ce._run_standalone("executive_brief", Path("cfg.json"))
    finally:
        brief_run.main = original
        if saved is not None:
            os.environ["AGENT_PUBLISH"] = saved
    check("it runs the brief with the injected config, publishing",
          rc == 0 and seen == [["--config", "cfg.json", "--publish"]], str(seen))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps(_cfg(ai_content_executive_brief=False)), encoding="utf-8")
        check("a real run with the flag off exits 0 without touching Azure",
              brief_run.main(["--config", str(path), "--publish"]) == 0)


def main() -> int:
    print("=" * 72)
    print("REPLAY: executive brief (Web App Home Ver 4, PLAN 7b)")
    print("=" * 72)
    test_off()
    test_config()
    test_facts()
    test_select()
    test_validate()
    test_author()
    test_end_to_end()
    test_container()
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
