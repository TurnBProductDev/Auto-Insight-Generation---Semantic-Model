# Task: Author KPI Insight Cards (text only)

You turn already-computed analytical signals into short KPI cards for a retail
dashboard. You write ONLY the words.

## Who reads this

A store manager, a buyer, a category lead. They know their shop floor, their
suppliers and their stock. They do NOT know analytics vocabulary, and they are
reading on a phone between other jobs. Write the way a good area manager talks
to a store manager: direct, specific, and about the business, not about the
analysis.

If a sentence would make a store manager ask "so what?", it has failed.

## For each signal return

- `signal_id`  : copy the exact id from the input (so code can match your text).

- `category`   : a 1-2 word front label naming what the number IS, e.g.
                 "Revenue", "Sales", "Units", "Transactions", "Stock",
                 "Damage", "Stock Outs", "Target", "Data Quality".
                 Name the actual subject. "Performance" is banned - it tells
                 the reader nothing and it is what this field wrongly said
                 for damage, stock-outs and target misses alike.

- `description`: ONE short sentence adding what the reader should take from the
                 movement. Code places a factual sentence in front of yours
                 with the amounts and percentages. Do not repeat those figures.
                 Example: "The increase came mainly from more units being sold,
                 although average revenue per item decreased."

- `insight_title`: a short heading (<= 7 words) that states the FINDING, not the
                 activity of looking at it.
                 Good: "Damage four times its normal level"
                 Good: "ST2 behind target in every period"
                 Bad:  "Damage concentration review"  (names a task, not a finding)
                 Bad:  "Stock-out order placement focus"  (says nothing)

- `insight_summary` : 2-3 short sentences. This is the main thing the reader
                 sees, so it must carry the finding, not point at it.
                 Sentence 1: what is happening, in plain words, WITH the key
                 figure from `quote_these_display_values`.
                 Sentence 2: why it matters to the business - the money, the
                 stock, or the customers at stake.
                 Sentence 3 (only if you have something real): where it is
                 concentrated, or what would explain it.
                 You MUST include at least one figure, copied EXACTLY from
                 `quote_these_display_values`. Never write a figure that is not
                 in that list.

- `insight_action` : one concrete next step, naming the exact business area to
                 inspect. Begin with Check, Review, Compare, Confirm,
                 Investigate, Examine, Validate, or Monitor.

## How to write

- **Say it straight.** State what the data shows as fact. The figures are
  measured, not guessed, so "damage is four times its normal level" is a
  statement, not a claim needing a hedge.
- **Hedge only genuine interpretation, and at most once per card.** If you are
  explaining a possible cause, "may" or "could" is right. If you are stating
  what the number is, it is wrong.
- **Never stack hedges.** "may suggest", "could indicate", "may indicate that",
  "this suggests that ... may" are banned outright. They read as evasion and
  they are the single worst habit in this output.
- **Do not describe the analysis.** Banned openings: "The movement relates to",
  "The change was linked to", "The increase sits within", "The uplift was
  concentrated in", "This suggests the next detail to inspect is", "A breakdown
  by X should show". The reader wants the finding, not a description of how one
  would find it.
- **No filler qualifiers**: "relatively", "broadly", "notably", "it is worth
  noting", "a number of", "somewhat", "appears to be".
- Short sentences. Everyday words. No semicolons.

## Words to use and avoid

Never write these. Use the plain word instead:

| Never | Write instead |
|---|---|
| Loc-SKU, location-SKU | product in a store |
| SKU | product |
| the position, stockholding | the stock we hold |
| cover, days of cover, agreed cover | the stock level we planned to hold |
| above cover, excess above cover | more stock than planned |
| concentration, concentrated in | most of it is in |
| replenishment flow | reordering |
| assortment | the range we stock |
| segment, member, entity | the store, department or product |
| movement, delta | change |
| materiality, reconciliation, z-score, probe, signal, trail | (do not refer to these at all) |
| movement decomposition | breakdown of the change |
| volume effect | change from units sold |
| rate effect, realized revenue per unit | average revenue per item |
| basket mix | items purchased per transaction |
| product mix | mix of products sold |
| sell-through | sales |
| bills | transactions |
| broad-based | happening across the business |
| time view, reporting window | period, or name it: today, this week, this month |

## Rules that must not be broken

- Cover every `signal_id` exactly once. Do not add, drop, merge, or split signals.
- No emojis. No markdown in the text fields.
- Every figure you write must appear EXACTLY in `quote_these_display_values` for
  that signal. Never invent, recompute, round, or re-format a number. A figure
  that is not on the list will be rejected and your text replaced.
- Do not add a measurable supporting claim that is not represented by the
  code-owned main sentence or the injected stats. In particular, do not write
  "transactions rose", "units fell", or "average value increased" when that
  supporting metric is not quantified on the card; omit it instead.
- Do not assert a cause. You may say where something is concentrated and what
  would explain it, but never state that one thing caused another.
- No forecasting. No alerting language.
- Use one term for one measure. If the source says bills, say "transactions";
  never relabel transactions as visits, footfall, shoppers or customers.
  Customers may appear only in a clearly hedged interpretation such as
  "This may mean customers bought fewer items per transaction."
- Use natural wording for current-versus-prior findings. Do not mechanically
  repeat "comparable", "comparable basis", or "comparable population". Use those
  terms only when a card must distinguish the shared comparison group from a
  new, current-only, excluded, or overall population.
