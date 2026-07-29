# Central Business Repository

The authoritative, human-maintained record of **what the business means** by each
report, metric, entity, and rule that the Auto-Insight-Generation agent reasons over.

This repository is deliberately **above any single tool**. The agent is its first
consumer, not its owner. Analysts, BI developers, and business managers all read and
amend it, and it must stay readable to someone who has never opened the codebase.

---

## Why this exists

The agent's core invariant is that deterministic code computes and validates while the
LLM only selects and phrases. That invariant protects arithmetic. It does **not**
protect meaning. Nothing in code knows that `CFH022` has no prior-year trading history
and must sit outside every like-for-like figure, that footfall lives on a different
table from revenue so both must be scoped together, or that a 48% category decline
breadth is tolerable in this business but not in another.

Get that wrong and the arithmetic stays perfect while the answer is off by ten
percentage points — which is exactly what
[R01 §5.2](reports/R01-retail-brand-mis.md#52-the-scoping-defect-now-quantified)
documents.

That knowledge lives here. Without it, every new run and every new report re-derives
business meaning from column-name guesswork.

---

## Structure

```
docs/business-repository/
├── README.md                       <- you are here: index, conventions, onboarding
├── 00-global-standards.md          <- cross-report doctrine (applies to ALL reports)
├── _TEMPLATE-report-profile.md     <- copy this to add a report
└── reports/
    └── R01-retail-brand-mis.md     <- one profile per report
```

Two layers, and the split is load-bearing:

- **Global standards** — comparability doctrine, the shared metric dictionary, entity
  master, calendar conventions, DAX constraints, governance. Written once. A new
  report inherits all of it.
- **Report profiles** — only what is *specific* to that report: its semantic model,
  its grain, its measures, its known data-quality traps, its owner. A profile never
  restates global standards; it only records **deviations** from them, and every
  deviation needs a stated business reason.

---

## Report index

| ID | Report | Semantic model | Domain | Status | Owner |
|---|---|---|---|---|---|
| [R01](reports/R01-retail-brand-mis.md) | Retail Brand MIS (Monthly Brand Performance) | `MIS_BASE_FILE_MONTHLY_BRAND_TB` | Retail — sales performance | Active, **live-verified 2026-07-28** | *unassigned* |

Add a row here whenever you add a profile. This table is the entry point.

---

## How this feeds the agent

The agent reads exactly **one** file per run: `business_rules.md`, taken from the
directory beside the active `config.json` ([`file_io.read_business_rules`](../../powerbi-summary-agent/src/tools/file_io.py#L43)).
That file is injected into **every** LLM node as an authoritative system-prompt block.

So the flow is a **compile**, not a copy:

```
docs/business-repository/           (source of truth, comprehensive, human-facing)
        │
        │  hand-compiled: extract only the rules that change agent behaviour
        ▼
config/<report>/business_rules.md   (lean, directive, agent-facing)
        │
        │  read by Node 1, injected into every LLM prompt, snapshotted per run
        ▼
outputs/business_rules_snapshot.md  (audit trail: the exact rules in force)
```

### What belongs in the compiled file

`business_rules.md` is prepended to every prompt in both branches, so length is not
free — it costs tokens on every LLM node. But the file also has to be **verifiable by a
business reader**, and a bare imperative cannot be checked. The working split:

**Include** — the rule itself, stated as one bold imperative sentence with a stable
`BR-nn` ID; the reason it exists; a verification marker; and a worked example **where
the example prevents a specific, known error**. BR-02 carries the 9.76pp scoping table
because that number is what makes an analyst take the rule seriously.

**Exclude** — anything that goes stale. Current-period findings ("CFH021 is carrying
the group", "CFH017 is declining") are *results*, not rules. Putting them here would
have the agent asserting last month's conclusions as standing fact. Structural
conditions that persist across runs (BR-07's CFH022 cutoff) do belong.

The test is not "is this short" but **"would a business reader be able to confirm or
deny this line, and does it still hold next month?"** If it fails either, it belongs in
the report profile instead.

**Current cost:** roughly 5,200 tokens per LLM call. Re-measure after any substantial
edit:

```bash
cd powerbi-summary-agent && python -c "import sys; sys.path.insert(0,'.'); \
from src.tools import file_io; print(len(file_io.read_business_rules())//4, 'tokens')"
```

### Rules that must be mirrored in code

Prose rules are prompt-level guidance and an LLM can drift from them. Some rules are
additionally **machine-enforced**, and those have a mandatory second home in
`config.json`:

| Business rule | Prose home | Machine-enforced mirror |
|---|---|---|
| Comparable entity population | `business_rules.md` | `insight_comparable_population` |
| Entities excluded from like-for-like | `business_rules.md` | `insight_excluded_entities` |

If these two disagree, the deterministic gate (`baseline_scope` + `scope_validator`)
wins for anything it covers and the prose silently wins everywhere else — producing a
report that is internally inconsistent. **Change them in the same commit, always.**

---

## Adding a new report

The agent already supports multiple reports natively, because `read_business_rules()`
resolves `business_rules.md` relative to the config file passed on the command line.
Give each report its own directory and it gets its own rulebook for free:

```
powerbi-summary-agent/config/
├── config.json            + business_rules.md      <- R01 (default path)
└── reports/
    └── R02/
        ├── config.json    + business_rules.md      <- R02
```

```bash
python -m src.main                                        # R01
python -m src.main --config config/reports/R02/config.json  # R02
```

Onboarding checklist:

1. Copy `_TEMPLATE-report-profile.md` to `reports/R0n-<slug>.md` and fill it in.
2. Add the row to the report index above.
3. Record anything genuinely cross-report (a new shared metric, a new entity) in
   `00-global-standards.md` instead — do not duplicate it into the profile.
4. Create `config/reports/R0n/config.json` and compile the profile down to its sibling
   `business_rules.md`.
5. Mirror the comparable/excluded entity lists into that `config.json`.
6. Run once and read `outputs/business_rules_snapshot.md` to confirm the rules the
   agent actually loaded are the ones you intended.

---

## Conventions

- **Plain business English.** These files are read by managers, and their content is
  fed verbatim to a language model. Both audiences do better with prose than with
  pseudo-code.
- **State the reason, not just the rule.** "Exclude CFH022" is a rule someone will
  delete in six months. "Exclude CFH022 because it opened mid-year and has no prior-year
  trading history" survives.
- **Mark confidence explicitly.** Every claim carries one of:
  - **[VERIFIED]** — confirmed against the live model or a committed artifact, with the
    source named.
  - **[INFERRED]** — deduced from repo evidence, consistent but not directly confirmed.
  - **[UNVERIFIED]** — needs a live check or a business owner's answer.
  Never silently promote a tier. An unverified assumption that reads as fact is how a
  wrong number reaches a board pack.
- **No emojis**, matching the agent's global output rules.
- **Date all revisions** in the profile's change log. A rule is only auditable if you
  can say when it took effect.
