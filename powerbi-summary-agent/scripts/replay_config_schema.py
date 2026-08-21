"""Offline replay: the config schema is the single source of truth.

The failure this guards against is not a crash. Two hundred keys are read as
``state.get(key, default)`` across ~40 modules, and a key missing from a config
does not error - it silently changes behaviour. That is exactly how R4 and R6
stayed off in production while the code implementing them shipped. A UI that
carries its own copy of the key list would make that worse, not better.

So this test asserts the catalogue and the code cannot drift apart:

* every config key any module reads is in the schema
* every key any committed config sets is in the schema
* every schema default matches the literal fallback the code uses
* ``build_initial_state`` emits exactly the schema's ``in_state`` keys
* no key is documented as configurable while being unreachable from a config
* the role vocabulary matches ``summary_roles``

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import config_schema  # noqa: E402
from src.main import build_initial_state  # noqa: E402
from src.tools import summary_roles  # noqa: E402

FAILURES: list[str] = []

#: State keys that are computed rather than configured, so they are correctly
#: absent from the catalogue.
NON_CONFIG_STATE_KEYS = {
    "config",
    "config_path",
    "logs",
    "errors",
    "insight_memory_root",
    "summary_memory_root",
}

CONFIG_FILES = (
    "config/config.json",
    "config/config.example.json",
    "config/scanb/config.json",
    "config/sbmart-yoy/config.json",
    "config/sbmart-targettracker/config.json",
    "config/experiment/config.json",
)


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Source scanning
# ---------------------------------------------------------------------------


def _literal(node: ast.AST):
    try:
        return True, ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return False, None


def scan_source() -> tuple[dict[str, str], dict[str, list[tuple[str, object]]], set[str]]:
    """Return (config-key reads, ``state.get`` literal defaults, all mentions).

    A "config-key read" is any ``cfg.get("k")``, ``config.get("k")``,
    ``state["config"].get("k")`` or ``state.get("config", {}).get("k")`` - the
    four shapes the codebase actually uses to reach a configured value.

    "Mentions" is deliberately loose - every string constant appearing anywhere
    in ``src/`` - because a key can legitimately be reached as ``state["k"]``,
    inside a comprehension, or through a helper that takes the name as an
    argument. It answers only "is this key referenced at all", which is all the
    dead-key check needs.
    """
    config_reads: dict[str, str] = {}
    state_reads: dict[str, list[tuple[str, object]]] = {}
    mentions: set[str] = set()
    for path in sorted((PROJECT_ROOT / "src").rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        # The schema describes what the PIPELINE reads. src/services and src/api
        # are consumers of the catalogue, not readers of config keys, so their
        # own bookkeeping fields must not be mistaken for configuration.
        if path.name == "config_schema.py" or rel.startswith(("src/services/", "src/api/")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                mentions.add(node.value)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                mentions.add(node.target.id)  # SummaryAgentState field declarations
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "get" or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            key = first.value
            base = node.func.value
            via_chain = (
                isinstance(base, ast.Call)
                and isinstance(base.func, ast.Attribute)
                and base.func.attr == "get"
                and base.args
                and isinstance(base.args[0], ast.Constant)
                and base.args[0].value == "config"
            )
            via_subscript = (
                isinstance(base, ast.Subscript)
                and isinstance(base.slice, ast.Constant)
                and base.slice.value == "config"
            )
            via_name = getattr(base, "id", None) in {"cfg", "config"}
            if via_chain or via_subscript or via_name:
                config_reads.setdefault(key, f"{rel}:{node.lineno}")
            elif getattr(base, "id", None) == "state":
                ok, default = _literal(node.args[1]) if len(node.args) > 1 else (False, None)
                if ok:
                    state_reads.setdefault(key, []).append((f"{rel}:{node.lineno}", default))
    return config_reads, state_reads, mentions


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_code_coverage(config_reads: dict[str, str]) -> None:
    print("\nEvery config key the code reads is catalogued")
    required = {"tenant_id", "workspace_id", "dataset_id"}
    missing = sorted((set(config_reads) | required) - set(config_schema.BY_KEY))
    check(
        "no config key read by src/ is missing from the schema",
        not missing,
        "missing: " + str([f"{k} ({config_reads.get(k, 'main.py')})" for k in missing]),
    )


def test_committed_configs() -> None:
    print("\nEvery key in a committed config is catalogued")
    for name in CONFIG_FILES:
        path = PROJECT_ROOT / name
        if not path.exists():
            continue
        cfg = json.loads(path.read_text(encoding="utf-8"))
        unknown = config_schema.unknown_keys(cfg)
        check(f"{name} has no unknown keys", not unknown, f"unknown: {unknown}")
        problems = config_schema.type_errors(cfg)
        check(f"{name} matches the declared types", not problems, "; ".join(problems[:4]))


def test_defaults_match_code(state_reads: dict[str, list[tuple[str, object]]]) -> None:
    print("\nSchema defaults match the literal fallbacks in src/")
    mismatches: list[str] = []
    for entry in config_schema.KEYS:
        for where, default in state_reads.get(entry.key, []):
            same = default == entry.default or (
                isinstance(default, (int, float))
                and isinstance(entry.default, (int, float))
                and not isinstance(default, bool)
                and not isinstance(entry.default, bool)
                and float(default) == float(entry.default)
            )
            if not same:
                mismatches.append(f"{entry.key}: schema={entry.default!r} code={default!r} at {where}")
    check(
        "no state.get() fallback diverges from its schema default",
        not mismatches,
        "; ".join(mismatches[:4]),
    )


def test_reachability(
    state_reads: dict[str, list[tuple[str, object]]],
    config_reads: dict[str, str],
    mentions: set[str],
) -> None:
    print("\nNo key is documented as configurable but unreachable from a config")
    unreachable = [
        entry.key
        for entry in config_schema.KEYS
        if not entry.in_state and entry.key in state_reads and entry.key not in config_reads
    ]
    check(
        "every schema key is reachable from config.json",
        not unreachable,
        f"read from state but never copied out of the config: {unreachable}",
    )

    # The mirror image: a key the schema promises to put in state must be
    # referenced by the pipeline somewhere, or it is dead weight the UI would
    # invite someone to set for no effect.
    unread = [
        entry.key
        for entry in config_schema.KEYS
        if entry.in_state and not entry.dead and entry.key not in mentions
    ]
    check("every in_state key is referenced by src/", not unread, f"never referenced: {unread}")

    # Keys flagged dead really are dead - if one starts being read, un-flag it.
    resurrected = [
        entry.key
        for entry in config_schema.KEYS
        if entry.dead and (entry.key in config_reads or entry.key in state_reads)
    ]
    check("keys flagged dead are still unread", not resurrected, f"now read: {resurrected}")


def test_state_shape() -> None:
    print("\nbuild_initial_state emits exactly the schema's in_state keys")
    cfg = json.loads((PROJECT_ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    state = build_initial_state(cfg, "config/config.json")
    emitted = set(state) - NON_CONFIG_STATE_KEYS
    expected = {entry.key for entry in config_schema.KEYS if entry.in_state}
    check("state keys == schema in_state keys", emitted == expected,
          f"only in state: {sorted(emitted - expected)}; only in schema: {sorted(expected - emitted)}")

    # A config that sets nothing must behave exactly like the code defaults.
    bare = {"tenant_id": "t", "workspace_id": "w", "dataset_id": "d"}
    bare_state = build_initial_state(dict(bare), "")
    drifted = [
        entry.key
        for entry in config_schema.KEYS
        if entry.in_state
        and not entry.derived
        and not entry.required  # tenant/workspace/dataset come from the caller
        and bare_state[entry.key] != entry.default
    ]
    check("an empty config reproduces the schema defaults", not drifted, f"drifted: {drifted}")

    # Derived keys are the documented exceptions - assert each one explicitly so
    # a new derivation cannot be added silently.
    check("summary_focus_candidate_pool_per_role falls back to members_per_dimension",
          build_initial_state({**bare, "summary_focus_members_per_dimension": 7}, "")[
              "summary_focus_candidate_pool_per_role"] == 7)
    check("summary_focus_total_deep_dive_queries falls back to summary_focus_max_queries",
          build_initial_state({**bare, "summary_focus_max_queries": 9}, "")[
              "summary_focus_total_deep_dive_queries"] == 9)
    check("summary_memory_enabled is ANDed with fresh_summary_enabled",
          build_initial_state({**bare, "fresh_summary_enabled": False}, "")["summary_memory_enabled"] is False)
    check("summary_history_enabled is ANDed with fresh_summary_enabled",
          build_initial_state({**bare, "fresh_summary_enabled": False}, "")["summary_history_enabled"] is False)
    check("cloud memory storage never seeds from the local memory directory",
          build_initial_state({**bare, "insight_memory_storage": "azure_blob"}, "")[
              "insight_memory_root"] == "outputs/.runtime/insight_memory")


def test_vocabulary() -> None:
    print("\nRole vocabulary matches summary_roles")
    check("hierarchy roles match HIERARCHY_LEVELS",
          set(config_schema.HIERARCHY_ROLES) == set(summary_roles.HIERARCHY_LEVELS),
          f"{sorted(set(config_schema.HIERARCHY_ROLES) ^ set(summary_roles.HIERARCHY_LEVELS))}")
    check("coverage role default matches DEFAULT_COVERAGE_ROLES",
          config_schema.BY_KEY["summary_coverage_roles"].default == list(summary_roles.DEFAULT_COVERAGE_ROLES))
    check("coverage vocabulary is a superset of the hierarchy vocabulary",
          set(summary_roles.DEFAULT_COVERAGE_ROLES) <= set(config_schema.COVERAGE_ROLES))
    check("store is coverage-only and carries no hierarchy depth",
          "store" not in summary_roles.HIERARCHY_LEVELS and "store" in config_schema.COVERAGE_ROLES)


def test_metadata() -> None:
    print("\nCatalogue metadata is well formed")
    valid_types = {"bool", "int", "float", "string", "guid", "enum", "list", "object"}
    bad_type = [e.key for e in config_schema.KEYS if e.type not in valid_types]
    check("every key declares a known type", not bad_type, f"{bad_type}")

    bad_group = [e.key for e in config_schema.KEYS if e.group not in config_schema.GROUP_IDS]
    check("every key belongs to a wizard group", not bad_group, f"{bad_group}")

    no_help = [e.key for e in config_schema.KEYS if len(e.help.strip()) < 10]
    check("every key has help text", not no_help, f"{no_help}")

    # A plain label and a tier are what let the wizard show twenty questions
    # instead of two hundred, so neither may be forgotten on a new key.
    no_label = [e.key for e in config_schema.KEYS if len(e.label.strip()) < 3]
    check("every key has a plain-language label", not no_label, f"{no_label}")

    bad_tier = [e.key for e in config_schema.KEYS if e.tier not in config_schema.TIERS]
    check("every key declares a known tier", not bad_tier, f"{bad_tier}")

    essential = config_schema.tier_keys("essential")
    check("the essential set stays small enough to fill in", 15 <= len(essential) <= 45,
          f"{len(essential)} essential keys")
    check("nothing dead or experimental is marked essential",
          not [e.key for e in essential if e.dead])

    # The help text is read by someone who has never seen the codebase. Words
    # that only mean something inside it belong in `detail`.
    jargon = ("dax", "treatas", "topn", "semantic model", "state.get", "langgraph",
              "reducer", "superset of the focus", "coverage_kind", "story_key")
    leaked = [
        f"{e.key}:{word}" for e in config_schema.KEYS for word in jargon
        if word in e.help.lower()
    ]
    check("help text stays free of internal vocabulary", not leaked, f"{leaked[:5]}")

    # Every enum a person picks from needs readable option names.
    unlabelled = [
        e.key for e in config_schema.KEYS
        if e.type == "enum" and e.tier != "expert"
        and set(dict(e.choice_labels)) != set(e.choices)
    ]
    check("every non-expert enum names its options in plain words", not unlabelled,
          f"{unlabelled}")

    check("label() falls back to the key for something unknown",
          config_schema.label("not_a_key") == "not_a_key")
    check("label() gives the plain name for a real key",
          config_schema.label("azure_blob_prefix") == "Folder name inside the container")

    bad_enum = [e.key for e in config_schema.KEYS if e.type == "enum" and not e.choices]
    check("every enum declares its choices", not bad_enum, f"{bad_enum}")

    bad_default = [
        e.key
        for e in config_schema.KEYS
        if e.type == "enum" and e.choices and e.default not in e.choices
    ]
    check("every enum default is one of its choices", not bad_default, f"{bad_default}")

    check("defaults() round-trips through JSON",
          json.loads(json.dumps(config_schema.defaults())) == config_schema.defaults())
    check("to_json() is serialisable", isinstance(json.dumps(config_schema.to_json()), str))
    check("every group holds at least one key",
          all(config_schema.group_keys(g.id) for g in config_schema.GROUPS))
    check("the destructive-default traps are catalogued",
          {"azure_blob_prefix", "ai_content_client", "output_folder",
           "summary_r4_enabled", "summary_r6_enabled",
           "summary_dashboard_replaces_summary_html"}
          <= {e.key for e in config_schema.warned_keys()})


def test_coercion() -> None:
    print("\nForm values coerce to the declared types")
    check("bool from a checkbox string", config_schema.coerce("summary_r6_enabled", "true") is True)
    check("bool from 'off'", config_schema.coerce("summary_r6_enabled", "off") is False)
    check("int from text", config_schema.coerce("summary_focus_target_count", " 4 ") == 4)
    check("float stays int when the default is int",
          config_schema.coerce("summary_focus_override_change_pct", "20") == 20
          and isinstance(config_schema.coerce("summary_focus_override_change_pct", "20"), int))
    check("float stays float when the default is float",
          config_schema.coerce("insight_stat_z_cutoff", "2.5") == 2.5)
    check("list from a comma-separated string",
          config_schema.coerce("summary_coverage_roles", "store, division") == ["store", "division"])
    check("list from JSON", config_schema.coerce("insight_excluded_entities", '["A","B"]') == ["A", "B"])
    check("empty list text yields []", config_schema.coerce("insight_excluded_entities", "  ") == [])
    check("object from JSON",
          config_schema.coerce("summary_focus_role_aliases", '{"merch":"department"}')
          == {"merch": "department"})
    check("enum rejects an unknown choice",
          _raises(lambda: config_schema.coerce("ai_provider", "bedrock")))
    check("int rejects text", _raises(lambda: config_schema.coerce("summary_dashboard_tldr", "five")))
    check("bool rejects a bare int-like string is not silently truthy",
          config_schema.coerce("summary_r4_enabled", "0") is False)
    coerced, errors = config_schema.coerce_config({"summary_r6_enabled": "yes", "max_tokens": "8192"})
    check("coerce_config converts a whole submission",
          coerced == {"summary_r6_enabled": True, "max_tokens": 8192} and not errors)
    _, errors = config_schema.coerce_config({"max_tokens": "lots"})
    check("coerce_config reports rather than raises", len(errors) == 1)
    check("unknown keys pass through coercion untouched",
          config_schema.coerce("not_a_real_key", "x") == "x")


def test_schema_order() -> None:
    print("\nKey ordering is deterministic")
    keys = ["insight_stat_z_cutoff", "tenant_id", "zzz_unknown", "summary_r6_enabled"]
    ordered = config_schema.schema_order(keys)
    check("wizard order puts connection first and unknown keys last",
          ordered[0] == "tenant_id" and ordered[-1] == "zzz_unknown", f"{ordered}")
    check("ordering is stable", config_schema.schema_order(ordered) == ordered)


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:  # noqa: BLE001 - the point is that it refuses
        return True
    return False


def main() -> int:
    print("=" * 72)
    print("REPLAY: config schema is the single source of truth")
    print("=" * 72)
    config_reads, state_reads, mentions = scan_source()
    print(f"\nscanned src/: {len(config_reads)} config-key reads, "
          f"{len(state_reads)} state reads with literal defaults; "
          f"schema holds {len(config_schema.KEYS)} keys")
    test_code_coverage(config_reads)
    test_committed_configs()
    test_defaults_match_code(state_reads)
    test_reachability(state_reads, config_reads, mentions)
    test_state_shape()
    test_vocabulary()
    test_metadata()
    test_coercion()
    test_schema_order()
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
