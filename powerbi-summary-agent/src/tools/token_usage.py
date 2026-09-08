"""Per-call token accounting for every LLM node.

Nothing in this pipeline recorded token usage, so the only way to answer
"what does a run cost, and which node spent it" was to correlate Azure
Monitor metrics against container-job execution windows after the fact -
which cannot see inside a run, and arrives minutes late.

This records usage at the point of use instead. A recorder is attached to
every model built by ``llm.get_llm``; the label is the *calling module*
(``dax_generator``, ``insight_investigator``, ...), captured by walking one
frame out of the factory, so no node had to be edited to be counted.

Design rules, both load-bearing:

* **It can never break a run.** Every entry point swallows its own
  exceptions. Accounting that takes the pipeline down with it is worse than
  no accounting.
* **It never holds the model's output**, only integers. The records are
  written to ``token_usage.json`` beside the other artifacts, so a run's
  cost is auditable from the output folder alone.

Cached prompt tokens are recorded separately because they bill at a tenth
of the uncached rate - a total that folds them together cannot be priced.
"""

from __future__ import annotations

import atexit
import inspect
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - exercised only when langchain is installed
    from langchain_core.callbacks.base import BaseCallbackHandler
except Exception:  # pragma: no cover - keeps import safe in offline replays
    class BaseCallbackHandler:  # type: ignore[no-redef]
        pass


#: USD per 1M tokens, from the Azure retail price list (East US 2).
#: Used only to annotate the dumped record - billing is still the invoice.
RATES: Dict[str, Dict[str, float]] = {
    "gpt-5.4":       {"in": 2.50,  "cached": 0.25,   "out": 15.00},
    "gpt-5.4-mini":  {"in": 0.75,  "cached": 0.075,  "out": 4.50},
    "gpt-5.4-nano":  {"in": 0.20,  "cached": 0.02,   "out": 1.25},
}

_LOCK = threading.Lock()
_RECORDS: List[Dict[str, Any]] = []
_DUMP_PATH: Optional[Path] = None
_REGISTERED = False


def _rate(deployment: str) -> Dict[str, float]:
    """Rates for a deployment name, falling back to the flagship.

    Longest prefix wins, and that ordering is load-bearing: Azure deployment
    names routinely carry a date or revision suffix, and every one of them
    also starts with the flagship's name. Taking the first match in
    declaration order prices `gpt-5.4-mini-2026-05-01` as the flagship and
    overstates that node by more than 3x - on exactly the nodes this work
    moves to the cheaper model to save money.
    """
    key = (deployment or "").strip().lower()
    if key in RATES:
        return RATES[key]
    for name in sorted(RATES, key=len, reverse=True):   # 'gpt-5.4-mini-2' -> mini
        if key.startswith(name):
            return RATES[name]
    return RATES["gpt-5.4"]


def caller_label(skip: int = 2) -> str:
    """Module name of whoever asked for the model, e.g. ``dax_generator``.

    Walks out of this file and ``llm.py`` so the label names the node rather
    than the factory. Falls back to ``unknown`` rather than raising - a bad
    label is a cosmetic problem, an exception here is a broken run.
    """
    try:
        frame = inspect.currentframe()
        for _ in range(skip):
            if frame is None:
                break
            frame = frame.f_back
        seen = 0
        while frame is not None and seen < 12:
            name = frame.f_globals.get("__name__", "")
            short = name.rsplit(".", 1)[-1]
            if short not in ("llm", "token_usage", "__main__"):
                return short
            frame = frame.f_back
            seen += 1
    except Exception:
        pass
    return "unknown"


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _extract(payload: Any) -> Dict[str, int]:
    """Pull prompt/completion/cached counts out of a provider's usage blob.

    Providers disagree on the key names and on whether the blob is a dict or
    an object, and the cached count is nested a level deeper again. Anything
    unreadable becomes zero rather than an exception.
    """
    usage: Dict[str, Any] = {}
    if isinstance(payload, dict):
        usage = payload
    elif payload is not None:
        usage = getattr(payload, "__dict__", {}) or {}

    prompt = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _as_int(usage.get("completion_tokens") or usage.get("output_tokens"))

    cached = 0
    details = usage.get("prompt_tokens_details") or usage.get("input_token_details") or {}
    if not isinstance(details, dict):
        details = getattr(details, "__dict__", {}) or {}
    cached = _as_int(details.get("cached_tokens") or details.get("cache_read"))
    return {"prompt": prompt, "completion": completion, "cached": cached}


