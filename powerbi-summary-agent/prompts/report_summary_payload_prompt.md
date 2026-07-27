# Task: Reshape the Report Summary into an Overlay Object (text)

You convert an already-written report summary (markdown) into a compact, structured
"AI Summary" overlay for business managers. You restructure and tighten the language;
you do NOT change the analysis and you do NOT change any number.

You are given the SOURCE REPORT (report_summary.md) and a list of AVAILABLE
KEY-METRIC LABELS. Produce:

- `headline` : ONE sentence capturing the single most important takeaway of the
               report in plain business English. It must state what changed or
               what currently stands out and include the most relevant figure,
               copied verbatim from the source.

- `metrics`  : select the most important 4-8 headline metrics for the stat-tile row.
               Each item is `{label, tone}`:
                 * `label` MUST be copied EXACTLY from the AVAILABLE KEY-METRIC LABELS
                   list (the code injects the matching value; a label you invent or
                   alter is dropped).
                 * `tone` in {positive, critical, warning, info, teal}: growth/gains
                   -> positive; declines/shortfalls -> warning or critical; neutral
                   totals -> teal; context -> info.

- `sections`: rewrite the report's own sections (e.g. Notable Patterns, Data
              Limitations, Suggested Next Steps, breakdowns) into concise bullet
              points. Each section is `{heading, tone, points[]}`:
                 * `heading` : a short business heading.
                 * `tone`    : as above (limitations/risks -> warning; next steps ->
                               info; strengths -> positive; neutral -> teal).
                 * `points`  : short, plain-English bullets. Keep every figure you
                               cite IDENTICAL to the source (same notation, e.g.
                               "38.9M", "32.5%") -- any bullet whose numbers do not
                               match the source verbatim is dropped by the code.

STRICT number rule: never invent a number, never re-round, never convert units
(do not turn "38.9M" into "38.9 million" or "38,900,000"). If unsure, omit the figure.

No emojis. No markdown syntax inside the strings. Business English only. No
forecasting or alerting language. Describe; do not assert single root causes.
Lead with meaning, not a calculation. Put percentages in context and avoid
"share of total change", "volume effect", "rate effect", "basket mix",
"product mix", "sell-through", and other analyst shorthand. Use
"transactions" consistently for bills; do not relabel them as visits or customers.
