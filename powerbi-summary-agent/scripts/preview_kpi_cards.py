"""Re-author the KPI cards from saved signals and show what changed.

The replays prove the *code*: a level is not signed, a date is not a segment,
a summary quoting an invented figure is rejected. None of that can prove the
thing a reader actually complained about - that the sentences are vague and do
not sound like a person. Only a real model call can, and only against the real
signals.

So this takes the `insight_signals.json` a live run already wrote, calls the
LLM exactly as the pipeline does, and prints the result beside the card that
shipped. It is a preview: it reads saved files, writes into `outputs_preview/`,
and **publishes nothing**.

    # what the current prompt produces from the signals behind the live feed
    python scripts/preview_kpi_cards.py

    # ...beside what actually shipped to the client
    python scripts/preview_kpi_cards.py --live <insights.json>

    # A/B: same signals, same model, one prompt against another
    python scripts/preview_kpi_cards.py --prompt <other_prompt.md>

`--prompt` swaps the prompt file for the duration of the run only. Pair it with
the previous version of the file to see the change on its own:

    git show HEAD~1:powerbi-summary-agent/prompts/kpi_insights_generator_prompt.md > old.md
    python scripts/preview_kpi_cards.py --prompt old.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The signal sets behind the live SB Mart feed, in the order the client sees
# them. Each is written by its own runner at the end of a real run.
DEFAULT_SIGNALS = (
    "outputs_inventory/insight_signals.json",
    "outputs_sbmart_yoy/insight_signals.json",
    "outputs_sbmart_targettracker/insight_signals.json",
)
DEFAULT_CONFIGS = {
    "outputs_inventory": "config/inventory/config.json",
    "outputs_sbmart_yoy": "config/sbmart-yoy/config.json",
    "outputs_sbmart_targettracker": "config/sbmart-targettracker/config.json",
}
WIDTH = 88


def wrap(text: str, indent: int = 12, width: int = WIDTH) -> str:
    """Fold prose so a long summary stays readable in a terminal."""
    import textwrap
    pad = " " * indent
    body = textwrap.fill(str(text or ""), width=width - indent,
                         initial_indent="", subsequent_indent=pad)
    return body


def load_signals(paths) -> list:
    out = []
    for raw in paths:
        p = (ROOT / raw) if not Path(raw).is_absolute() else Path(raw)
        if not p.exists():
            print(f"  ! no signals at {raw} - skipped")
            continue
        signals = json.loads(p.read_text(encoding="utf-8"))
        cfg_name = DEFAULT_CONFIGS.get(p.parent.name)
        out.append((p, signals, cfg_name))
        print(f"  {len(signals):>2} signal(s) from {raw}")
    return out


def state_for(cfg_path: str | None, out_dir: Path) -> dict:
    """The same small state the runners build for the payload call."""
    cfg = {}
    if cfg_path and (ROOT / cfg_path).exists():
        cfg = json.loads((ROOT / cfg_path).read_text(encoding="utf-8"))
    return {
        "config": cfg,
        "ai_provider": cfg.get("ai_provider"),
        "model": cfg.get("model"),
        "max_tokens": cfg.get("max_tokens"),
        "report_id": cfg.get("report_id"),
        "ai_content_multi_report_feed": True,
        "ai_content_kpi_card_fields": cfg.get("ai_content_kpi_card_fields", False),
        "output_folder": str(out_dir),
    }


def use_prompt(path: str) -> None:
    """Serve an alternate prompt file for this process only.

    The prompt is read by name through `file_io.read_prompt`, so swapping it
    here leaves the repo untouched - an A/B must never depend on editing the
    file under test.
    """
    from src.tools import file_io
    replacement = Path(path)
    if not replacement.is_absolute():
        replacement = ROOT / path
    if not replacement.exists():
        raise SystemExit(f"no prompt file at {path}")
    body = replacement.read_text(encoding="utf-8")
    original = file_io.read_prompt

    def patched(name: str) -> str:
        if name == "kpi_insights_generator_prompt.md":
            return body
        return original(name)

    file_io.read_prompt = patched
    print(f"  prompt overridden with {path}")


def live_cards(path: str | None) -> dict:
    """What shipped, keyed by (reportId, segment)."""
    if not path:
        return {}
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / path
    if not p.exists():
        print(f"  ! no live feed at {path}")
        return {}
    blob = json.loads(p.read_text(encoding="utf-8"))
    cards = blob.get("payload", blob) if isinstance(blob, dict) else blob
    # The value disambiguates: two inventory cards share the segment
    # "All Locations", and keying on segment alone silently paired the Damage
    # card with the Excess card's text.
    return {(c.get("reportId"), c.get("metric"), c.get("value")): c for c in cards}


def show(card: dict, label: str) -> None:
    insight = card.get("insight") or {}
    print(f"    {label}")
    print(f"      title  : {insight.get('title', '')}")
    print(f"      summary: {wrap(insight.get('summary', ''), indent=15)}")
    for stat in insight.get("stats") or []:
        print(f"      stat   : {stat.get('label', ''):<34} {stat.get('value', '')}")
    print(f"      action : {wrap(insight.get('action', ''), indent=15)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signals", nargs="*", default=list(DEFAULT_SIGNALS))
    ap.add_argument("--config", default=None,
                    help="force one config for every signal set")
    ap.add_argument("--prompt", default=None,
                    help="use this prompt file instead of the committed one")
    ap.add_argument("--live", default=None,
                    help="a published insights.json to compare against")
    args = ap.parse_args()

    print("=" * WIDTH)
    print("PREVIEW: KPI cards re-authored from saved signals (publishes nothing)")
    print("=" * WIDTH)

    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv(ROOT / ".env")

    sets = load_signals(args.signals)
    if not sets:
        print("nothing to author")
        return 1
    if args.prompt:
        use_prompt(args.prompt)
    shipped = live_cards(args.live)

    out_dir = ROOT / "outputs_preview"
    out_dir.mkdir(exist_ok=True)
    from src.tools import api_payloads

    produced, fell_back = [], 0
    for path, signals, cfg_name in sets:
        state = state_for(args.config or cfg_name, out_dir)
        print()
        print("-" * WIDTH)
        print(f"{path.parent.name}   ({state.get('report_id')})")
        print("-" * WIDTH)
        try:
            cards = api_payloads.generate_kpi_insights_payload(signals, state)
        except Exception as exc:  # noqa: BLE001 - a preview reports, never raises
            print(f"  authoring FAILED: {type(exc).__name__}: {exc}")
            continue

        grounded_all = {
            api_payloads._sentence(
                api_payloads._lead_sentence(s, api_payloads._signal_family(s)))
            for s in signals
        } - {""}
        for card in cards:
            key = (card.get("reportId"), card.get("metric"), card.get("value"))
            print()
            print(f"  {card.get('metric') or '(no segment)'}   [{card.get('severity')}]"
                  f"   value {card.get('value')}")
            was = shipped.get(key)
            if was:
                show(was, "WAS (shipped)")
                print()
            show(card, "NOW")

            # Did the model's own summary survive, or did code replace it?
            if (card.get("insight") or {}).get("summary") in grounded_all:
                fell_back += 1
                print("      ^ summary was REPLACED by the grounded sentence "
                      "(the model wrote no usable figure)")
            produced.append(card)

    (out_dir / "kpi_cards_preview.json").write_text(
        json.dumps(produced, indent=2, default=str), encoding="utf-8")
    print()
    print("=" * WIDTH)
    print(f"{len(produced)} card(s) authored; {fell_back} fell back to the grounded sentence")
    print(f"written to outputs_preview/kpi_cards_preview.json  (nothing published)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
