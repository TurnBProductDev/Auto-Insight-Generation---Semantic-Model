"""Every model-written draft a writer rejected, and the checker's own reasons.

The narrated Sales YoY summary cost three calls on 2026-09-11 where one should
have done: `fresh_summary_generator._invoke` rejected two drafts and resent the
whole conversation each time. The rejection reasons went nowhere - not the run
log, not an artifact - so nobody could say what the model kept getting wrong,
and the obvious fixes (relax the check, raise the retry count) were the two
that must not be made.

This records, per writer, each attempt's outcome, the validator's errors
verbatim, and that call's tokens from `token_usage`, into
``summary_authoring_attempts.json`` beside the other artifacts. It is purely
observational: nothing reads it back, and no writer's behaviour depends on it.

Rules, both load-bearing:

* **It can never break a run.** Every entry point swallows its own exceptions.
* **It is thread-safe.** Key Insights narration runs in the insight branch at
  the same time as the summary writers run in theirs, and both merge into the
  one file.

The first record a process makes for a given file replaces whatever an earlier
run left there, so a reused output folder never mixes two runs' attempts.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List

from . import token_usage

FILENAME = "summary_authoring_attempts.json"
SCHEMA_VERSION = 1

_LOCK = threading.Lock()
_STARTED: set = set()


def _calls(label: str) -> List[Dict[str, Any]]:
    try:
        return [call for call in token_usage.summary()["calls"] if call.get("node") == label]
    except Exception:
        return []


def mark(label: str) -> int:
    """How many calls ``label`` has made so far; pass to `usage_since`."""
    return len(_calls(label))


def usage_since(label: str, since: int) -> Dict[str, Any]:
    """Tokens and cost of the calls ``label`` made after ``since``.

    Counting by label is safe because no label is ever used by two concurrent
    calls: the summary writers run one after another in their branch, Key
    Insights runs alone in the other, and the KPI cards run after the graph.
    """
    total = {"calls": 0, "prompt_tokens": 0, "cached_tokens": 0,
             "completion_tokens": 0, "usd": 0.0}
    for call in _calls(label)[since:]:
        total["calls"] += 1
        for key in ("prompt_tokens", "cached_tokens", "completion_tokens"):
            total[key] += int(call.get(key) or 0)
        total["usd"] = round(total["usd"] + float(call.get("usd") or 0.0), 6)
    return total


def record(state: dict, writer: str, entry: Dict[str, Any]) -> None:
    """Append one writer's entry to this run's attempts file. Never raises.

    Needs an explicit ``output_folder``: a stand-alone caller that names none
    (an offline replay handing a bare config) is skipped rather than writing
    into the repository's default ``outputs/``.
    """
    try:
        folder = (state or {}).get("output_folder")
        if not folder:
            return
        from . import file_io

        path = file_io.output_path(state, FILENAME)
        key = str(path.resolve())
        with _LOCK:
            data: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "writers": {}}
            if key in _STARTED and path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict) and isinstance(loaded.get("writers"), dict):
                        data = loaded
                except Exception:
                    pass
            _STARTED.add(key)
            data["writers"].setdefault(writer, []).append(entry)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                            encoding="utf-8")
    except Exception:
        pass


def reset() -> None:
    """Forget which files this process has started (offline replays only)."""
    with _LOCK:
        _STARTED.clear()
