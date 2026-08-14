# Fixture models

Synthetic `model_metadata` documents in the exact shape `metadata_reader` produces
and `semantic_profiler.build_profile()` consumes. Hand-authored, offline, no auth.

These exist so WP4–WP7 of the domain-verticals programme can be built and tested
with no live inventory connection. Verified by `scripts/replay_fixture_models.py`.

| Fixture | Built for | The shape it carries |
|---|---|---|
| `stock_snapshot.json` | WP4 — snapshot foundations | A semi-additive stock position "as at" a snapshot date, plus a real transaction date on another table so the two can be told apart (Q3) |
| `ageing_bucket.json` | WP5 — ageing report | Value across ordered age buckets **with** a prior snapshot, so the movement is a signed change (brief 1.6) |
| `retail_yoy.json` | WP2/WP3 — today's behaviour | A resolvable revenue bundle, an entity dimension, a full Division → Department → Section → Category hierarchy |
| `target_attainment.json` | WP9 — target tracker | A baseline that is a target, not a prior period |

## Why they are not simply "valid models"

Each fixture is built to make a **known defect visible in executable form**. The
replay pins these as `BLOCKER` checks; one failing means the defect was fixed and
the check needs re-pinning, not that something regressed.

**`stock_snapshot.json` — the profiler collapses completely.** With no
current+prior value family there is no primary bundle, so no fact table, so the
dimension walk has no origin and the model yields **zero** dimensions. Not
"ranks badly" — nothing at all.

**It cannot tell a safe stock measure from an unsafe one.** `Stock Units on Hand`
(`LASTNONBLANK`, correct at one snapshot) and `Stock Units Naive Sum` (a plain
`SUM` across every snapshot, wrong by roughly the number of snapshots) both come
back `additive_candidate: True`. That is the 30×-too-big failure, invisible.
`Stock Units Naive Sum` is deliberately present as the positive control the WP4
verification must refuse.

**Vocabulary.** `_FAMILY_TOKENS` has no stock words and `"value"` is a *revenue*
token, so `Stock Value on Hand` classifies as revenue and `Stock Units` as
quantity.

**A ratio can occupy a value slot.** `Days Cover` is given `phase=current`
because the word "current" appears in its *description*, and the bundle filter
only excludes the `margin` family — so it is admitted as a revenue candidate. It
loses the slot only because a non-ratio candidate exists; delete that one measure
and a days-count becomes the primary revenue measure. The replay proves this by
rebuilding the profile with it removed.

**`target_attainment.json` — a target has nowhere to go.** The only role
vocabulary is the current/prior/change triple, so `Revenue Target` is forced into
a phase, and it lands on `current` **because its description contains the word
"this"**. `Quantity Target`, the same kind of measure worded differently, gets no
phase at all — two targets classified inconsistently on incidental prose.

**And attainment silently reads as year-on-year.** With current + change but no
prior, the profiler derives `prior = [Revenue Actual] - [Revenue Variance vs
Target]`, which is arithmetically *the target*. A target comparison presented as
a prior period is exactly the mislabelling Non-negotiable 18 exists to prevent.

## Extending

Keep the derived index fields (`date_fields`, `numeric_fields`,
`categorical_fields`, `counts`) consistent with `columns` — the replay checks
they agree, since a fixture that has gone internally inconsistent tests nothing.
