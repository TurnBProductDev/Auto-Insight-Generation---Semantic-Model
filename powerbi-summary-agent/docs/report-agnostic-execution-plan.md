# Report-Agnostic Agent — Architecture and Execution Plan

**Status:** proposal, not yet implemented.
**Scope:** turn the agent from *one hard-coded retail YoY report* into a *report engine* that
handles any retail report from configuration alone.
**Companion docs:** `config-ui.md` (what the UI does today), `config-ui-execution-plan.md`
(how it was built), `CLAUDE.md` / `AGENTS.md` (current architecture of record).

---

## PART 0 — Executive summary

### The finding

The agent is **not a general BI agent that happens to be configured for YoY**. It is a
**year-on-year comparison engine**, and the comparison is welded into the load-bearing
data structure rather than into a few prompts.

The atom of the whole pipeline is a three-phase measure triple — `(current, prior, change)`
— produced by `semantic_profiler.build_profile()`. Every layer above it consumes that
triple: scope classification, universe scans, materiality, coverage ranking, severity
bands, the three-lever spine, RAG verdicts, the dashboard, memory keys, the validators and
the prose rules. There are **~330 references to `prior`** across 30 modules, and they are
not decorative: `summary_materiality.area_change()` *is* `current − prior`, and
`summary_coverage.rank_scores()` is undefined without a signed percentage change.

The product already knows this about itself. `services/probe.py:248-257` refuses a model
outright with:

> "This dashboard has no measures that compare one period with the same period a year
> earlier, and that comparison is the whole basis of what this agent reports. […] A stock
> or inventory snapshot with only current balances cannot be used."

That message is accurate. It is also the exact wall this plan removes.

### The good news

Below the semantics, the *mechanism* is already report-agnostic and unusually well
factored for this kind of change:

| Already generic | Evidence |
|---|---|
| Auth, token reuse, concurrency contract | `powerbi_executor.py`, one pre-fork token |
| Metadata acquisition + measure-definition recovery | `metadata_reader.py`, Fabric TMSL enrichment |
| DAX assembly, validation, scope gating, repair | `summary_focus_queries.py`, `dax_validator.py`, `scope_validator.py` |
| Budgeted query execution + caching | `_run_query`, per-node budgets |
| Evidence contracts and provenance | `evidence_contract.py` |
| Ranking / normalization math | `summary_materiality.divide_by_max`, `summary_coverage.rank_scores` |
| Cross-run memory, novelty, rotation | `summary_memory.py`, `insight_memory.py` |
| Deterministic rendering (2 self-contained HTML docs) | `summary_visual.py`, `summary_dashboard_html.py` |
| Config catalogue + wizard + probe + validate + deploy | `config_schema.py`, `src/api/`, `src/services/` |
| Grounded prose validation with a passing fallback | `summary_validation.py` |

So this is **not a rewrite**. It is the extraction of four hard-coded semantic
decisions into declarative contracts, plus a report registry and a UI step.

### The four generalizations

| # | Today (hard-coded) | Target (declared) |
|---|---|---|
| **G1** | Comparison is `(current, prior, change)` | A **Comparison Model** plugin — period-over-period, actual-vs-target, snapshot-vs-threshold, ratio-vs-standard, composition, flow-balance |
| **G2** | 7 fixed retail-sales measure families, `revenue` priority 100 | A **KPI Registry**: id, kind (flow/stock/rate/count/duration), aggregation (incl. **semi-additive**), direction, unit, band set, spine bindings |
| **G3** | `HIERARCHY_LEVELS` = merchandise only; `store` special-cased in code | An **Axis Registry**: any number of axes with depth, kind (hierarchy/orthogonal/partner/time), focus-eligibility, coverage flag |
| **G4** | `Revenue = Transactions × Basket × Price` in `summary_levers.py` | A **Decomposition Registry** of declared identities with a `method` (sequential-multiplicative, additive, ratio) |

Plus two structural changes:

- **R** — a **Report Registry**: many reports per client (today: one config = one dataset = one report).
- **L** — **Layout & Rule Packs**: the R6 four-layer page and the R4 "Overall first" rule become data, not code.

### What stays hard-coded, forever

This distinction is the point of the whole exercise, so it is stated up front.

**Hard-coded agent capabilities** (never per-report): authentication and token lifecycle;
metadata scanning; DAX text assembly and the model guardrails (`TREATAS` not
`KEEPFILTERS`, always `TOPN`); validator and scope gate; query budgeting and caching;
reconciliation arithmetic; normalization and blended ranking *math*; memory transaction
semantics and atomic writes; LangGraph topology and the concurrency contract; HTML
rendering primitives; grounding checks (a quoted figure must exist in the model);
publishing destinations; the refusal to invent numbers, forecast, or assert cause.

**Configurable report levers** (per report): which KPIs, what they mean, how they
aggregate, which direction is good; what the baseline is and how to compute distance from
it; which axes exist and which earn narrative; which identities decompose which KPI; what
counts as material; what to exclude; the page skeleton; the vocabulary; the report's
business rulebook.

---

## PART 1 — Current-state assessment

### 1.1 How the agent works today

One LangGraph `StateGraph` over `SummaryAgentState`, pre-fork serial then two concurrent
branches rejoining at a barrier:

```
load_config → read_metadata → semantic_profile → baseline_scope → baseline_coverage
  → understand_report
      ├── SUMMARY branch  (descriptive: "what the numbers are")
      │     plan_dax → generate_dax → validate_dax → execute_dax → normalize
      │     → period_resolver → focus_universe → candidate_builder
      │     → overall_performance → novelty_filter → focus_evidence
      │     → fresh_summary_generator → dashboard_build → validator → done
      └── INSIGHT branch (investigative: "why they look that way")
            normalize → temporal → business_day_source → recent_week → daily
            → evidence_catalog → stat_detector → novelty → signal_detector
            → evidence_assembler → gap_scan → investigator → synthesizer → done
  → save_outputs
```

The critical control-plane step is **`semantic_profiler.build_profile()`**
(`src/agents/semantic_profiler.py`). It is deterministic and contains no model-specific
names — which is genuinely good — but it emits one specific *shape*:

```python
primary_value_bundle = {
    "family": "revenue",
    "measures": {"current": ..., "prior": ..., "change": ...},
    "derived":  {"prior": {"expression": "[cur] - [chg]"}},   # reconstruction
}
```

Everything downstream is a function of that shape.

### 1.2 Where it is welded to YoY

Ordered by how hard each is to remove.

#### (a) The measure triple is the type system — `semantic_profiler.py`

```python
_CURRENT = {"current","curr","cy","actual","this","ty"}
_PRIOR   = {"past","prior","previous","prev","ly","py","last"}
_CHANGE  = {"growth","change","chg","variance","var","delta","difference","diff","yoy"}
```
(`:30-32`)

- `:244` — `if "current" not in phases: continue` — a bundle without a current phase is discarded.
- `:275-277` — `value_bundles` keeps only bundles where prior is present **or derivable**;
  `primary_value_bundle` is `value_bundles[0]`. **No prior ⇒ no primary metric ⇒ no report.**
- `:43` — `_VALUE_FAMILIES = {"revenue","profit","cost"}`. Stock on hand, cover days, fill
  rate, lead time, shrink can never be the primary metric; at best they are classified
  `"other"` with score 0.
- `:45-54` — `_FAMILY_PRIORITY` hard-ranks `revenue: 100`.
- `:128-138` — `_additive()` returns a boolean. There is **no semi-additive concept**, so
  a stock balance (which sums across stores but *not* across time) is indistinguishable
  from revenue. Every reconciliation check downstream would silently pass on a wrong sum.

#### (b) Population = "traded in both periods" — `baseline_scope.py`

```python
if not entity.get("reference") or not current or not prior:
    return None                                   # :40-41
...
if has_current and has_prior:   auto_comparable.append(code)
elif has_current:               new.append(code)
elif has_prior:                 prior_only.append(code)
```
(`:106-115`)

"Comparable" is defined *only* as period-over-period activity. For an inventory report the
meaningful population is "SKUs that are stocked and rangeable"; for procurement, "suppliers
with an active contract". Neither is expressible. The excluded set then propagates into
every scan filter via `insight_excluded_entities`.

#### (c) The DAX builder signature — `summary_focus_queries.py:114-173`

```python
def universe_scan(..., current_measure, prior_measure, change_measure, pool_rows, ...)
    change_expr = f"[{change_measure}]" if change_measure else f"([{current_measure}] - [{prior_measure}])"
```

The three-phase contract reaches all the way into the generated DAX, including the
broadcast diagnostics (`__gross_sibling_change`, `__signed_sibling_change`,
`__parent_change`) which are all defined as sums of signed deltas.

#### (d) Hard stop in the universe scan — `summary_focus_universe.py:190-198`

```python
if not (current_m and prior_m):
    universe = {"status": "no_metric",
                "reason": "no additive current/prior value family in metadata"}
```

R4/R5/R6 — the entire modern product — degrade to nothing here.

#### (e) Materiality is delta arithmetic — `summary_materiality.py:26-59`

`area_change = current − prior`; `global_impact_pct = |change| / |overall_current|`;
`business_share_pct = |current| / |overall_current|`; `area_change_pct = change / |prior|`.
All four are undefined for a snapshot or a rate.

#### (f) Coverage, ranking and severity — `summary_coverage.py`

