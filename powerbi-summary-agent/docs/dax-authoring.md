# How DAX planning & generation works

Nodes 4-7 of the pipeline (`src/graph.py`) decide what to ask the semantic
model and write the actual DAX to ask it - no fixed query templates.

## Before

The planner could only pick one of 5 hardcoded shapes
(`overall_totals` / `topn_dimension` / `time_summary` / `count` /
`distribution`), and a Python template mechanically filled in the DAX for
whichever shape was picked. No reasoning about the model happened - just
slot-filling into a fixed menu.

## Now

**Node 4 - `dax_planner.py` + `prompts/dax_planner_prompt.md` (LLM).**
Given the model's real tables/measures/columns, the LLM decides what's
actually worth asking for *this* model and writes each as a free-text
`intent` - e.g. "top 15 SECTION rows by [SALES], descending" or
"DEPARTMENT crossed with LOC_CODE, summarized by [SALES], top 20 by SALES
descending". No fixed vocabulary of query types - it can plan totals,
top/bottom-N, multi-dimension crossings, filtered slices, whatever the
model's structure supports.

**Node 5 - `dax_generator.py` + `prompts/dax_generator_prompt.md` (LLM).**
One LLM call per planned intent, writing the real `EVALUATE` DAX statement
directly. Hard rules baked into the prompt: exactly one `EVALUATE`, only
reference real object names given to it, wrap anything that can return more
than one row in `TOPN(n, ...)`.

**Node 6 - `dax_validator.py` (deterministic, no LLM).**
Regex-parses every `'Table'[Column]` and bare `[Measure]` token straight out
of the generated DAX text and checks it against the real model metadata -
the guardrail against hallucinated names. This is the same check the old
system did on structured template fields; it just runs on free-form text now.
Anything that fails is marked `skipped` but kept for Node 7, not discarded.

**Node 7 - `execute_dax` in `graph.py` (one-shot repair loop).**
Runs every valid query. Anything the validator skipped, or anything that
executed but Power BI rejected (e.g. a query referencing a measure whose
formula points at a table that no longer exists), gets sent back to the LLM
**once** with the exact error text, asked to fix it, re-validated, and
re-run - before finally being recorded as failed with the real error.

## Example, from a live run

Given nothing but the connected model's metadata, the planner produced (on
its own, unprompted for any of these specifically): a grand-totals snapshot,
top locations by sales, top departments by sales, a **bottom-N "shortfall"
view** of underperforming sections, a **location x department matrix**, a
sales trend over time, a **weekly breakdown**, and a **day-of-week
breakdown**. The matrix and bottom-N views are impossible to express in the
old 5-shape system.

## Known limitation

The repair loop only sees measure **names**, not their DAX formulas (even
though `metadata_reader.py` already fetches each measure's `expression` -
it's just not passed to the generator/repair prompts). So if a measure's
*name* looks fine but its internal formula references something broken, the
repair attempt can't diagnose which measure is actually at fault and may
drop the wrong one. Feeding measure expressions into the repair prompt would
close this gap.
