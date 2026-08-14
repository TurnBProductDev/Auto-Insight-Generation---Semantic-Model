"""The four WP0 fixture models: loadable, internally consistent, and pinned.

    python scripts/replay_fixture_models.py

Offline: no auth, no LLM, no network. WP0 deliverable 3 of the domain-verticals
programme. These synthetic models are what let WP4-WP7 be built and tested
without a live inventory connection.

Three jobs
----------
1. **Structure** - every fixture is referentially sound: measures and columns
   live on declared tables, relationships join real columns, a sort_by_column
   names a real sibling, and the derived index fields agree with the columns
   they summarise. A fixture that has quietly gone inconsistent tests nothing.

2. **Pinned profiler verdict** - what ``semantic_profiler.build_profile``
   actually makes of each model today. This is the "before" picture the kernel
   work is measured against.

3. **Blockers, asserted deliberately** - the checks marked ``BLOCKER`` below
   assert behaviour that is WRONG and known to be wrong. They are here so the
   defect is documented in executable form rather than in prose, and so that
   fixing it in WP2/WP4/WP9 produces a failure here that says exactly what to
   update. **A BLOCKER check failing is progress, not a regression** - read its
   message and re-pin it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import semantic_profiler  # noqa: E402

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "models"
EXPECTED = ("stock_snapshot", "ageing_bucket", "retail_yoy", "target_attainment")

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in detail.splitlines():
            print(f"         {line}")
    _failures.append(label)


def blocker(label: str, condition: bool, when_fixed: str) -> None:
    """A check that pins known-wrong behaviour. Failure here means it got fixed."""
    if condition:
        print(f"  [PASS] BLOCKER pinned: {label}")
        return
    print(f"  [FAIL] BLOCKER changed: {label}")
    print(f"         This behaviour was wrong and is pinned so the fix is visible.")
    print(f"         If you just fixed it: {when_fixed}")
    _failures.append(f"BLOCKER {label}")


def load(name: str) -> dict:
    path = FIXTURE_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- structure


def check_structure(name: str, model: dict) -> None:
    print(f"\n--- {name}: structure ---")

    required = ("tables", "columns", "measures", "relationships",
                "date_fields", "numeric_fields", "categorical_fields", "counts")
    missing = [key for key in required if key not in model]
    check("every top-level key present", not missing, f"missing: {missing}")

    table_names = {t["name"] for t in model["tables"]}
    columns = model["columns"]
    by_table: dict[str, set[str]] = {}
    for column in columns:
        by_table.setdefault(column["table"], set()).add(column["column"])

    orphan_cols = sorted({c["table"] for c in columns} - table_names)
    check("every column belongs to a declared table", not orphan_cols,
          f"undeclared tables: {orphan_cols}")

    orphan_measures = sorted({m["table"] for m in model["measures"]} - table_names)
    check("every measure belongs to a declared table", not orphan_measures,
          f"undeclared tables: {orphan_measures}")

    dupe_cols = [f"{t}[{c}]" for t, cols in by_table.items() for c in cols
                 if [x["column"] for x in columns if x["table"] == t].count(c) > 1]
    check("no duplicate column definitions", not dupe_cols, f"duplicates: {dupe_cols}")

    measure_names = [m["name"] for m in model["measures"]]
    dupes = sorted({n for n in measure_names if measure_names.count(n) > 1})
    check("no duplicate measure names", not dupes, f"duplicates: {dupes}")

    broken_rels = []
    for rel in model["relationships"]:
        for side in ("from", "to"):
            table, column = rel[f"{side}_table"], rel[f"{side}_column"]
            if column not in by_table.get(table, set()):
                broken_rels.append(f"{table}[{column}]")
    check("every relationship joins real columns", not broken_rels,
          f"unresolved: {broken_rels}")

    bad_sort = []
    for column in columns:
        target = column.get("sort_by_column")
        if target and target not in by_table.get(column["table"], set()):
            bad_sort.append(f"{column['table']}[{column['column']}] -> {target}")
    check("every sort_by_column names a real sibling column", not bad_sort,
          f"unresolved: {bad_sort}")

    # The derived index fields are a summary of the columns; they must agree.
    def refs(category: str) -> list[str]:
        return sorted(f"{c['table']}[{c['column']}]" for c in columns
                      if c["category"] == category)

    for category, key in (("date", "date_fields"), ("numeric", "numeric_fields"),
                          ("categorical", "categorical_fields")):
        check(f"{key} matches the {category} columns",
              sorted(model[key]) == refs(category),
              f"declared {len(model[key])}, columns give {len(refs(category))}")

    counts = model["counts"]
    check("counts match the collections they count",
          counts == {"tables": len(model["tables"]), "columns": len(columns),
                     "measures": len(model["measures"]),
                     "relationships": len(model["relationships"])},
          f"declared {counts}")


# --------------------------------------------------------------- stock snapshot


def check_stock_snapshot() -> None:
    model = load("stock_snapshot")
    check_structure("stock_snapshot", model)
    profile = semantic_profiler.build_profile(model)
    roles = profile["measure_roles"]

    print("\n--- stock_snapshot: profiler verdict (WP4 target) ---")

    # The headline: a snapshot model does not resolve at all today. Worth being
    # precise about how total the failure is - with no primary bundle there is
    # no fact table, and with no fact table the dimension walk has no origin,
    # so the model yields zero dimensions. Not "ranks badly": nothing at all.
    check("no primary value bundle resolves",
          profile["primary_value_bundle"] is None)
    check("fact table is unresolved", profile["fact_table"] == "")
    check("and so NO dimensions resolve at all",
          profile["dimensions"] == [] and profile["time_dimensions"] == [],
          f"dimensions={len(profile['dimensions'])} "
          f"time={len(profile['time_dimensions'])}")
    check("no entity dimension resolves", profile["entity_dimension"] is None)
    check("the warning names the missing current+prior value family",
          any("current+prior" in w for w in profile["warnings"]),
          f"warnings={profile['warnings']}")

    print("\n--- stock_snapshot: the semi-additive blocker ---")

    # Non-negotiable 11: a semi-additive measure must never be summed across
    # snapshots. Today metadata cannot tell the safe measure from the unsafe one.
    blocker("a LASTNONBLANK semi-additive measure is marked additive",
            roles["Stock Units on Hand"]["additive_candidate"] is True,
            "AggregationClass should classify it SEMI_ADDITIVE_LAST; re-pin this "
            "to assert the new classification instead.")
    blocker("a plain SUM across snapshots is marked additive identically",
            roles["Stock Units Naive Sum"]["additive_candidate"] is True,
            "verify() should now refuse this measure; assert the refusal here.")
    check("metadata alone cannot distinguish the two - same verdict, "
          "opposite correctness",
          roles["Stock Units on Hand"]["additive_candidate"]
          == roles["Stock Units Naive Sum"]["additive_candidate"])

    print("\n--- stock_snapshot: vocabulary and phase hazards ---")

    # _FAMILY_TOKENS has no stock vocabulary, and "value" is a revenue token.
    blocker("stock value is classified as the revenue family",
            roles["Stock Value on Hand"]["family"] == "revenue",
            "the inventory domain's families.py should own this; re-pin to the "
            "new family name.")
    blocker("stock units is classified as the quantity family",
            roles["Stock Units on Hand"]["family"] == "quantity",
            "re-pin to the inventory domain's own vocabulary.")

    # Found while building this fixture: a ratio measure earns a phase from an
    # incidental English word in its description, and can then stand in as the
    # bundle's current measure. Here it loses only because a non-ratio
    # candidate exists - remove that and Days Cover becomes primary.
    days_cover = roles["Days Cover"]
    blocker("a ratio measure is given phase=current by the word 'current' "
            "appearing in its DESCRIPTION",
            days_cover["phase"] == "current" and days_cover["ratio_like"] is True,
            "phase detection should not read free prose, or should not admit a "
            "ratio to a value bundle at all.")
    check("it is admitted to a value bundle (family is not 'margin')",
          days_cover["family"] != "margin",
          f"family={days_cover['family']} - the bundle filter only excludes 'margin'")

    revenue_bundle = next(b for b in profile["measure_bundles"]
                          if b["family"] == "revenue")
    check("a non-ratio candidate outranks it while one exists",
          revenue_bundle["measures"].get("current") == "Stock Value Current Snapshot",
          f"current={revenue_bundle['measures'].get('current')}")

    # Prove the near-miss, so the risk is recorded rather than assumed.
    thinned = json.loads(json.dumps(model))
    thinned["measures"] = [m for m in thinned["measures"]
                           if m["name"] != "Stock Value Current Snapshot"]
    thinned_bundle = next(
        b for b in semantic_profiler.build_profile(thinned)["measure_bundles"]
        if b["family"] == "revenue")
    blocker("remove that one measure and the RATIO becomes the current measure",
            thinned_bundle["measures"].get("current") == "Days Cover",
            "a ratio can no longer occupy a value slot; re-pin accordingly.")


# ---------------------------------------------------------------- ageing bucket


def check_ageing_bucket() -> None:
    model = load("ageing_bucket")
    check_structure("ageing_bucket", model)
    profile = semantic_profiler.build_profile(model)

    print("\n--- ageing_bucket: profiler verdict (WP5 target) ---")

    # Brief 1.6: Ageing HAS a comparison, so the existing signed-change
    # ranking blend applies unchanged. That is why it ships before stock health.
    primary = profile["primary_value_bundle"]
    check("a primary value bundle resolves", primary is not None)
    check("it carries all three phases",
          primary and sorted(primary["measures"]) == ["change", "current", "prior"],
          f"measures={primary and sorted(primary['measures'])}")
    check("the movement is therefore a signed change, needing no new blend",
          primary and "change" in primary["measures"])
    check("a volume driver resolves alongside it",
          [b["id"] for b in profile["volume_driver_bundles"]]
          == ["FACT_STOCK_AGEING::quantity"],
          f"drivers={[b['id'] for b in profile['volume_driver_bundles']]}")
    check("an entity dimension resolves",
          (profile["entity_dimension"] or {}).get("reference")
          == "'DIM_STORE'[STORE_NAME]",
          f"entity={(profile['entity_dimension'] or {}).get('reference')}")
    check("no warnings", profile["warnings"] == [], f"{profile['warnings']}")

    print("\n--- ageing_bucket: the ordinal axis (WP5) ---")

    columns = {(c["table"], c["column"]): c for c in model["columns"]}
    bucket = columns[("DIM_AGE_BUCKET", "AGE_BUCKET")]
    check("the bucket label is sorted by an explicit integer, not alphabetically",
          bucket["sort_by_column"] == "AGE_BUCKET_SORT")
    check("the sort key is numeric, so order and adjacency are derivable",
          columns[("DIM_AGE_BUCKET", "AGE_BUCKET_SORT")]["category"] == "numeric")
    check("explicit day bounds are present, so a bucket definition need not "
          "be guessed",
          ("DIM_AGE_BUCKET", "AGE_BUCKET_LOWER_DAYS") in columns
          and ("DIM_AGE_BUCKET", "AGE_BUCKET_UPPER_DAYS") in columns)
    check("a receipt date is present, so the derived-bucket variant of Q4 is "
          "also testable",
          ("FACT_STOCK_AGEING", "RECEIPT_DATE") in columns)

    # The ordinal axis is discoverable, but nothing consumes ordinality yet.
    bucket_dims = [d for d in profile["dimensions"] if d["table"] == "DIM_AGE_BUCKET"]
    blocker("the age bucket is ranked as an ordinary categorical dimension, "
            "with no notion of order",
            all("order" not in d and "ordinal" not in d for d in bucket_dims),
            "buckets.py now models an ordinal axis; assert the ordering metadata "
            "the profile carries.")

    print("\n--- ageing_bucket: semi-additive still applies ---")
    roles = profile["measure_roles"]
    blocker("the ageing measures are semi-additive but marked additive",
            roles["Ageing Value Current"]["additive_candidate"] is True,
            "re-pin to SEMI_ADDITIVE_LAST once WP4 classifies it.")
    check("a 'higher is worse' share measure is present for RAG direction "
          "testing",
          roles["Share of Value Over 90 Days"]["ratio_like"] is True)


# ------------------------------------------------------------------- retail yoy


def check_retail_yoy() -> None:
    model = load("retail_yoy")
    check_structure("retail_yoy", model)
    profile = semantic_profiler.build_profile(model)

    print("\n--- retail_yoy: profiler verdict (today's behaviour) ---")

    primary = profile["primary_value_bundle"]
    check("the primary bundle is the revenue family",
          primary and primary["family"] == "revenue")
    check("it carries all three phases",
          primary and sorted(primary["measures"]) == ["change", "current", "prior"])
    check("the fact table resolves",
          profile["fact_table"] == "FACT_SALES_MONTHLY",
          f"fact={profile['fact_table']}")
    check("the entity dimension resolves to the store name",
          (profile["entity_dimension"] or {}).get("reference")
          == "'DIM_STORE'[STORE_NAME]")
    check("both volume drivers resolve, quantity ahead of transactions",
          [b["family"] for b in profile["volume_driver_bundles"]]
          == ["quantity", "transactions"],
          f"{[b['family'] for b in profile['volume_driver_bundles']]}")
    check("no warnings", profile["warnings"] == [], f"{profile['warnings']}")

    print("\n--- retail_yoy: prior reconstructed from a change measure ---")

    # The live model publishes bills CURRENT and bills growth but no
    # bills-prior. R6's lever scan depends on prior = current - change.
    bills = next(b for b in profile["measure_bundles"]
                 if b["family"] == "transactions")
    check("the transactions family has current and change but no prior measure",
          sorted(bills["measures"]) == ["change", "current"],
          f"measures={sorted(bills['measures'])}")
    check("so a prior is derived rather than read",
          "prior" in bills["derived"], f"derived={sorted(bills['derived'])}")
    check("and the derived expression is current minus change",
          bills["derived"]["prior"]["expression"]
          == "[Net Bills Current] - [Bills Growth]",
          f"expression={bills['derived']['prior']['expression']}")

    print("\n--- retail_yoy: the R5 role vocabulary ---")

    from src.tools import summary_roles

    available = {c["column"].lower() for c in model["columns"]}
    for level in ("division_name", "department_name", "section_name", "category_name"):
        check(f"{level} is present for hierarchy-depth testing", level in available)
    check("'section' is a known hierarchy level at depth 25",
          summary_roles.HIERARCHY_LEVELS.get("section") == 25,
          f"section={summary_roles.HIERARCHY_LEVELS.get('section')}")
    check("'store' is deliberately NOT a hierarchy level",
          "store" not in summary_roles.HIERARCHY_LEVELS,
          "store is orthogonal to merchandise; a depth would make diversity "
          "rules treat it as an ancestor")


# -------------------------------------------------------------- target tracker


def check_target_attainment() -> None:
    model = load("target_attainment")
    check_structure("target_attainment", model)
    profile = semantic_profiler.build_profile(model)
    roles = profile["measure_roles"]

    print("\n--- target_attainment: profiler verdict (WP9 target) ---")

    # A target is a BASELINE, not a value. Today there is no such concept: the
    # only vocabulary a measure role has is the current/prior/change triple, so
    # a target has nowhere to go but into one of those slots.
    role_keys = set(roles["Revenue Target"])
    blocker("a measure role carries no baseline/target concept at all",
            not (role_keys & {"baseline", "baseline_role", "target", "spine",
                              "aggregation_class"}),
            "a baseline role now exists on the measure record; assert its value "
            "here instead of its absence.")
    check("the only role vocabulary available is the phase triple",
          roles["Revenue Target"]["phase"] in ("current", "prior", "change"),
          f"phase={roles['Revenue Target']['phase']!r} - a target has been "
          f"forced into a period phase")

    # Found while building this fixture: the phase came from the word "this" in
    # the description. Its sibling, worded differently, gets no phase at all.
    blocker("'Revenue Target' is classified phase=current because its "
            "DESCRIPTION contains the word 'this'",
            roles["Revenue Target"]["phase"] == "current",
            "phase detection no longer reads free prose; re-pin.")
    blocker("'Quantity Target' - same kind of measure, different wording - "
            "gets NO phase",
            roles["Quantity Target"]["phase"] is None,
            "targets are recognised structurally now; re-pin both to the same "
            "verdict.")
    check("so two target measures are classified inconsistently, on prose alone",
          roles["Revenue Target"]["phase"] != roles["Quantity Target"]["phase"])

    print("\n--- target_attainment: the derived prior coincidence ---")

    actual = next(b for b in profile["measure_bundles"]
                  if b["source_table"] == "FACT_SALES_ACTUAL"
                  and b["family"] == "revenue")
    check("the actuals bundle has current and change, no prior",
          sorted(actual["measures"]) == ["change", "current"],
          f"measures={sorted(actual['measures'])}")
    check("a prior is therefore derived as actual minus variance",
          actual["derived"]["prior"]["expression"]
          == "[Revenue Actual] - [Revenue Variance vs Target]",
          f"expression={actual['derived']['prior']['expression']}")
    # actual - (actual - target) == target. The derived "prior" IS the target,
    # so attainment silently reads as a period-over-period comparison.
    blocker("that derived 'prior' is arithmetically the TARGET, so attainment "
            "masquerades as a prior period",
            "Variance" in actual["derived"]["prior"]["expression"],
            "the spine now labels the baseline 'the agreed target'; re-pin to "
            "the spine's baseline_label.")

    check("a separate target bundle also resolves, competing with the actuals",
          any(b["source_table"] == "FACT_SALES_TARGET"
              for b in profile["measure_bundles"]))
    check("an attainment ratio is present for WP9's pct() to be tested against",
          roles["Revenue Attainment Pct"]["ratio_like"] is True)


def main() -> int:
    print("=" * 72)
    print("WP0 fixture models")
    print("=" * 72)

    if not FIXTURE_DIR.is_dir():
        print(f"[FAIL] fixture directory missing: {FIXTURE_DIR}")
        return 1

    found = sorted(path.stem for path in FIXTURE_DIR.glob("*.json"))
    print(f"\n--- inventory ---")
    check(f"all four fixture models present", sorted(EXPECTED) == found,
          f"expected {sorted(EXPECTED)}\nfound    {found}")
    for name in EXPECTED:
        if name not in found:
            print(f"[FAIL] cannot continue without {name}.json")
            return 1
        try:
            load(name)
        except (ValueError, OSError) as exc:
            print(f"[FAIL] {name}.json is not loadable: {exc}")
            return 1
    print(f"  [PASS] every fixture parses as JSON")

    check_stock_snapshot()
    check_ageing_bucket()
    check_retail_yoy()
    check_target_attainment()

    print("\n" + "=" * 72)
    if _failures:
        print(f"FIXTURE MODELS FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        print("\nA check labelled BLOCKER failing means known-wrong behaviour")
        print("changed. If you fixed it, re-pin that check to the new verdict.")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