```python
def is_comparable(member):        # :89-96
    """True when both sides of the year-on-year pair are present."""
    return _num(member.get("current")) is not None and _num(member.get("prior")) is not None
```

- `peer_median_change_pct`, `unexpectedness_pts`, `rank_scores` (`:99-201`) all require
  `change_pct`.
- `severity()` (`:124-151`) — a member with no prior can never be `critical`, and is
  labelled "not comparable / no prior year". For a stock report **every** member is in that
  bucket, so the entire R5 coverage surface renders as a table of "not comparable".

#### (g) The three-lever spine — `summary_levers.py`

`Revenue = Transactions × Basket Size × Price` is in the module docstring, the state-name
matrix (`_STATES`, 8 named sign corners), the vocabulary (`_LEVER_WORDS`: "fuller baskets",
"higher prices and mix") and the labels. It requires **three** families each with current
*and* prior. It is the flagship R6 feature and it is pure retail POS.

Likewise `summary_overall._bridge()` (`:43-72`) — volume vs rate/mix — needs
revenue + quantity, both phases.

#### (h) Axis vocabulary is merchandise-only — `summary_roles.py:23-48`

```python
HIERARCHY_LEVELS = {"division":10,"department":20,"section":25,"category":30,
                    "subcategory":35,"product_group":40,"special_product_group":50,
                    "brand":60,"product":70,"item":70,"sku":70}
DEFAULT_ALLOWED_ROLES  = ("division","department","section","category")
DEFAULT_COVERAGE_ROLES = ("store","division","department","section","category")
```

`store` is deliberately absent from `HIERARCHY_LEVELS` and special-cased in
`summary_focus_universe._resolve_store_role()`. That was the right call for merchandise,
but it means **every new orthogonal axis needs new code**: supplier, warehouse, buyer,
channel, customer segment, promotion, season.

#### (i) Report-type-specific business logic in generic modules

- `summary_candidate_builder._angle()` (`:103-146`) returns literals: `store_overview`,
  `division_overview`, `category_overview`, `product_overview`, `period_movement`.
- `_comparison_label()` (`:177-219`) regex-matches `ly|py|yoy` and returns the string
  `"the same period last year"`.
- `_family()` (`:56-68`) is a second, independent copy of the retail family vocabulary.
- `summary_rag.py:49-63` — `DEFAULT_MEASURE_BANDS` keyed on `revenue/units/basket_size/price`;
  `DEFAULT_CAUTIONS` contains the literal sentence *"We sold fewer items than last year."*