def record(label: str, deployment: str, counts: Dict[str, int]) -> None:
    """Append one call's usage. Never raises."""
    try:
        prompt = counts.get("prompt", 0)
        cached = min(counts.get("cached", 0), prompt)
        completion = counts.get("completion", 0)
        if not (prompt or completion):
            return
        rates = _rate(deployment)
        cost = ((prompt - cached) * rates["in"]
                + cached * rates["cached"]
                + completion * rates["out"]) / 1_000_000.0
        with _LOCK:
            _RECORDS.append({
                "node": label,
                "deployment": deployment,
                "prompt_tokens": prompt,
                "cached_tokens": cached,
                "completion_tokens": completion,
                "usd": round(cost, 6),
                "at": time.strftime("%H:%M:%S"),
            })
    except Exception:
        pass


class UsageRecorder(BaseCallbackHandler):
    """Attached to every model; records one entry per completed call."""

    def __init__(self, label: str, deployment: str) -> None:
        self.label = label
        self.deployment = deployment

    # LangChain hands back an LLMResult whose llm_output carries the usage.
    def on_llm_end(self, response: Any, **_: Any) -> None:  # noqa: D102
        try:
            out = getattr(response, "llm_output", None) or {}
            counts = _extract(out.get("token_usage") or out.get("usage"))
            if not (counts["prompt"] or counts["completion"]):
                # Structured-output calls sometimes carry usage on the message.
                for gens in (getattr(response, "generations", None) or []):
                    for gen in gens or []:
                        msg = getattr(gen, "message", None)
                        if msg is None:
                            continue
                        counts = _extract(getattr(msg, "usage_metadata", None))
                        if counts["prompt"] or counts["completion"]:
                            break
                        meta = getattr(msg, "response_metadata", None) or {}
                        counts = _extract(meta.get("token_usage"))
                        if counts["prompt"] or counts["completion"]:
                            break
            record(self.label, self.deployment, counts)
        except Exception:
            pass


def summary() -> Dict[str, Any]:
    """Totals overall and per node, cheapest thing to print at the end."""
    with _LOCK:
        records = list(_RECORDS)
    per_node: Dict[str, Dict[str, Any]] = {}
    total = {"calls": 0, "prompt_tokens": 0, "cached_tokens": 0,
             "completion_tokens": 0, "usd": 0.0}
    for r in records:
        node = per_node.setdefault(r["node"], {
            "calls": 0, "prompt_tokens": 0, "cached_tokens": 0,
            "completion_tokens": 0, "usd": 0.0, "deployment": r["deployment"]})
        for key in ("prompt_tokens", "cached_tokens", "completion_tokens"):
            node[key] += r[key]
            total[key] += r[key]
        node["calls"] += 1
        total["calls"] += 1
        node["usd"] = round(node["usd"] + r["usd"], 6)
        total["usd"] = round(total["usd"] + r["usd"], 6)
    return {"total": total,
            "by_node": dict(sorted(per_node.items(), key=lambda kv: -kv[1]["usd"])),
            "calls": records}


def set_dump_path(output_folder: str) -> None:
    """Point the end-of-run dump at this run's output folder."""
    global _DUMP_PATH, _REGISTERED
    try:
        if not output_folder:
            return
        _DUMP_PATH = Path(output_folder) / "token_usage.json"
        if not _REGISTERED:
            atexit.register(dump)
            _REGISTERED = True
    except Exception:
        pass


def dump(path: Optional[str] = None) -> Optional[str]:
    """Write the accounting to JSON. Safe to call more than once."""
    try:
        target = Path(path) if path else _DUMP_PATH
        if target is None:
            return None
        data = summary()
        if not data["total"]["calls"]:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(target)
    except Exception:
        return None


def reset() -> None:
    with _LOCK:
        _RECORDS.clear()
