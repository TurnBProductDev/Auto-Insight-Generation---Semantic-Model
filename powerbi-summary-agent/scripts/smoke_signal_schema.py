"""One-call live check for the insight signal structured-output schema."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.insight_signal_detector import SignalList  # noqa: E402
from src.main import build_initial_state, load_config  # noqa: E402
from src.tools.llm import get_llm  # noqa: E402


def main() -> None:
    cfg = load_config(PROJECT_ROOT / "config" / "config.json")
    state = build_initial_state(cfg)
    state["max_tokens"] = 300
    state["config"]["llm_max_retries"] = 0
    llm = get_llm(state, structured_schema=SignalList)
    result = llm.invoke([
        {
            "role": "system",
            "content": "Return exactly one signal matching the response schema.",
        },
        {
            "role": "user",
            "content": (
                "Candidate cand_01: revenue rose by 10 for segment A. "
                "Use evidence query q1 and ask what drove the increase."
            ),
        },
    ])
    if not isinstance(result, SignalList) or len(result.signals) != 1:
        raise SystemExit("Structured signal response did not validate.")
    print("Azure OpenAI SignalList structured-output smoke test passed.")


if __name__ == "__main__":
    main()
