"""Offline proof of the container's runner selection.

Three of the five reports sit outside the LangGraph pipeline and until now had
no container path at all - only a command line. `AGENT_RUNNER` gives them one
through the same image and the same injected secrets.

The property that matters most is the **default**: a job that sets no
`AGENT_RUNNER` must run exactly what it ran before this existed. Every deployed
job is in that state, so a regression here would silently change what every
scheduled run produces.

No Power BI, Azure or LLM credentials are required - the runner modules are
replaced with recorders, so nothing is actually produced.

    python scripts/replay_container_runner.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import container_entrypoint as ce  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _config_env(**extra) -> None:
    os.environ["AGENT_CONFIG_B64"] = base64.b64encode(
        json.dumps({"tenant_id": "t", "workspace_id": "w",
                    "dataset_id": "d"}).encode()).decode()
    for key in ("AGENT_RUNNER", "AGENT_PUBLISH", "AGENT_REPORT_ID"):
        os.environ.pop(key, None)
    for key, value in extra.items():
        os.environ[key] = value


def _recorder(module_name: str) -> list:
    calls: list = []
    fake = types.ModuleType(module_name)
    fake.main = lambda argv=None: calls.append(list(argv or [])) or 0
    sys.modules[module_name] = fake
    return calls


def test_default_is_unchanged() -> None:
    print("\nNo AGENT_RUNNER runs the pipeline, exactly as before")
    _config_env()
    graph_calls: list = []
    original = ce.agent_main
    ce.agent_main = lambda argv=None: graph_calls.append(list(argv or [])) or 0
    try:
        rc = ce.main()
    finally:
        ce.agent_main = original
    check("it returns cleanly", rc == 0)
    check("the pipeline was invoked", len(graph_calls) == 1, str(graph_calls))
    check("with only the config path, as before",
          graph_calls and graph_calls[0][0] == "--config"
          and len(graph_calls[0]) == 2, str(graph_calls))
    check("and no --publish is added to the pipeline path",
          "--publish" not in (graph_calls[0] if graph_calls else []),
          "the pipeline owns its own publishing decisions")


def test_report_id_still_threads() -> None:
    print("\nAGENT_REPORT_ID still reaches the pipeline")
    _config_env(AGENT_REPORT_ID="sales_yoy")
    calls: list = []
    original = ce.agent_main
    ce.agent_main = lambda argv=None: calls.append(list(argv or [])) or 0
    try:
        ce.main()
    finally:
        ce.agent_main = original
    check("--report is passed explicitly", "--report" in calls[0], str(calls))
    check("with the requested id", "sales_yoy" in calls[0], str(calls))


def test_standalone_runners() -> None:
    print("\nA named runner is invoked instead of the pipeline")
    for runner, module in (("inventory", "scripts.run_inventory"),
                           ("target_tracker", "scripts.run_target_tracker"),
                           ("ageing", "scripts.run_ageing"),
                           ("sku_overview", "scripts.run_sku_overview")):
        _config_env(AGENT_RUNNER=runner)
        calls = _recorder(module)
        graph: list = []
        original = ce.agent_main
        ce.agent_main = lambda argv=None: graph.append(1) or 0
        try:
            rc = ce.main()
        finally:
            ce.agent_main = original
        check(f"{runner}: the runner is invoked", len(calls) == 1, str(calls))
        check(f"{runner}: the pipeline is NOT invoked", not graph)
        check(f"{runner}: it returns cleanly", rc == 0)
        check(f"{runner}: it is given the injected config",
              calls and calls[0][0] == "--config"
              and calls[0][1].endswith("config.json"), str(calls))
        check(f"{runner}: a scheduled run publishes by default",
              "--publish" in calls[0], str(calls))


def test_publish_can_be_turned_off() -> None:
    print("\nPublishing can be suppressed for a dry run")
    _config_env(AGENT_RUNNER="inventory", AGENT_PUBLISH="0")
    calls = _recorder("scripts.run_inventory")
    ce.main()
    check("--publish is omitted", "--publish" not in calls[0], str(calls))


def test_unknown_runner_fails_loudly() -> None:
    print("\nAn unknown runner fails loudly, never silently")
    _config_env(AGENT_RUNNER="nonsense")
    graph: list = []
    original = ce.agent_main
    ce.agent_main = lambda argv=None: graph.append(1) or 0
    raised = ""
    try:
        ce.main()
    except SystemExit as exc:
        raised = str(exc)
    finally:
        ce.agent_main = original
    check("it raises", bool(raised), "a typo must not quietly run the pipeline")
    check("the message names the valid runners",
          "inventory" in raised and "target_tracker" in raised, raised[:80])
    check("and the pipeline did not run instead", not graph)


def test_graph_is_explicitly_selectable() -> None:
    print("\nAGENT_RUNNER=graph is the pipeline, stated explicitly")
    _config_env(AGENT_RUNNER="graph")
    calls: list = []
    original = ce.agent_main
    ce.agent_main = lambda argv=None: calls.append(list(argv or [])) or 0
    try:
        ce.main()
    finally:
        ce.agent_main = original
    check("the pipeline runs", len(calls) == 1, str(calls))
    check("and it is treated as the default, not as a standalone runner",
          "--publish" not in calls[0], str(calls))


def main() -> int:
    print("=" * 72)
    print("Container runner selection")
    print("=" * 72)
    try:
        test_default_is_unchanged()
        test_report_id_still_threads()
        test_standalone_runners()
        test_publish_can_be_turned_off()
        test_unknown_runner_fails_loudly()
        test_graph_is_explicitly_selectable()
    finally:
        for key in ("AGENT_CONFIG_B64", "AGENT_RUNNER", "AGENT_PUBLISH",
                    "AGENT_REPORT_ID"):
            os.environ.pop(key, None)
        # The entrypoint materialises the injected config on disk; it is not an
        # output of this replay and must not be left behind.
        runtime = PROJECT_ROOT / "outputs" / "runtime-config"
        for name in ("config.json",):
            (runtime / name).unlink(missing_ok=True)

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
