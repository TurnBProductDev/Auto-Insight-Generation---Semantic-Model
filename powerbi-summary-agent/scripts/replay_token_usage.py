"""Token accounting: what a run cost, per node, without ever breaking the run.

    python scripts/replay_token_usage.py

Offline - no auth, no LLM, no network.

Nothing in this pipeline recorded token usage, so "what does a run cost, and
which node spent it" could only be answered by correlating billing metrics
against container-job execution windows after the fact. `src/tools/token_usage.py`
records it at the point of use instead, into `token_usage.json` beside the
other artifacts.

Accounting is a *subordinate* concern, and this file exists to keep it that
way. Three properties, in descending order of how badly they hurt if wrong:

1. **It can never break a run.** A recorder that raises takes down the report
   it was only supposed to describe. Every entry point swallows its own
   exceptions, and this asserts that against a provider payload deliberately
   built to be hostile.
2. **Cached tokens are counted separately.** They bill at a tenth of the
   uncached rate. A total that folds them together cannot be priced at all -
   it is not a rounding error, it is the difference between a real number and
   a made-up one.
3. **It never holds the model's output.** The record is integers and labels.
   A cost file that quietly accumulated draft prose would be an exfiltration
   surface sitting in every client's output folder.

Plus the thing that makes the file useful rather than merely safe: the label
must name the *node*, not the factory that built the model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import token_usage  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs_replay" / "token_usage"

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


class FakeMessage:
    def __init__(self, usage=None, metadata=None):
        self.usage_metadata = usage
        self.response_metadata = metadata or {}


class FakeGeneration:
    def __init__(self, message):
        self.message = message


class FakeResult:
    """Shaped like a LangChain LLMResult, which is what the recorder reads."""

    def __init__(self, llm_output=None, generations=None):
        self.llm_output = llm_output
        self.generations = generations or []


# ------------------------------------------------- 1. it can never break a run


def test_nothing_here_can_raise() -> None:
    print("\n=== accounting never takes the pipeline down with it ===")
    token_usage.reset()

    recorder = token_usage.UsageRecorder("dax_generator", "gpt-5.4")

    class Hostile:
        """Every attribute access explodes - the worst a provider could do."""

        def __getattr__(self, name):
            raise RuntimeError(f"provider blew up reading {name}")

    try:
        recorder.on_llm_end(Hostile())
        raised = None
    except Exception as exc:  # noqa: BLE001
        raised = exc
    check("a provider payload that raises on every access is swallowed",
          raised is None, raised)

    for payload in (None, "", 0, [], {"token_usage": "not a dict"},
                    FakeResult(llm_output={"token_usage": None}),
                    FakeResult(generations=[[None]])):
        try:
            recorder.on_llm_end(payload)
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = exc
        check(f"an unusable payload does not propagate ({type(payload).__name__})",
              ok, locals().get("detail", ""))

    # record() is the other public entry point, and is called directly by the
    # recorder; junk in must not become an exception out.
    for counts in ({}, {"prompt": "nine"}, {"prompt": None, "completion": None}):
        try:
            token_usage.record("node", "gpt-5.4", counts)
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, exc
        check(f"record() survives junk counts ({counts})", ok,
              locals().get("detail", ""))

    check("and none of that was recorded as a call",
          token_usage.summary()["total"]["calls"] == 0,
          token_usage.summary()["total"])

    # An unwritable destination must not raise either - dump() is registered
    # with atexit, and an exception there fires after the report is written.
    check("dumping to an impossible path returns None rather than raising",
          token_usage.dump(str(PROJECT_ROOT / "no" / "such" / "dir" / "x.json"))
          is None)


# --------------------------------------------- 2. cached tokens are priceable


def test_cached_tokens_are_separate() -> None:
    print("\n=== cached tokens bill at a tenth and are counted apart ===")
    token_usage.reset()

    token_usage.record("insight_investigator", "gpt-5.4",
                       {"prompt": 100_000, "cached": 80_000, "completion": 1_000})
    call = token_usage.summary()["calls"][0]

    check("the cached count is kept, not folded into the prompt total",
          call["prompt_tokens"] == 100_000 and call["cached_tokens"] == 80_000, call)

    rates = token_usage.RATES["gpt-5.4"]
    expected = (20_000 * rates["in"] + 80_000 * rates["cached"]
                + 1_000 * rates["out"]) / 1_000_000.0
    check("cost prices the cached share at the cached rate",
          abs(call["usd"] - round(expected, 6)) < 1e-9,
          f"got {call['usd']}, expected {round(expected, 6)}")

    # The whole point: folding them together overstates the bill. Assert the
    # gap is real, so a regression that drops the distinction is visible.
    naive = (100_000 * rates["in"] + 1_000 * rates["out"]) / 1_000_000.0
    check("and that is materially cheaper than pricing it all as uncached",
          call["usd"] < naive * 0.75, f"{call['usd']} vs naive {naive}")

    # A provider reporting more cached than prompt tokens is nonsense; clamp
    # rather than compute a negative uncached charge.
    token_usage.reset()
    token_usage.record("node", "gpt-5.4",
                       {"prompt": 1_000, "cached": 9_000, "completion": 10})
    clamped = token_usage.summary()["calls"][0]
    check("cached is clamped to prompt, so cost can never go negative",
          clamped["cached_tokens"] == 1_000 and clamped["usd"] > 0, clamped)


def test_rates_resolve_per_deployment() -> None:
    print("\n=== a per-node cheaper model is priced as that model ===")
    token_usage.reset()

    token_usage.record("insight_signal_detector", "gpt-5.4-mini",
                       {"prompt": 1_000_000, "cached": 0, "completion": 0})
    token_usage.record("fresh_summary_generator", "gpt-5.4",
                       {"prompt": 1_000_000, "cached": 0, "completion": 0})
    by_node = token_usage.summary()["by_node"]

    check("the mini deployment is priced at the mini rate",
          abs(by_node["insight_signal_detector"]["usd"]
              - token_usage.RATES["gpt-5.4-mini"]["in"]) < 1e-6, by_node)
    check("the flagship is priced at the flagship rate",
          abs(by_node["fresh_summary_generator"]["usd"]
              - token_usage.RATES["gpt-5.4"]["in"]) < 1e-6, by_node)
    check("routing a node to the cheaper model shows up as a real saving",
          by_node["insight_signal_detector"]["usd"]
          < by_node["fresh_summary_generator"]["usd"])

    # A dated or suffixed deployment name must not silently fall back to the
    # flagship rate and overstate a mini node's cost by more than 3x.
    token_usage.reset()
    token_usage.record("n", "gpt-5.4-mini-2026-05-01",
                       {"prompt": 1_000_000, "cached": 0, "completion": 0})
    check("a suffixed deployment name still resolves to its own family",
          abs(token_usage.summary()["total"]["usd"]
              - token_usage.RATES["gpt-5.4-mini"]["in"]) < 1e-6,
          token_usage.summary()["total"])

    token_usage.reset()
    token_usage.record("n", "some-unknown-deployment",
                       {"prompt": 1_000, "cached": 0, "completion": 0})
    check("an unrecognised deployment is priced at the flagship rate, not zero",
          token_usage.summary()["total"]["usd"] > 0)


# ------------------------------------------------- 3. it holds no model output


def test_the_record_holds_no_prose() -> None:
    print("\n=== the record is integers and labels, never model output ===")
    token_usage.reset()

    secret = "CONFIDENTIAL DRAFT: revenue fell 51.98% at branch CFH017"
    recorder = token_usage.UsageRecorder("insight_synthesizer", "gpt-5.4")
    recorder.on_llm_end(FakeResult(
        llm_output={"token_usage": {"prompt_tokens": 500,
                                    "completion_tokens": 200},
                    "text": secret},
        generations=[[FakeGeneration(FakeMessage(
            usage={"input_tokens": 500, "output_tokens": 200}))]]))

    blob = json.dumps(token_usage.summary())
    check("the usage was recorded", token_usage.summary()["total"]["calls"] == 1)
    check("and the model's text is nowhere in the record", secret not in blob)
    check("no free-text field leaked in at all",
          "CONFIDENTIAL" not in blob and "CFH017" not in blob)

    allowed = {"node", "deployment", "prompt_tokens", "cached_tokens",
               "completion_tokens", "usd", "at"}
    check("a call record carries only the accounting fields",
          set(token_usage.summary()["calls"][0]) == allowed,
          set(token_usage.summary()["calls"][0]))


# ----------------------------------------------------- the label names the node


def test_the_label_names_the_calling_node() -> None:
    print("\n=== the label names the node, not the factory ===")

    # caller_label reads the module name off the calling frame, so the label
    # can only be tested from a frame that has a realistic module name. This
    # replay itself runs as `__main__`, which caller_label deliberately skips
    # (otherwise every label would be `main`), so build the real two-frame
    # chain instead: a node calls llm.get_llm, which calls caller_label.
    def _frame_in(module_name: str, body: str, closure: dict):
        namespace = {"__name__": module_name, **closure}
        exec(compile(body, f"<{module_name}>", "exec"), namespace)  # noqa: S102
        return namespace["fn"]

    factory = _frame_in(
        "src.tools.llm",
        "def fn():\n    return token_usage.caller_label()\n",
        {"token_usage": token_usage})
    node = _frame_in(
        "src.agents.dax_generator",
        "def fn():\n    return factory()\n",
        {"factory": factory})

    check("the label names the node that asked for the model",
          node() == "dax_generator", node())

    # The two frames it must walk past are its own and the factory's. If it
    # stopped at either, every node in the run would be labelled identically
    # and the per-node cost breakdown - the entire point of the file - would
    # be a single meaningless row.
    check("it never returns the factory's own name",
          node() not in ("llm", "token_usage"), node())

    deep = _frame_in(
        "src.agents.insight_investigator",
        "def fn():\n    return factory()\n",
        {"factory": factory})
    check("a different node gets a different label", deep() == "insight_investigator",
          deep())

    check("an unreachable frame degrades to 'unknown' rather than raising",
          token_usage.caller_label(skip=999) == "unknown")

    token_usage.reset()
    token_usage.record("dax_generator", "gpt-5.4", {"prompt": 10, "completion": 5})
    token_usage.record("dax_generator", "gpt-5.4", {"prompt": 20, "completion": 5})
    token_usage.record("insight_investigator", "gpt-5.4",
                       {"prompt": 1_000_000, "completion": 5})
    data = token_usage.summary()

    check("calls are grouped under the node that made them",
          data["by_node"]["dax_generator"]["calls"] == 2
          and data["by_node"]["insight_investigator"]["calls"] == 1, data["by_node"])
    check("nodes are ordered by spend, so the biggest is first",
          list(data["by_node"])[0] == "insight_investigator", list(data["by_node"]))
    check("the totals add up across nodes",
          data["total"]["calls"] == 3
          and data["total"]["prompt_tokens"] == 1_000_030, data["total"])


def test_the_dump() -> None:
    print("\n=== the file lands beside the other artifacts ===")
    token_usage.reset()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / "token_usage.json"
    target.unlink(missing_ok=True)

    check("a run that called no model writes nothing at all",
          token_usage.dump(str(target)) is None and not target.exists())

    token_usage.record("dax_planner", "gpt-5.4", {"prompt": 1_000, "completion": 100})
    written = token_usage.dump(str(target))
    check("a run that called a model writes the file", written and target.exists())

    data = json.loads(target.read_text(encoding="utf-8"))
    check("the file carries the total, the per-node split and the calls",
          {"total", "by_node", "calls"} <= set(data), sorted(data))
    check("the totals in the file match the in-memory summary",
          data["total"] == token_usage.summary()["total"])

    # set_dump_path names the run's own output folder, so a client's cost sits
    # with that client's report rather than in a shared location.
    token_usage.set_dump_path(str(OUT_DIR / "run_folder"))
    second = token_usage.dump()
    check("set_dump_path targets the run's output folder",
          second is not None and second.endswith("token_usage.json")
          and "run_folder" in second, second)
    check("an empty output folder is ignored rather than writing to the root",
          token_usage.set_dump_path("") is None)

    token_usage.reset()
    check("reset clears the accumulated records",
          token_usage.summary()["total"]["calls"] == 0)


def main() -> int:
    print("=" * 72)
    print("Token accounting: safe, priceable, and free of model output")
    print("=" * 72)

    test_nothing_here_can_raise()
    test_cached_tokens_are_separate()
    test_rates_resolve_per_deployment()
    test_the_record_holds_no_prose()
    test_the_label_names_the_calling_node()
    test_the_dump()

    print("\n" + "=" * 72)
    if _failures:
        print(f"TOKEN USAGE FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
