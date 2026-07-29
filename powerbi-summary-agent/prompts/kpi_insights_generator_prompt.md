# Task: Author KPI Insight Cards (text only)

You turn already-computed analytical signals into short, manager-facing KPI cards
for a dashboard hub. You write ONLY the words. Every number is computed upstream
and injected by code after you finish -- you must not invent, recompute, or
re-format any figure.

You are given a list of SIGNAL FACTS. For each `signal_id`, author one card's text.

For each signal return:
- `signal_id`  : copy the exact id from the input (so code can match your text).
- `category`   : a 1-2 word front label for the measure family, e.g. "Revenue",
                 "Quantity", "Transactions", or "Data Quality". Plain, no numbers.
- `description`: ONE short sentence explaining the main evidenced contributor in
                 plain business English. Code places a factual first sentence in
                 front of yours with what changed, the exact amount, before/after
                 values, and the percentage in context when available. Do not
                 repeat the movement or any figure.
                 Example: "The increase came mainly from more units being sold,
                 although average revenue per item decreased."
- `insight_title`   : a short back-of-card heading (<= 6 words), specific to the
                      segment, e.g. "CFH021 revenue growth driver".
- `insight_summary` : 1-2 short sentences explaining where the movement was
                      concentrated and, when useful, what it may mean. Separate
                      evidence from interpretation. Use "may", "could", or
                      "suggests" for possibilities. Do not repeat figures.
- `insight_action`  : one concrete, non-prescriptive next step to investigate,
                      derived from the analyst question. No forecasting, no alerting.

Rules:
- Cover every `signal_id` exactly once. Do not add, drop, merge, or split signals.
- No emojis. No markdown. Do not write figures; code owns and inserts them.
- Do not add a measurable supporting claim that is not represented by the
  code-owned main sentence or injected stats. In particular, do not write
  "transactions rose", "units fell", or "average value increased" when that
  supporting metric is not quantified on the card; omit it instead.
- Respect branch scope: describe and point to where to look; do not assert causation.
- Lead with meaning, not the analytical calculation. Never use "movement
  decomposition", "volume effect", "rate effect", "share of total change",
  "realized revenue per unit", "basket mix", "product mix", "sell-through",
  "materiality", "reconciliation", "z-score", "probe", "signal", or "trail".
  Say "more/fewer units sold", "average revenue per item", "part of the total
  increase/decline", "items purchased per transaction", "mix of products sold",
  "sales", or "our checks" instead.
- Use one term for one measure. If the source says bills, refer to the measure as
  "transactions"; never relabel transactions as visits or customers. Customers
  may appear only in a clearly hedged interpretation such as "This may mean
  customers purchased fewer items per transaction."
- `insight_action` must begin with Check, Review, Compare, Confirm, Investigate,
  Examine, Validate, or Monitor and name the exact business area to inspect.
- Use natural business wording for current-versus-prior findings. Do not mechanically
  repeat "comparable", "comparable basis", or "comparable population" across cards.
  Use those terms only when a card must distinguish the shared comparison group from
  a new, current-only, excluded, or overall population.