- `summary_calendar.py` — the comparator-drift check ("Eid fell inside this period last
  year but not this year") is *inherently* a YoY concept. It is correct code that must
  become an opt-in contract capability rather than an always-on layer.
- `summary_dashboard.py` (58 `prior` refs) — `_verdict_tag`, KPI cards, waterfall,
  contribution points, `period_context` ("3 of 7 periods came in below last year").

#### (j) Memory keys assume a period — `summary_memory.py`, `insight_memory.py`

`focus:v1:{dataset+dimension_role+segment+metric_family+lens}` and the insight
`story_key`'s `period_anchor` both assume the unit of novelty is *a period's movement*.
A snapshot report's novelty unit is different: **a state and its duration** ("SKU-1183 has
been below reorder point for 9 days") — which is not a new period, and must not resurface
daily as if it were new.

#### (k) Prompts and rulebooks

- `prompts/_global_rules.md` — branch scope wording assumes describe-vs-investigate over a
  comparison.
- `config/summary_business_rules.md:22-26` — *"For a store or merchandise focus, managers
  want to know: how revenue, quantity and transactions changed…"*
- `prompts/summary_dashboard_prompt.md` — written around the four-layer YoY page.
- `config/business_rules.md` (827 lines) — mixes three genuinely different things: company
  facts (BR-00 currency/VAT), report-specific calculation policy (BR-01..BR-10 like-for-like
  branches), and analytical framework (BR-28 the 27 lever states, BR-32 how to explain a
  revenue change). Only the first is client-level; the rest is *report*-level and currently
  has nowhere else to live.

#### (l) One config = one report

`grep -rniE "report_type|report_kind|report_template" src/` → **no matches.** There is no
report identity anywhere. `ai_content_report_ids` is a list of *publishing targets for the
same content*, not a set of distinct reports. `config/<client>/config.json` +
two sibling rulebooks *is* the report. Memory and history key on `dataset_id` alone, so two
reports over one dataset would collide.

#### (m) Config UI groups are YoY prose — `config_schema.py:69-131`

Group titles and blurbs: *"Which shops to compare — comparing this year to last year only
makes sense for shops that were trading in both years"*, *"How your products are
organised"*. `HIERARCHY_ROLES` (`:138-150`) duplicates the merchandise vocabulary. The
wizard's information architecture is itself report-specific.

### 1.3 Summary of what must change

| Layer | Change class |
|---|---|
| `semantic_profiler` | **Extend** — emit contract-shaped spines, keep the deterministic evidence approach |
| `baseline_scope` | **Generalize** — population rule becomes a declared strategy |
| `summary_focus_queries` | **Generalize signature** — take a `Spine`, not three measure names |
| `summary_materiality`, `summary_coverage` | **Add a second ranking blend** for non-delta reports |
| `summary_levers`, `summary_overall._bridge` | **Demote to registry entries** behind one interface |
| `summary_roles` | **Replace vocabulary with data** |
| `summary_rag` | **Already 80% there** (band sets are config-owned); make the measure keys contract ids |
| `summary_calendar` | **Gate** as a comparison-kind capability |
| `summary_candidate_builder._angle`, `_family`, `_comparison_label` | **Delete and re-source from the contract** |
| `summary_dashboard*`, `summary_visual` | **Layout pack** — page model driven by a `LayoutSpec` |
| `summary_memory`, `insight_memory` | **Add a state-novelty key kind** alongside period-novelty |
| `config_schema`, `src/api/`, `src/services/probe.py`, `validate.py` | **Contract-aware**: template picker, contract editor, contract conformance probe |
| Prompts, rulebooks | **Split** client facts / report contract / report narrative guidance |

---

## PART 2 — The standardized report framework

### 2.1 Layering

```
┌─────────────────────────────────────────────────────────────────┐
│ KNOWLEDGE LAYER   report_business_rules.md  (prose, human)      │  meaning, decisions, provenance
├─────────────────────────────────────────────────────────────────┤
│ CONTRACT LAYER    report.json  (declarative, UI-authored)       │  what/how/what-matters/how-it-reads
├─────────────────────────────────────────────────────────────────┤
│ CAPABILITY LAYER  src/  (code, report-agnostic)                 │  scan, query, validate, rank, remember, render
└─────────────────────────────────────────────────────────────────┘
```

Rule of thumb for where a fact belongs:

- **Machine must enforce it** → contract (`min_share_pct: 5`).
- **LLM must respect it, machine cannot check it** → knowledge layer (*"Ramadan shifts ~11 days earlier each year"*).
- **True for every report we will ever run** → code.

### 2.2 The report contract — full skeleton

New file: `config/<client>/reports/<report_id>.json`. Version-stamped, schema-validated by
a new `report_schema.py` that stands to it as `config_schema.py` stands to `config.json`.

```jsonc
{
  "contract_version": 1,
  "report_id": "retail_yoy_performance",          // MANDATORY, stable, memory key
  "report_name": "Retail Brand MIS — Sales vs Last Year",
  "template": "period_comparison_retail",          // seeds defaults; not runtime behaviour
  "dataset": { "workspace_id": "…", "dataset_id": "…" },   // MANDATORY

  // ─── 1. SCOPE & NATURE ────────────────────────────────────────
  "scope": {
    "question": "How is the business trading versus the same period last year?",
    "audience": "Regional and brand managers",
    "nature": "performance_comparison",            // MANDATORY (enum, see 2.3)
    "cadence": "daily",
    "decisions_supported": ["range action", "branch intervention", "pricing review"],
    "out_of_scope": ["forecasting", "customer-level analysis", "stock availability"]
  },

  // ─── 2. MEASUREMENT SPINE ─────────────────────────────────────
  "measurement": {
    "comparison_kind": "period_over_period",       // MANDATORY — selects the plugin
    "baseline": {
      "label": "the same period last year",        // MANDATORY — manager-facing wording
      "offset": "-1y",
      "binding": "measure_phase"                   // prior comes from a measure, not a time shift
    },
    "delta": { "kind": "absolute", "pct_denominator": "baseline" },
    "undefined_baseline": "separate_bucket",        // separate_bucket | exclude | zero_baseline
    "population": {
      "strategy": "active_in_both_phases",         // MANDATORY (enum, see 2.4)
      "axis": "store",
      "configured_include": [],
      "configured_exclude": ["CFH022"],
      "audit_against_data": true
    },
    "denominator": { "kind": "overall_current", "measure": "revenue" }
  },

  // ─── 3. KPI REGISTRY ──────────────────────────────────────────
  "kpis": [
    { "id": "revenue", "label": "Revenue", "role": "primary",
      "kind": "flow", "aggregation": "additive",
      "direction": "higher_is_better", "unit": "SAR", "format": "compact_money",
      "band_set": "standard",
      "bindings": { "current": "net revenue CURRENT", "prior": "net revenue PAST",
                    "change": "revenue Growth" },
      "synonyms": ["sales", "turnover", "net sales"] },

    { "id": "units", "label": "Units", "role": "driver",
      "kind": "flow", "aggregation": "additive",
      "direction": "higher_is_better", "unit": "each", "band_set": "tough",
      "bindings": { "current": "net qty CURRENT", "prior": "net qty PAST" },
      "caution": "We sold fewer items than last year." },

    { "id": "transactions", "label": "Transactions", "role": "driver",
      "kind": "count", "aggregation": "additive_within_level",
      "direction": "higher_is_better", "band_set": "standard",
      "bindings": { "current": "net bills CURRENT", "change": "bills growth" },
      "reconstruct_prior_from_change": true,
      "vocabulary": { "approved": "transactions",
                      "forbidden": ["traffic","footfall","visits","shoppers"] } }
  ],

  // ─── 4. AXES ──────────────────────────────────────────────────
  "axes": [
    { "id": "division",   "label": "Division",   "kind": "hierarchy", "depth": 10,
      "focus_eligible": true, "coverage": true, "resolve": { "mode": "auto" } },
    { "id": "department", "label": "Department", "kind": "hierarchy", "depth": 20,
      "focus_eligible": true, "coverage": true,
      "resolve": { "mode": "alias", "from": ["dep","dept"] } },
    { "id": "category",   "label": "Category",   "kind": "hierarchy", "depth": 30,
      "focus_eligible": true, "coverage": true },
    { "id": "sku",        "label": "SKU",        "kind": "hierarchy", "depth": 70,
      "focus_eligible": false, "coverage": false, "deep_dive_only": true },
    { "id": "store",      "label": "Branch",     "kind": "orthogonal",
      "focus_eligible": false, "coverage": true,
      "resolve": { "mode": "pin", "column": "'DIM_BRANCH'[BRANCH_NAME]" } }
  ],
  "time": {
    "axis_preference": ["business_date","month"],
    "reject": ["load_date","batch_date","posting_date"],
    "grain": "auto",
    "period_view": "latest_complete_month"
  },

  // ─── 5. DECOMPOSITIONS ────────────────────────────────────────
  "decompositions": [
    { "id": "three_lever", "target": "revenue", "method": "sequential_multiplicative",
      "factors": [
        { "id": "transactions", "expr": "transactions" },
        { "id": "basket_size",  "expr": "units / transactions", "band_set": "tough" },
        { "id": "price",        "expr": "revenue / units",       "read_with": "basket_size" }
      ],
      "state_matrix": "retail_three_lever",
      "order_note": "Traffic, then basket, then price — attribution order matters." },

    { "id": "volume_rate", "target": "revenue", "method": "two_way_volume_rate",
      "quantity": "units",
      "note": "Rate/mix reflects price and mix together, not pure price." }
  ],

  // ─── 6. WHAT MATTERS ──────────────────────────────────────────
  "significance": {
    "ranking_blend": "impact_magnitude_unexpectedness",   // see 2.6
    "weights": { "impact": 0.40, "magnitude": 0.35, "unexpectedness": 0.25 },
    "magnitude_ceiling_pct": 100,
    "material_change_pct": 10,
    "material_share_pct": 5,
    "headline_min_impact_pct": 0.05,
    "focus_target_count": 4,
    "rotation": { "window_days": 7, "min_repeat_gap_days": 3,
                  "overlap_threshold": 0.6, "overlap_window_days": 14 },
    "overrides": { "reversal": true, "magnitude_pct": 25, "min_impact_share_pct": 3 },
    "suppress": [
      { "when": "share_pct < 0.5 AND abs(change_pct) > 100",
        "reason": "freak percentage on a negligible base" }
    ]
  },

  // ─── 7. NARRATIVE ─────────────────────────────────────────────
  "narrative": {
    "layout": "retail_yoy_dashboard",               // → layouts/*.json
    "views": ["full_span", "latest_complete_period"],
    "rule_pack": "comparison_strict",               // → rule_packs/*.json
    "eyebrow": "AI Insights",
    "title": "Sales vs Last Year",
    "instructions": [
      "Lead with the branch-level story; managers act on branches, not divisions.",
      "Never present a price rise as pricing power without stating basket size."
    ],
    "capabilities": { "calendar_comparator": true, "new_entity_note": true }
  },

  // ─── 8. KNOWLEDGE ─────────────────────────────────────────────
  "knowledge": {
    "rulebook": "report_business_rules.md",
    "glossary": "glossary.md",
    "client_rulebook": "../../client_business_rules.md"
  }
}
```

### 2.3 Mandatory vs optional

**Mandatory — the agent refuses to run without these (8 fields):**

| Field | Why it cannot be defaulted |
|---|---|
| `report_id` | Memory/history key; a wrong or missing one corrupts rotation across reports |
| `dataset.workspace_id`, `dataset.dataset_id` | No inference possible |
| `scope.nature` | Selects the default layout, rule pack and ranking blend |
| `measurement.comparison_kind` | Selects the spine plugin — the single most consequential choice |
| `measurement.baseline.label` | Every figure in the report is *relative to* this; a wrong label is a lie on every line |
| ≥1 `kpis[]` entry with `role: "primary"` and resolvable bindings | Nothing to report on |
| ≥1 `axes[]` entry with `coverage: true` | Nothing to break down by |

**Probe-derived, human-confirmable (defaulted by the probe, editable):** KPI bindings,
axis resolution, time axis, hierarchy depths, population membership, `undefined_baseline`,
denominator. These are exactly the values that *cannot* be answered before inspecting the
model — the reason the wizard is probe-first today, and the reason that ordering must survive.

**Optional with safe code defaults:** significance thresholds, rotation, weights,
decompositions (zero is valid), narrative instructions, capabilities, glossary.

**Never in the contract:** credentials, connection strings, LLM provider keys, blob keys —
those stay in `config.json`/env exactly as today.

### 2.4 Comparison kinds — the plugin interface

This is the heart of the design. Each kind is a small class in
`src/tools/comparison/<kind>.py` implementing one interface, registered by name.

```python
class Spine(Protocol):
    """Everything downstream needs to compare a member against its baseline."""
    kind: str                      # "period_over_period" | ...
    primary: KpiBinding            # measure + alias for the value being reported
    baseline: BaselineBinding|None  # measure / target / threshold / prior snapshot
    baseline_label: str            # "the same period last year"

    def delta_expr(self) -> str:                   # DAX fragment for the movement
    def delta_kind(self) -> str:                   # absolute | points | ratio | distance | none
    def pct(self, current, baseline) -> float|None # the report's % semantics
    def classify(self, row) -> str                 # comparable | baseline_missing | current_only | inactive
    def population_filter(self, scope) -> str|None
    def denominator(self, rows) -> float|None
    def is_material(self, facts, thresholds) -> bool
    def rank_components(self, member, level) -> dict  # feeds the blend
    def novelty_key(self, member, period) -> dict     # period anchor vs state+duration
    def caveats(self) -> list[str]
```

| Kind | Baseline | Delta | Population strategy | Novelty unit | Retail use |
|---|---|---|---|---|---|
| `period_over_period` | prior measure or time-shifted | absolute + % of baseline | `active_in_both_phases` | period anchor | **Today's report.** YoY / MoM / WoW |
| `actual_vs_target` | target/budget/plan measure | variance + % attainment | `has_target` | period anchor | Sales vs budget, labour vs plan |
| `snapshot_vs_threshold` | policy band (min/max/reorder) | **distance from band** | `rangeable_and_active` | **state + duration** | Inventory health, stock-out risk |
| `snapshot_vs_snapshot` | same measure, prior snapshot | absolute + % | `present_in_both_snapshots` | snapshot pair | Stock movement week-on-week |
| `ratio_vs_standard` | a standard/SLA value | **points**, not % | `has_denominator_volume` | period anchor | Fill rate, OTIF, sell-through, shrink |
| `composition` | none — the mix *is* the finding | share-point shift | `in_universe` | mix state | Category mix, channel mix, ABC class |
| `flow_balance` | identity must close | residual/unexplained | `has_all_flow_legs` | reconciliation break | Opening+In−Out=Closing, PO pipeline |

**Two things this table makes concrete:**

1. `snapshot_vs_threshold` is *not* a config tweak. It needs (i) semi-additive aggregation,
   (ii) a ranking blend with no signed change, (iii) a novelty key with duration. That is
   why it is Phase 4 of the roadmap, not Phase 1.
2. `ratio_vs_standard` breaks the *percentage of a percentage* trap: a fill rate moving
   92% → 88% is **−4 points**, never "−4.3%". `delta_kind: "points"` makes that a machine
   guarantee rather than a prompt instruction.

### 2.5 KPI semantics — what `aggregation` must express

| Value | Sums across members? | Sums across time? | Example | Consequence if wrong |
|---|---|---|---|---|
| `additive` | yes | yes | revenue, units | — |
| `semi_additive_last` | yes | **no** (take latest) | stock on hand, headcount | Summing 30 days of stock reports 30× the truth |
| `additive_within_level` | yes, **at one level only** | yes | transactions/bills | Adding bills across categories double-counts baskets (already a live rulebook rule, BR-29) |
| `non_additive_ratio` | **no** — recompute from parts | no | fill rate, margin %, price | Averaging averages; a small branch skews the estate |
| `duration` | no — distribution, not sum | no | lead time, cover days | Sums are meaningless; needs median/p90 |

`semantic_profiler._additive()` returns a plain bool today. Making this a five-value
enum is a small change with large protective value — it is what stops the engine from
confidently reporting a wrong total on an inventory model.

### 2.6 Ranking blends

The R5 blend is `0.40·impact + share·(0.35·magnitude + 0.25·unexpectedness)` and it exists
to solve a real, documented failure (a ₹312 movement headlining at −85.7%). Generalize it
as **named blends**, all built from the same normalization primitives:

| Blend | Components | For |
|---|---|---|
| `impact_magnitude_unexpectedness` | share-weighted, today's exact math | delta reports |
| `severity_exposure_persistence` | distance-from-band × value-at-risk × days-in-state | `snapshot_vs_threshold` |
| `variance_attainment_share` | absolute variance × attainment gap × share of plan | `actual_vs_target` |
| `points_volume_trend` | point change × underlying volume × direction run | `ratio_vs_standard` |
| `shift_concentration` | share-point shift × Herfindahl move | `composition` |

Weights, ceilings and floors stay per-report configurable. The *normalization* math
(`divide_by_max`, winsorization, share-weighting) stays in code and is shared.

---

## PART 3 — Config UI design

### 3.1 New information architecture

Today's eight groups become a two-tier wizard: **client** once, then **report** per report.

```
CLIENT  (once per client — mostly today's config.json)
  1  Connect            tenant / workspace / dataset · AI provider          [essential]
  2  Where it goes      three storage destinations (unchanged)              [essential]
  3  Client facts       currency · VAT · timezone · fiscal calendar         [essential]

REPORT  (repeat per report — the new surface)
  4  Report type        template picker → seeds the contract                [essential]
  5  Purpose & scope    question · audience · nature · cadence · out-of-scope
  6  Probe              contract conformance against the live model         [gate]
  7  Measurement        comparison kind · baseline label · population · denominator
  8  KPIs               binding table: measure → kpi id, kind, aggregation, direction, bands
  9  Axes               hierarchy depths · orthogonal axes · focus vs coverage
 10  Decompositions     pick / define identities                           [optional]
 11  What matters       thresholds · weights · rotation · suppressions
 12  Narrative          layout · rule pack · title · vocabulary · instructions
 13  Knowledge          rulebook editor + template scaffold
 14  Validate & publish blocking errors → deploy
```

Steps 5, 7–13 are *contract* editing; 1–3 stay `config.json`. Step 4 is new and does the
heaviest lifting: choosing a template pre-fills 60–80% of steps 7–12, so a new report is
realistically **~15 questions**, matching the current 31-essential-key design goal.

### 3.2 Report templates

Shipped as `config/templates/<template_id>.json` — a partial contract plus a
`probe_expectations` block the conformance probe checks.

```
period_comparison_retail     YoY / MoM sales performance          (= today's behaviour)
target_attainment            actuals vs budget / plan / forecast
inventory_health             stock vs policy band, cover, ageing
service_level                fill rate · OTIF · availability
supplier_performance         procurement: spend, lead time, compliance
mix_composition              category / channel / ABC mix shift
flow_reconciliation          stock or cash movement balance
blank                        expert: declare everything by hand
```

A template is **seed data only**. Once written into `report.json` the runtime never reads
the template again — the contract is self-contained and auditable, exactly as
`business_rules_snapshot.md` is today.

### 3.3 Generic configuration vs report-specific business rules

The separation the current product lacks:

| Lives in `config.json` (client, generic) | Lives in `report.json` (report, generic) | Lives in `report_business_rules.md` (report, prose) |
|---|---|---|
| tenant / workspace / dataset ids | report id, name, scope, nature | why this report exists, who acts on it |
| AI provider, deployment, model | comparison kind, baseline label | why *this* baseline is the fair one |
| three storage destinations, prefixes | KPI ids, bindings, aggregation, direction | what each KPI means to the business, edge cases |
| timezone, currency, VAT stance | axes, depths, focus/coverage | why an axis is or is not decision-relevant |
| query/LLM budgets, feature flags | thresholds, weights, rotation | why 10% is the threshold *here* |
| memory policy, cooldowns | layout, rule pack, vocabulary | tone, forbidden framings, worked examples |
| delivery channel requirements | exclusions (machine-enforced list) | why each exclusion exists, who decided, when to revisit |

The load-bearing rule: **if a machine can enforce it, it goes in the contract; the rulebook
explains it.** An exclusion illustrates the pair — `configured_exclude: ["CFH022"]` is
enforced by `scope_validator`; the rulebook carries *"CFH022 opened in March 2025, so it
has no last-year baseline; it is still counted in total sales (BR-03)."* Today those two
facts live in the same 827-line markdown file, and only the prose half is actually enforced.

### 3.4 Contract-aware probe

`services/probe.py::run_probe` becomes `run_probe(config, contract)` and changes its
question from *"does this model support our YoY report?"* to **"does this model satisfy
this contract?"** Same in-process, no-LLM, no-write, temp-location execution.

Output sections:

1. **Binding resolution** — per KPI: resolved / ambiguous / missing, with the candidate
   measures and a confidence, plus reconstructed phases (`prior = current − change`).
2. **Aggregation verification** — for each `additive` KPI, the existing windowed
   reconciliation; for `semi_additive_last`, prove the sum-across-time is *not* equal to
   the latest (that non-equality is the evidence it is semi-additive) — this catches a
   mis-declared stock measure before it ships a 30× wrong total.
3. **Axis resolution** — per axis: column, member count, reconciliation verdict, mirroring.
4. **Population** — strategy applied, member counts per bucket, audit vs configured lists.
5. **Time axis** — verdicts per candidate (`business_date` / `batch_date` / `stale` /
   `timestamped`), `data_as_of`, span, completeness of the latest period.
6. **Decomposition feasibility** — for each declared identity, whether all factors resolve
   and whether the identity closes numerically on scanned totals.
7. **Contract conformance** — blocking errors phrased against the contract, e.g.
   *"Your contract says fill rate is a ratio measured in points, but the measure it points
   at sums to 4,712 across branches, which a rate cannot do. Either the binding is wrong or
   the KPI kind is."*

Blocking (hard stop, unchanged philosophy): unreconciled coverage axis; missing primary
KPI binding; a declared additive KPI that fails reconciliation; an axis pinned to a column
that does not exist; a `snapshot_*` contract on a model with no snapshot date.

### 3.5 UI mechanics that carry over unchanged

Everything in `docs/config-ui.md` that already works stays: schema-rendered forms,
tiers (`essential`/`standard`/`expert`), plain-language `label`/`help`/`detail`, findings
with `title`/consequence/`fix`, byte-identical round-trip saving (`services/clients.py`),
env-vs-config resolution (`validate.effective`), the three-destination storage preview,
ARM secret merge (`services/deploy.py`), and jobs-not-requests for long operations.

New UI components needed:

| Component | Why a plain form field will not do |
|---|---|
| **Template gallery** (step 4) | The choice reshapes seven later steps; it needs consequence copy, not a dropdown |
| **KPI binding table** | Two-sided mapping (model measures ↔ contract KPIs) with per-row probe status; the highest-error-rate screen in the product |
| **Axis builder** | Drag-order depth, hierarchy-vs-orthogonal toggle, live member counts, mirror warnings |
| **Decomposition editor** | Formula entry with live "does this identity close?" verification against probe totals |
| **Threshold simulator** | Replay the probe's scanned rows through the blend and show *which members would be reported* at the current thresholds. This is the only honest way to tune a threshold, and it needs no extra queries |
| **Layout preview** | Render the layout skeleton with probe data — the existing `scripts/preview_summary_dashboard.py` promoted into the UI |
| **Rulebook editor** | Markdown + template scaffold + section completeness checks |

---

## PART 4 — Business documentation / knowledge layer

### 4.1 What belongs in prose rather than the contract

Four kinds of thing, none machine-checkable:

1. **Meaning** — what a KPI *is* in this business, including the awkward edges
   ("net revenue excludes VAT and inter-branch transfers").
2. **Justification** — why a threshold, an exclusion, a population rule is what it is,
   who decided, and when it should be revisited.
3. **Interpretation frameworks** — the analytical grammar the report reasons in. BR-28's
   27 lever states and BR-32's "how to explain any revenue change" are the model example:
   they are *how to think*, not *what to compute*.
4. **Forbidden framings** — conclusions that are technically supportable but commercially
   wrong ("never call a price rise pricing power without stating basket size").

### 4.2 Three files, three lifecycles

| File | Scope | Changes when |
|---|---|---|
| `client_business_rules.md` | company-wide | the company changes (currency, VAT, fiscal calendar, entity naming) |
| `reports/<id>/report_business_rules.md` | one report | the report's policy changes (thresholds, exclusions, framing) |
| `prompts/_global_rules.md` | all reports, all clients | almost never (safety, tone, no-forecasting, no-emoji) |

This split is what the current single `business_rules.md` is missing, and it is why that
file has grown to 827 lines mixing three lifecycles.

### 4.3 Standard rulebook template

Shipped as `config/templates/report_business_rules.template.md`, scaffolded by the UI.
It keeps every convention the existing 827-line rulebook earned — numbered immutable rules,
`[V]`/`[B]`/`[A]` provenance marks, an at-a-glance table, retired-not-reused numbers — and
adds machine-addressable structure.

```markdown
# <Report name> — Business Rules
Report ID: <report_id>        Owner: <name>       Last reviewed: <date>
Contract: reports/<report_id>.json

> These rules win. Where a rule here disagrees with the agent's normal behaviour,
> the rule wins. A copy is snapshotted with every run.

## 0. Provenance marks
| Mark | Meaning |
|---|---|
| **[V]** | Verified against live data on <date> |
| **[B]** | Business decision — true because we decided it |
| **[A]** | Assumption — **needs confirmation** |

## 1. Rules at a glance
| # | Rule | Mark |
|---|---|---|

## 2. What this report answers            → mirrors contract.scope
## 3. What this report must NOT be used for
## 4. KPI definitions                     → one block per contract.kpis[] id
   ### <kpi_id> — <label>
   - **Means:** …
   - **Excludes:** …
   - **Aggregation:** … (must match contract; the probe checks it does)
   - **Good direction:** … and why
   - **Read alongside:** …
## 5. The baseline and why it is fair     → justifies contract.measurement.baseline
## 6. Population and exclusions           → one block per configured_exclude entry
   - **<member>** — reason · decided by · date · revisit when
## 7. Calculation policy                   (the BR-nn numbered rules)
## 8. Interpretation framework             (the state matrix / how to explain a change)
## 9. Thresholds and why                   → justifies contract.significance
## 10. Language rules                      approved / forbidden words, with the reason
## 11. Known data limitations              → what the probe found and we accepted
## 12. Open assumptions [A]                the review queue
```

### 4.4 How the agent uses it

Unchanged mechanism, generalized routing. `file_io.business_rules_block(state)` becomes
`knowledge_block(state, audience=...)` and composes three snapshots into every LLM prompt,
in precedence order **global rules → client rules → report rules**, with the report rulebook
authoritative on conflicts.

Two additions worth the effort:

- **Section routing.** Inject §4 (KPI definitions) + §10 (language) into the summary
  generator; §7–§8 (calculation policy, interpretation framework) into the insight
  synthesizer and investigator; §5–§6 into report understanding. A 900-line rulebook in
  every prompt dilutes attention and costs tokens; the section headings above make routing
  mechanical.
- **Scope answering.** `scope.question` / `decisions_supported` / `out_of_scope` plus §2–§3
  give the agent a deterministic answer to "can this report tell me X?" — today it has no
  representation of its own boundaries and will cheerfully attempt anything the metadata
  permits.

Snapshotting stays: `business_rules_snapshot.md` becomes three snapshot files plus
`report_contract_snapshot.json`, so any delivered artifact can be reproduced exactly.

---

## PART 5 — Agent architecture

### 5.1 Contract resolution: one new pre-fork node

```
load_config
  → load_contract          ← NEW: parse + schema-validate report.json, snapshot it
  → read_metadata
  → resolve_contract       ← NEW: bind contract to model → ResolvedContract
  → baseline_scope         (now: population strategy from the contract)
  → baseline_coverage
  → understand_report
  → [fork as today]
```

`resolve_contract` is deterministic, no LLM, and produces the single object every
downstream node reads:

```python
@dataclass(frozen=True)
class ResolvedContract:
    contract: dict                    # the declared contract, verbatim
    spine: Spine                      # the comparison plugin, bound to real measures
    kpis: dict[str, ResolvedKpi]      # id → measure refs, aggregation, direction, bands
    axes: dict[str, ResolvedAxis]     # id → column ref, ancestry, depth, kind, flags
    decompositions: list[ResolvedDecomposition]
    population: ResolvedPopulation
    time: ResolvedTime
    thresholds: Thresholds
    layout: LayoutSpec
    rules: RulePack
    knowledge: KnowledgeBundle
    conformance: list[Finding]         # non-blocking findings carried into caveats
```

`semantic_profiler` keeps its job — it is the *evidence gatherer* — but stops being the
*decision maker*. It reports candidates and confidences; `resolve_contract` chooses,
guided by the declared bindings, and falls back to profiler ranking only where the contract
says `mode: "auto"`.

### 5.2 Reusable capability vs report configuration

| Capability (code, one implementation) | Parameterized by |
|---|---|
| `ScanExecutor` — validate, scope-gate, budget, cache, execute | axis refs, KPI measures, population filter |
| `SpineArithmetic` — delta, %, reconciliation, distance | comparison kind |
| `MaterialityEngine` — normalize, blend, band, rank | blend name, weights, thresholds |
| `PortfolioSelector` — eligibility, diversity, rotation, overrides | target count, rotation, overlap |
| `DeepDiveEngine` — child discovery, contributors, trend, bridge | axes, decompositions, budgets |
| `CoverageEngine` — rank every member of every level | coverage axes, blend |
| `NoveltyEngine` — story keys, suppression, resurfacing | novelty-key kind, policy, cooldowns |
| `NarrativeEngine` — slot creation, authoring, fallback, validation | layout spec, rule pack, knowledge |
| `RenderEngine` — self-contained HTML, charts, nav | layout spec, vocabulary |
| `PublishEngine` — local, history, API, blob, app storage | destinations, required channels |

Every one of these exists today; each currently reaches into a global assumption instead
of taking a parameter. **The work is mostly turning implicit dependencies into explicit
arguments** — which is why the golden-master harness in Phase 0 is non-negotiable: it is
the only way to prove a mechanical refactor of this size changed nothing.

### 5.3 Orchestration

- **Prompts become composed, not monolithic.** `prompts/` splits into
  `_global_rules.md` (unchanged) + `tasks/<node>.md` (report-agnostic instruction) +
  `capabilities/<capability>.md` (fragments included only when the contract enables that
  capability, e.g. calendar comparator, three-lever reading). Assembly is code; no prompt
  file mentions revenue, stores or last year.
- **Rule packs are composed from existing primitives.** `summary_validation.py` already
  holds every primitive needed (figure grounding, decimal ceiling, vocabulary bans,
  duplicate-story breadth/prominence, unknown-member rejection). A `RulePack` is a JSON
  list naming primitives with parameters. `focus_rules` and `dashboard_rules` become
  packs `comparison_strict` and `dashboard_prose`.
- **Tool exposure to the investigator stays code-owned.** `run_dax` remains
  object-validated and scope-validated; the contract may narrow what it can touch
  (axes, KPIs, population) but never widen the guardrails.
- **Insight branch gating.** The temporal/recent-week/daily cascade is a
  `period_over_period`-family capability. Under a snapshot contract those levels
  self-disable and say so — the same honest-caveat mechanism they already use when
  `UPDATED_DATE` turns out to be a batch date.

### 5.4 Concurrency contract — unchanged, and must stay so

`ResolvedContract` is **frozen and read-only** after `resolve_contract`. It is built
pre-fork, so both branches read it without a writer conflict. No node may mutate it;
per-run derived facts continue to go into ordinary state keys under the existing
single-writer-per-superstep rule. The joined-edge barrier into `save_outputs` is untouched.

---

## PART 6 — Summary and insight generation

### 6.1 The layout spec

R6 deliberately inverted R1–R5: there the LLM chooses the page plan, in R6 code owns the
structure and the LLM fills prose slots. **R6's inversion is the right general answer** —
a prompt that decides layout will silently drop a layer on a quiet day. So generalize the
*structure*, keep the *inversion*.

`config/layouts/<id>.json`:

```jsonc
{
  "layout_id": "retail_yoy_dashboard",
  "views": [
    { "id": "full_span", "label_from": "scanned_span", "owns_breakdowns": true },
    { "id": "latest_complete_period", "label_from": "period_name",
      "owns_breakdowns": "if_period_scan_reconciles", "requires": "complete_period" }
  ],
  "sections": [
    { "id": "hero", "kind": "verdict", "required": true,
      "prose_slots": ["headline", "narrative"],
      "elements": ["decomposition_chips", "waterfall", "kpi_cards", "signals"] },
    { "id": "entities", "kind": "axis_cards", "axis": "store", "required": true,
      "prose_slots": ["story_per_member"],
      "elements": ["contribution_bars", "share_donut", "factor_minibars"] },
    { "id": "areas", "kind": "focus_spotlight", "source": "portfolio", "required": true,
      "prose_slots": ["headline_per_area", "connect_per_area"],
      "elements": ["deep_dive_evidence"], "state_rotation": true },
    { "id": "detail", "kind": "coverage_tables", "source": "coverage", "required": true,
      "elements": ["top_movers", "full_tables"] }
  ],
  "caveat_policy": "once_per_view_then_footer"
}
```

Guarantees the engine enforces regardless of layout: every `required` section is present or
carries an explicit reason for absence; every prose slot has a grounded deterministic
fallback; every caveat appears exactly once; every quoted figure exists in the view model.

Other layouts: `single_focus_page` (R1–R3), `balanced_multi_focus` (R4/R5),
`exception_list` (inventory — the page *is* a prioritized exception queue, not a hero
verdict), `scorecard_grid` (target attainment), `partner_scorecard` (supplier).

### 6.2 What matters — the general algorithm

Report-agnostic pipeline; every step parameterized:

1. **Universe** — one bounded scan per coverage axis (contract axes, contract KPIs,
   contract population). Unchanged mechanism, unchanged zero-extra-cost coverage.
2. **Facts** — spine arithmetic per member: value, baseline, movement, share, impact,
   reconciliation. `delta_kind` decides whether movement is absolute, points, or distance.
3. **Eligibility** — the contract's material thresholds plus `suppress` predicates.
   The existing R5 headline relevance floor generalizes to *"a movement too small to
   matter cannot lead the report, but is still ranked inside its own level"*, with the
   same drop-the-floor-rather-than-render-blank fallback.
4. **Rank** — the contract's named blend. Never raw percentage — the failure that rule
   prevents (`CF-FRESH BAKES +2166.79%` on a near-zero base) is report-agnostic.
5. **Band** — severity from the blend; RAG from the KPI's band set. Two different
   standards, deliberately, exactly as today.
6. **Diversify** — parent/child suppression, fact overlap within the overlap window,
   rotation and repeat gaps. Expired history can never suppress forever.
7. **Novelty** — spine-supplied key kind: period anchor for flows, **state + duration** for
   snapshots. A snapshot report must say *"still below reorder point, day 9"* rather than
   re-reporting it as new every day; and it must re-report when the state *changes*.
8. **Cover** — every member of every coverage axis gets a ranked line regardless of
   selection. Coverage complete, focus selective. This tension resolution is the R5
   insight and it generalizes untouched.

### 6.3 Avoiding irrelevant observations

Five mechanisms, all already present, all becoming contract-parameterized:

| Mechanism | Today | Generalized |
|---|---|---|
| Share-weighted ranking | `rank_scores` scales ratio components by business share | blend-specific, same primitive |
| Winsorization | `MAGNITUDE_CEILING_PCT = 100` | `significance.magnitude_ceiling_pct` |
| Headline relevance floor | `HEADLINE_MIN_IMPACT_PCT = 0.05` | `significance.headline_min_impact_pct` |
| Unmeasurable ≠ zero | current-only member ranked last, labelled | spine `classify()` → `baseline_missing` bucket, never green, never zero |
| Explicit suppressions | none | `significance.suppress[]` predicates |

Plus the honest-caveat discipline throughout: an unreconciled breakdown is withheld with a
stated reason rather than published with numbers that do not add up. That principle — and
the `scripts/audit_*` tools that enforce it on delivered artifacts — is the most valuable
thing in the codebase and must survive the refactor unchanged.

---

## PART 7 — Configuration-driven extensibility

### 7.1 Adding a new report, end to end

```
1  CREATE     UI → new report → pick template ("inventory_health")
              Contract is seeded; ~15 questions remain.

2  DECLARE    Steps 5,7–12: purpose, comparison kind, KPI bindings, axes,
              decompositions, thresholds, layout.
              Nothing has touched the model yet — no queries, no cost.

3  PROBE      run_probe(config, contract) → in-process, no LLM, no writes.
              Binding resolution · aggregation verification · axis reconciliation ·
              population · time axis · decomposition feasibility · conformance.
              Returns recommendations (appliable in one click) and blocking errors.

4  ITERATE    Apply recommendations, fix blockers, re-probe.
              Threshold simulator shows which members would be reported. No extra queries.

5  AUTHOR     Rulebook editor scaffolds report_business_rules.md from the template.
              Completeness check: every KPI has a §4 block, every exclusion a §6 block.

6  PREVIEW    Layout preview renders the real page from probe rows — no live run,
              no LLM, no publish. This is where "the page is wrong" gets caught cheaply.

7  VALIDATE   services/validate.validate(config, contract, probe) → blocking errors:
              missing mandatory field · unreconciled coverage axis · unverified
              aggregation · storage collision · probe missing or failed · rulebook gaps.

8  DRY RUN    Full pipeline, LLM on, publish off, temp output.
              Then scripts/audit_report.py <output_dir> — re-derives every guarantee
              the contract declares from the written artifacts.

9  PUBLISH    Deploy: three-way secret merge (config, client rulebook, report rulebook),
              ARM request body (the 45KB/32,767-char command-line limit still applies).

10 RUN        python -m src.main --config config/<client>/config.json \
                                 --report retail_yoy_performance
              Memory/history keyed on (dataset_id, report_id). No code was written.
```

The acceptance test for the whole programme: **step 10 works for a report type nobody
anticipated, and no `.py` file changed.**

### 7.2 When code *is* still required

Be honest about this, or the architecture over-promises:

| New requirement | Code needed? |
|---|---|
| New KPI, axis, threshold, layout choice, vocabulary, rulebook | **No** |
| New report of an existing comparison kind | **No** |
| New decomposition using an existing `method` | **No** |
| New comparison kind (e.g. cohort-over-cohort) | **Yes** — one plugin, ~200 lines |
| New decomposition `method` (e.g. logarithmic attribution) | **Yes** — one function |
| New ranking blend | **Yes** — one function |
| New chart type | **Yes** — one renderer in `summary_dashboard_html.py` |
| New layout *section kind* | **Yes** — one builder + renderer |

Each of these is a small, well-isolated, testable addition to a registry — which is the
actual definition of extensible. The claim is *"no code per report"*, not *"no code ever"*.

---

## PART 8 — Data and model requirements

### 8.1 What the semantic model must expose

| Requirement | Why | If absent |
|---|---|---|
| At least one measure bindable to the primary KPI | nothing to report | hard stop |
| A baseline the comparison kind can resolve | every figure is relative | hard stop |
| At least one groupable descriptive column | nothing to break down by | hard stop |
| Members reconciling to the level total | percentages would be quietly wrong | hard stop per axis |
| Active relationships from fact to dimensions | filter paths | axis dropped |
| A genuine business time axis (not load/batch/posting) | trends, period views | time features self-disable with caveat |
| Measure definitions (via Fabric TMSL) | aggregation classification confidence | lower confidence, more `[A]` assumptions |

### 8.2 New metadata the profiler must derive

1. **Aggregation class per measure** (the five-value enum from §2.5) — the most valuable
   single addition. Verified numerically where possible: an `additive` claim is proved by
   windowed reconciliation; a `semi_additive_last` claim is proved by the sum-across-time
   *failing* to equal the latest value.
2. **Snapshot-date detection** — distinguish a *snapshot* date (as-of stamp; the correct
   filter is "latest") from a *transaction* date (event; the correct filter is a range).
   Getting this wrong on an inventory model produces a confidently wrong number.
3. **Threshold / policy measures** — recognize min/max/reorder/safety-stock/target/budget
   as *baseline candidates*, not value candidates. Today they land in `"other"`.
4. **Rate denominators** — for a `non_additive_ratio` KPI, record the numerator and
   denominator measures so the engine can recompute rather than average.
5. **Partner axes** — supplier/vendor/customer dimensions as a distinct axis kind
   (currently invisible: not in `_ENTITY_TOKENS`, not in `HIERARCHY_LEVELS`).
6. **Duration measures** — lead time, cover days, ageing buckets: distribution semantics
   (median/p90), never a sum.

### 8.3 Additional data structures

| Structure | Location | Purpose |
|---|---|---|
| `reports/<id>.json` | `config/<client>/reports/` | the contract |
| `reports/<id>/report_business_rules.md` | same | the rulebook |
| `client_business_rules.md` | `config/<client>/` | client facts |
| `templates/*.json` | `config/templates/` | seed contracts + probe expectations |
| `layouts/*.json` | `config/layouts/` | page skeletons |
| `rule_packs/*.json` | `config/rule_packs/` | validation compositions |
| `state_matrices/*.json` | `config/state_matrices/` | decomposition sign-pattern names |
| memory | `insightstate/{dataset_id}/{report_id}/memory.json` | **report-scoped** — prevents cross-report collision |
| history | `.../{dataset_id}/{report_id}/history/` | same |
| artifacts | `outputs/<report_id>/` | one run can produce several reports |

Migration for memory is a one-time, non-destructive move of the existing store into the
`retail_yoy_performance` subdirectory, following the established v1→v2→v3 migration
pattern in `summary_memory.load_store`.

---

## PART 9 — Implementation roadmap

Nine phases. Phases 0–2 change **no behaviour** and are the majority of the risk
reduction; nothing after Phase 2 is safe without them.

### Phase 0 — Freeze current behaviour *(1–2 weeks)*

The refactor's only real danger is silent regression in arithmetic that is currently
correct and hard-won. So build the net first.

- `scripts/golden_master.py` — run every committed acceptance output
  (`outputs_r4_acceptance*`, `outputs_scanb`, `outputs_replay`) through a byte-comparison
  harness over the deterministic artifacts (`summary_focus_universe.json`,
  `summary_coverage.json`, `summary_overall_performance.json`, `summary_dashboard.json`).
- Pin all 12 existing replays (`replay_summary_*`, `replay_config_*`, `replay_stat_detector`,
  `replay_novelty_filter`, …) into one `scripts/replay_all.py` gate.
- Synthetic model-metadata fixtures for four shapes: today's retail YoY, an
  inventory snapshot, a target-attainment model, a rate/service model. Offline, no auth.
- **Exit criterion:** `replay_all.py` green, golden master byte-identical.

### Phase 1 — Contract extraction, zero behaviour change *(3–4 weeks)*

- `src/report_contract.py` — `ReportContract`, `ResolvedContract`, `Spine` protocol.
- `src/report_schema.py` — the contract catalogue, mirroring `config_schema.py`'s
  discipline (label/help/detail/tier, drift test against code defaults).
- `src/tools/comparison/period_over_period.py` — the *only* plugin, reproducing today's
  behaviour exactly.
- `contract_from_legacy_config()` — derive a contract from any existing `config.json`, so
  no config must be rewritten to adopt the new path.
- Nodes `load_contract` + `resolve_contract`; `ResolvedContract` threaded into state.
- Route `summary_focus_universe`, `summary_materiality`, `summary_coverage`,
  `summary_portfolio`, `summary_focus_queries` through the spine.
- **Exit criterion:** golden master byte-identical with the contract path active.

### Phase 2 — Registries as data *(3–4 weeks)*

- KPI registry: `_FAMILY_TOKENS`/`_VALUE_FAMILIES`/`_FAMILY_PRIORITY` → data; the retail
  set becomes `templates/period_comparison_retail.json`.
- Aggregation enum (5 values) + numeric verification in the profiler and probe.
- Axis registry: `HIERARCHY_LEVELS` → data; `store` becomes an ordinary `orthogonal` axis;
  delete `_resolve_store_role`'s special case.
- Decomposition registry: `summary_levers` and `summary_overall._bridge` become entries
  behind one interface, with `method` dispatch.
- Delete the duplicate vocabularies in `summary_candidate_builder` (`_family`, `_angle`,
  `_comparison_label`) and re-source from the contract.
- **Exit criterion:** golden master byte-identical; `replay_report_contract.py` proves the
  registries cannot drift from code (same test pattern as `replay_config_schema.py`).

### Phase 3 — Second comparison kind: `actual_vs_target` *(2–3 weeks)*

The cheapest second kind — still two measures, still a signed variance — so it validates
the abstraction without also needing semi-additive support or a new ranking blend.

- Plugin + `variance_attainment_share` blend + `target_attainment` template +
  `scorecard_grid` layout.
- Probe recognizes budget/plan/forecast/target measures as baseline candidates.
- **Exit criterion:** a target-attainment report runs end-to-end on the fixture model with
  zero changes to any Phase 1–2 module.

### Phase 4 — Snapshot reports *(4–6 weeks — the hard one)*

Everything the earlier phases deferred lands here.

- `snapshot_vs_threshold` + `snapshot_vs_snapshot` plugins.
- Semi-additive handling end to end: DAX (`LASTNONBLANK`-style patterns), reconciliation
  (a stock total must *not* be a sum over time), display.
- `severity_exposure_persistence` blend — ranking with no signed change.
- **State novelty** in `summary_memory` / `insight_memory`: key on state + duration, with
  its own resurface rules (state change, escalation, duration milestone). Schema v4,
  non-destructive migration.
- `exception_list` layout — the page as a prioritized queue, no hero verdict.
- `inventory_health` template + rulebook template.
- **Exit criterion:** an inventory report runs end-to-end on the fixture model; the
  artifact auditor confirms no stock figure was summed across time.

### Phase 5 — Report registry *(2 weeks)*

- `config/<client>/reports/` layout; `--report` CLI argument; multi-report container runs.
- Report-scoped memory/history/outputs, with migration of the live store.
- `services/clients.py` extended to preserve byte-identical round-trip on contracts.
- **Exit criterion:** two reports over one dataset run without memory collision; the
  existing single-report path still works with no `--report` flag.

### Phase 6 — UI *(4–6 weeks)*

- `GET /api/templates`, `GET/PUT /api/clients/{c}/reports/{r}`, contract-aware
  `/api/probe` and `/api/validate`.
- Template gallery, KPI binding table, axis builder, decomposition editor, threshold
  simulator, layout preview, rulebook editor.
- Rewrite group titles/blurbs to be report-type-driven rather than YoY prose.
- **Exit criterion:** an inventory report configured start to finish through the UI, by
  someone who has not seen the code, with no file edited by hand.

### Phase 7 — Layout and rule packs *(3 weeks)*

- `LayoutSpec` interpreter; port R6's page to `layouts/retail_yoy_dashboard.json` and
  R4/R5's to `balanced_multi_focus`.
- `RulePack` composition; port `focus_rules` → `comparison_strict`,
  `dashboard_rules` → `dashboard_prose`.
- Prompt decomposition into `_global_rules` + `tasks/` + `capabilities/`.
- **Exit criterion:** golden master byte-identical with layouts and rule packs driving the
  existing pages.

### Phase 8 — Migrate live, then extend *(2 weeks + ongoing)*

- Write the contract for the live cityflower report and the scanb client; run both paths
  in parallel for a week; byte-compare the delivered artifacts; cut over.
- Split `business_rules.md` into client + report rulebooks using the new template.
- Then: `service_level`, `supplier_performance`, `mix_composition` templates as
  configuration-only additions.

**Total: roughly 6–8 months of focused single-developer work**, with usable increments from
Phase 3 onward. Phases 0–2 are ~40% of the effort and deliver *no visible feature* — that is
the honest cost of doing this without breaking a product whose arithmetic guarantees are
its main asset.

### Testing and validation strategy

| Layer | Tool | Runs |
|---|---|---|
| No regression | `scripts/golden_master.py` | every commit |
| Component logic | 12 existing replays via `replay_all.py` | every commit |
| Contract/code drift | `replay_report_contract.py` | every commit |
| Contract conformance | `replay_comparison_kinds.py` — every plugin against every fixture | every commit |
| Per-template E2E | `replay_template_<id>.py` — offline, synthetic metadata | every commit |
| Delivered artifact | `scripts/audit_report.py` — contract-driven re-derivation | **after every live run** |
| Live acceptance | full run + audit + human read | per report, per model |

Two properties of the current test approach must be preserved because they are what makes
this codebase safe to change: **replays prove the code is right, auditors prove a produced
artifact is right** (the auditor is what caught both the derived-period contribution bug
and the contaminated-denominator bug), and **every deterministic fallback is itself tested
to pass strict validation**, so validation can never dead-end.

### Migration approach for the existing YoY report

Strictly additive, reversible at every step:

1. Phase 1 ships `contract_from_legacy_config()`. Every existing config keeps working with
   no edit — the contract is derived at load time.
2. `report_contract_enabled` flag, **default false**, following the exact precedent of
   `summary_r4_enabled` / `summary_r6_enabled` (code default off; a config missing the key
   reproduces prior behaviour byte-for-byte).
3. Golden master runs both paths and byte-compares on every commit.
4. Phase 8 writes an explicit contract for cityflower and scanb, parallel-runs for a week,
   compares delivered artifacts, then flips the flag.
5. Legacy derivation stays for two releases, then is removed once no config relies on it.

---

## PART 10 — Worked examples

Four reports. Note what is **identical** across all four — that column is the return on
the whole programme.

### 10.1 Retail YoY performance *(today's report, re-expressed)*

```jsonc
{ "report_id": "retail_yoy_performance",
  "scope": { "nature": "performance_comparison", "cadence": "daily",
             "question": "How is the business trading versus the same period last year?" },
  "measurement": {
    "comparison_kind": "period_over_period",
    "baseline": { "label": "the same period last year", "offset": "-1y", "binding": "measure_phase" },
    "delta": { "kind": "absolute", "pct_denominator": "baseline" },
    "undefined_baseline": "separate_bucket",
    "population": { "strategy": "active_in_both_phases", "axis": "store",
                    "configured_exclude": ["CFH022"] },
    "denominator": { "kind": "overall_current", "measure": "revenue" } },
  "kpis": [ { "id":"revenue", "role":"primary", "kind":"flow", "aggregation":"additive",
              "direction":"higher_is_better", "band_set":"standard" },
            { "id":"units", "role":"driver", "kind":"flow", "aggregation":"additive",
              "band_set":"tough" },
            { "id":"transactions", "role":"driver", "kind":"count",
              "aggregation":"additive_within_level", "band_set":"standard",
              "reconstruct_prior_from_change": true } ],
  "axes": [ division(10,focus), department(20,focus), section(25,focus),
            category(30,focus), sku(70,deep_dive_only), store(orthogonal,coverage) ],
  "decompositions": [ "three_lever", "volume_rate" ],
  "significance": { "ranking_blend": "impact_magnitude_unexpectedness",
                    "material_change_pct": 10, "material_share_pct": 5,
                    "focus_target_count": 4 },
  "narrative": { "layout": "retail_yoy_dashboard",
                 "capabilities": { "calendar_comparator": true, "new_entity_note": true } } }
```

### 10.2 Inventory / stock health

```jsonc
{ "report_id": "inventory_health",
  "scope": { "nature": "exception_management", "cadence": "daily",
             "question": "Where is stock outside policy, and how much revenue is at risk?",
             "out_of_scope": ["sales performance", "supplier negotiation"] },
  "measurement": {
    "comparison_kind": "snapshot_vs_threshold",           // ← different plugin
    "baseline": { "label": "the agreed stock policy band",
                  "binding": "threshold_measures",
                  "lower": "Reorder Point", "upper": "Max Stock" },
    "delta": { "kind": "distance", "unit": "days_of_cover" },
    "undefined_baseline": "exclude",                       // no policy → not an exception
    "population": { "strategy": "rangeable_and_active", "axis": "sku" },
    "denominator": { "kind": "value_at_risk", "measure": "stock_value" } },
  "kpis": [
    { "id":"stock_units", "role":"primary", "kind":"stock",
      "aggregation":"semi_additive_last",                  // ← never sums over time
      "direction":"band_target", "band_set":"policy_band" },
    { "id":"cover_days", "role":"primary", "kind":"duration",
      "aggregation":"duration", "direction":"band_target" },  // median/p90, never a sum
    { "id":"stock_value", "role":"exposure", "kind":"stock",
      "aggregation":"semi_additive_last" },
    { "id":"ageing_over_90d", "role":"risk", "kind":"stock",
      "aggregation":"semi_additive_last", "direction":"higher_is_worse" } ],
  "axes": [ division(10,focus), category(30,focus), sku(70,coverage),
            warehouse(orthogonal,coverage),                 // ← new axis, config only
            store(orthogonal,coverage) ],
  "decompositions": [
    { "id":"stock_value_identity", "target":"stock_value", "method":"multiplicative",
      "factors":[{"id":"stock_units"},{"id":"unit_cost"}] },
    { "id":"cover_identity", "target":"cover_days", "method":"ratio",
      "numerator":"stock_units", "denominator":"avg_daily_units" } ],
  "significance": {
    "ranking_blend": "severity_exposure_persistence",       // ← no signed change exists
    "weights": { "severity":0.40, "exposure":0.40, "persistence":0.20 },
    "suppress":[{ "when":"stock_value < 5000", "reason":"below action threshold" }] },
  "narrative": { "layout": "exception_list",                // ← queue, not hero verdict
                 "capabilities": { "calendar_comparator": false } } }
```

**What this example proves and what it costs.** Everything structural is configuration —
new axis, new KPIs, new thresholds, new layout, no code. But three *capabilities* must
exist in code first: `semi_additive_last`, the `severity_exposure_persistence` blend, and
state-based novelty. That is exactly Phase 4, and it is why Phase 4 is the long one.

### 10.3 Sales vs budget / target

```jsonc
{ "report_id": "sales_vs_budget",
  "scope": { "nature": "target_attainment", "cadence": "weekly",
             "question": "Which areas are behind plan, and by how much?" },
  "measurement": {
    "comparison_kind": "actual_vs_target",
    "baseline": { "label": "the approved budget", "binding": "target_measure",
                  "measure": "Revenue Budget" },
    "delta": { "kind": "absolute", "pct_denominator": "baseline" },   // = attainment
    "undefined_baseline": "separate_bucket",                          // no budget set
    "population": { "strategy": "has_target", "axis": "store" },
    "denominator": { "kind": "overall_target", "measure": "revenue" } },
  "kpis": [ { "id":"revenue", "role":"primary", "aggregation":"additive",
              "bindings":{"current":"net revenue CURRENT","prior":"Revenue Budget"} },
            { "id":"attainment_pct", "role":"derived", "kind":"rate",
              "aggregation":"non_additive_ratio",
              "numerator":"revenue", "denominator":"revenue_budget",
              "band_set":"attainment" } ],
  "axes": [ division(10,focus), department(20,focus), store(orthogonal,coverage) ],
  "decompositions": [ "three_lever" ],                   // ← reused unchanged from 10.1
  "significance": { "ranking_blend":"variance_attainment_share",
                    "material_change_pct":5, "focus_target_count":5 },
  "narrative": { "layout":"scorecard_grid",
                 "capabilities": { "calendar_comparator": false } } }
```

Cheapest possible new report: one plugin, one blend, one layout — then unlimited variants
(labour vs plan, margin vs plan, per-channel budget) as pure configuration.

### 10.4 Procurement / supplier performance

```jsonc
{ "report_id": "supplier_performance",
  "scope": { "nature": "partner_scorecard", "cadence": "monthly",
             "question": "Which suppliers are hurting availability, cost or cash?",
             "out_of_scope": ["price negotiation advice", "contract terms"] },
  "measurement": {
    "comparison_kind": "ratio_vs_standard",
    "baseline": { "label": "the agreed service standard",
                  "binding":"standard_values",
                  "standards": { "fill_rate": 95.0, "otif": 90.0, "lead_time_days": 7 } },
    "delta": { "kind": "points" },              // ← 92%→88% is −4 points, never "−4.3%"
    "population": { "strategy":"has_denominator_volume", "axis":"supplier",
                    "min_volume": { "kpi":"po_lines", "value":20 } },
    "denominator": { "kind":"overall_current", "measure":"spend" } },
  "kpis": [
    { "id":"fill_rate", "role":"primary", "kind":"rate", "aggregation":"non_additive_ratio",
      "numerator":"lines_delivered", "denominator":"lines_ordered",
      "direction":"higher_is_better", "band_set":"service" },
    { "id":"otif", "role":"primary", "kind":"rate", "aggregation":"non_additive_ratio",
      "direction":"higher_is_better", "band_set":"service" },
    { "id":"lead_time_days", "role":"driver", "kind":"duration", "aggregation":"duration",
      "direction":"lower_is_better", "statistic":"p90" },   // ← never a mean
    { "id":"spend", "role":"exposure", "kind":"flow", "aggregation":"additive" } ],
  "axes": [ supplier(orthogonal,focus,coverage),            // ← partner axis is the subject
            category(30,coverage), warehouse(orthogonal,coverage) ],
  "decompositions": [
    { "id":"fill_rate_parts", "target":"fill_rate", "method":"ratio",
      "numerator":"lines_delivered", "denominator":"lines_ordered" } ],
  "significance": { "ranking_blend":"points_volume_trend",
                    "material_change_pct":3, "focus_target_count":5,
                    "suppress":[{ "when":"po_lines < 20",
                                  "reason":"too few orders to judge a rate" }] },
  "narrative": { "layout":"partner_scorecard",
                 "instructions":["Name the affected categories, never just the supplier."],
                 "capabilities": { "calendar_comparator": false } } }
```

`min_volume` is the small-sample guard: a supplier with 3 order lines at 67% fill rate is
noise, and the ranking must not lead with it — structurally the same failure as the
`+2166.79%` freak percentage, so it is solved by the same share-weighting machinery.

### 10.5 What changes vs what is reused

| | YoY perf | Inventory | vs Budget | Supplier |
|---|---|---|---|---|
| **Configuration — differs per report** ||||
| Comparison kind | period_over_period | snapshot_vs_threshold | actual_vs_target | ratio_vs_standard |
| Baseline | prior-year measure | policy band | budget measure | service standard |
| Delta kind | absolute | distance | absolute | **points** |
| Primary KPI | revenue (flow) | stock/cover (stock, duration) | revenue vs budget | fill rate (rate) |
| Aggregation classes used | additive, within-level | **semi-additive, duration** | additive, ratio | **ratio, duration** |
| Population strategy | active in both | rangeable & active | has target | has volume |
| Subject axis | merchandise + store | sku + warehouse | merchandise + store | **supplier** |
| Ranking blend | impact/magnitude/surprise | severity/exposure/persistence | variance/attainment | points/volume/trend |
| Layout | four-layer dashboard | exception list | scorecard grid | partner scorecard |
| Novelty unit | period anchor | **state + duration** | period anchor | period anchor |
| Calendar comparator | on | off | off | off |
| **Capability — identical for all four** ||||
| Auth, token reuse, concurrency contract | ✔ | ✔ | ✔ | ✔ |
| Metadata scan + TMSL definition recovery | ✔ | ✔ | ✔ | ✔ |
| DAX assembly + guardrails (`TREATAS`, `TOPN`) | ✔ | ✔ | ✔ | ✔ |
| Validator, scope gate, repair loop | ✔ | ✔ | ✔ | ✔ |
| Query budgets, caching, zero-extra-cost coverage | ✔ | ✔ | ✔ | ✔ |
| Reconciliation + "withhold rather than publish wrong" | ✔ | ✔ | ✔ | ✔ |
| Normalization, winsorization, share-weighting | ✔ | ✔ | ✔ | ✔ |
| Rotation, diversity, overlap suppression | ✔ | ✔ | ✔ | ✔ |
| Memory transactions, atomic writes, corruption fail-loud | ✔ | ✔ | ✔ | ✔ |
| Prose grounding, decimal ceiling, vocabulary bans | ✔ | ✔ | ✔ | ✔ |
| Deterministic fallback that passes strict validation | ✔ | ✔ | ✔ | ✔ |
| Self-contained HTML rendering, charts, nav, print | ✔ | ✔ | ✔ | ✔ |
| Publishing to three destinations, delivery gating | ✔ | ✔ | ✔ | ✔ |
| Probe → validate → publish onboarding flow | ✔ | ✔ | ✔ | ✔ |
| Artifact auditor re-deriving declared guarantees | ✔ | ✔ | ✔ | ✔ |

---

## PART 11 — Risks and honest caveats

1. **Phase 0–2 deliver no visible feature** and are ~40% of the effort. If they are cut,
   the arithmetic guarantees that make this product trustworthy will regress silently.
   The golden-master harness is the deliverable that makes the rest safe.
2. **Inventory is genuinely hard.** Semi-additive aggregation, snapshot-date semantics, a
   change-free ranking blend and duration-based novelty are four real capabilities, not
   configuration. Anyone promising "inventory by configuring the UI" before Phase 4 is
   wrong.
3. **The contract can be wrong in ways the model cannot detect.** A KPI declared
   `additive` that is not will produce confident nonsense. Mitigation: the probe *verifies*
   aggregation numerically rather than trusting the declaration, and refuses to publish on
   a failed verification.
4. **The LLM sees a bigger surface.** More comparison kinds means more ways to word a
   number wrongly. Mitigation: rule packs are composed from existing tested primitives, and
   the fallback-passes-validation invariant is enforced per pack.
5. **Prompt decomposition can regress quality invisibly.** Mitigation: golden master
   covers deterministic artifacts, and a human read of one live artifact per template is a
   named acceptance step — not optional.
6. **Config surface growth.** ~200 config keys plus a contract per report. Mitigation:
   templates keep the *answered* question count at ~15, and the contract is schema-validated
   with the same anti-drift test that already protects `config.json`.
7. **Two ways to configure during migration.** Legacy derivation plus explicit contracts
   coexist for two releases. Mitigation: a hard removal date, and the golden master runs
   both paths until the flag flips.
