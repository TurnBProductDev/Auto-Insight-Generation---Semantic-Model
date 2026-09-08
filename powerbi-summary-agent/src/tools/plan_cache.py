"""Reuse the query plan across runs instead of re-deriving it every morning.

Three of the pipeline's LLM nodes - `report_understanding`, `dax_planner` and
`dax_generator` - read the semantic model's *structure*, not its rows. Nothing
about today's data reaches them. So on a model whose schema has not changed,
they produce the same understanding, the same plan and the same DAX they
produced yesterday, at full price, every single run.

This caches that work and keys it on the only things that can invalidate it.

What the key covers, and why each part is in it:

* ``dataset_id`` / ``report_id`` - two reports over one model are different
  plans; two models are obviously different plans.
* **the model's shape** - table, column and measure names and types. This is
  the real invalidation signal: a renamed column makes yesterday's DAX wrong,
  and the plan must be rebuilt. Values are deliberately *not* in the key -
  data changing daily is the whole point of the pipeline, and keying on it
  would make the cache never hit.
* **the business rules** - they are injected into these prompts and change
  what the model is told to do.
* **the prompt files** - editing a prompt is meant to change the output.
* ``PLAN_CACHE_VERSION`` - lets a code change to the node itself invalidate
  every stored plan at once.

Two safety properties matter more than the saving:

1. **A cached plan is still validated.** The cache short-circuits the three
   LLM nodes, never `dax_validator` or `scope_validator`. A stale plan that
   no longer matches the model is rejected exactly as a freshly generated bad
   plan would be - the safety net is unchanged.
2. **A plan that stops working is dropped.** `record_execution` deletes the
   entry when the executed success rate falls below a floor, so the next run
   re-plans instead of failing the same way forever. A silently-wrong report
   is worse than an expensive one, so there is also a hard age limit
   regardless of whether anything looks broken.

Off by default (``plan_cache_enabled``), so a config that predates this
reproduces the previous behaviour exactly.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Bump to invalidate every stored plan after changing what these nodes emit.
PLAN_CACHE_VERSION = "1"

#: Prompts whose content participates in the key.
_PROMPT_FILES = (
    "_global_rules.md",
    "report_understanding_prompt.md",
    "dax_planner_prompt.md",
    "dax_generator_prompt.md",
)

#: Below this share of queries executing successfully, the plan is dropped.
MIN_SUCCESS_RATE = 0.6

SLOTS = ("report_understanding", "dax_plan", "generated_dax")


def enabled(state: dict) -> bool:
    return bool(state.get("plan_cache_enabled"))


def _root(state: dict) -> Path:
    configured = state.get("plan_cache_folder") or "outputs/.runtime/plan_cache"
    root = Path(str(configured))
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return root


def _shape(metadata: Any) -> Any:
    """The structural fingerprint of the model: names and types, never values.

    Walks the metadata generically rather than assuming a layout, so a change
    to how metadata is assembled does not silently produce a constant key.
    """
    if isinstance(metadata, dict):
        return {k: _shape(v) for k, v in sorted(metadata.items())
                if k not in ("rows", "sample", "sample_rows", "values")}
    if isinstance(metadata, list):
        return [_shape(v) for v in metadata]
    if isinstance(metadata, (str, int, float, bool)) or metadata is None:
        return metadata
    return str(metadata)


def _prompt_digest() -> str:
    h = hashlib.sha256()
    for name in _PROMPT_FILES:
        path = PROJECT_ROOT / "prompts" / name
        try:
            h.update(path.read_bytes())
        except Exception:
            h.update(b"<missing>")
        h.update(b"\x00")
    return h.hexdigest()[:16]


def cache_key(state: dict) -> str:
    """Stable identity for "the plan this model and rulebook imply"."""
    payload = {
        "v": PLAN_CACHE_VERSION,
        "dataset": str(state.get("dataset_id") or ""),
        "report": str(state.get("report_id") or "sales_yoy"),
        "shape": _shape(state.get("model_metadata")),
        "rules": hashlib.sha256(
            (state.get("business_rules") or "").encode("utf-8")).hexdigest()[:16],
        "prompts": _prompt_digest(),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _path(state: dict, key: str) -> Path:
    return _root(state) / f"{key}.json"


def load(state: dict) -> Optional[Dict[str, Any]]:
    """Return the stored plan, or None when absent, stale or unreadable.

    Any problem reading the cache returns None - the pipeline then does the
    full work, which is the correct failure direction.
    """
    if not enabled(state):
        return None
    try:
        key = cache_key(state)
        path = _path(state, key)
        if not path.exists():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        # `or 7` would be wrong here: the guard below and the config catalogue
        # both document 0 as "never expire", and `0 or 7` quietly restores the
        # seven-day limit the operator just turned off.
        configured_age = state.get("plan_cache_max_age_days")
        max_age = int(7 if configured_age is None else configured_age)
        age_days = (time.time() - float(entry.get("saved_at", 0))) / 86400.0
        if max_age > 0 and age_days > max_age:
            return None
        if not any(entry.get(slot) for slot in SLOTS):
            return None
        entry["age_days"] = round(age_days, 2)
        entry["key"] = key
        return entry
    except Exception:
        return None


def save(state: dict, **slots: Any) -> None:
    """Merge slots into the stored plan for this key. Never raises."""
    if not enabled(state):
        return
    try:
        key = cache_key(state)
        path = _path(state, key)
        entry: Dict[str, Any] = {}
        if path.exists():
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                entry = {}
        for name, value in slots.items():
            if name in SLOTS and value is not None:
                entry[name] = value
        entry["saved_at"] = time.time()
        entry["dataset_id"] = state.get("dataset_id")
        entry["report_id"] = state.get("report_id")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def record_execution(state: dict, succeeded: int, attempted: int) -> Optional[str]:
    """Drop the cached plan when it stops producing working queries.

    Returns a reason when the plan was invalidated, else None. Called after
    execution, so a plan that has quietly drifted out of step with the model
    costs at most one degraded run rather than every run thereafter.
    """
    if not enabled(state) or not state.get("plan_cache_hit"):
        return None
    try:
        if attempted <= 0:
            return None
        rate = succeeded / float(attempted)
        if rate >= MIN_SUCCESS_RATE:
            return None
        path = _path(state, cache_key(state))
        if path.exists():
            path.unlink()
        return (f"cached plan dropped: only {succeeded}/{attempted} queries executed "
                f"({rate:.0%} < {MIN_SUCCESS_RATE:.0%}); next run will re-plan")
    except Exception:
        return None
