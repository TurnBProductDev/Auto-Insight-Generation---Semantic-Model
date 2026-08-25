# SB Mart Target Tracker business rules

- This report compares actual sales with assigned targets. It does not run the YoY
  pipeline; the separate SB Mart Sales vs Previous Year report owns that comparison.
- Use ST1, ST2, ST3 and ST4. Exclude ST5 from Target Tracker because its last target is
  31 May 2026, its last sale is 13 June 2026, and it has no July sales or target.
- Report all figures in USD (`target_tracker_currency`). The model's own Metrics
  description table labels these sales figures QAR, but this report intentionally
  publishes in USD by configuration - never restate the model's own QAR label.
- Weeks run Monday to Sunday.
- Never invent a cause for a target gap. The model supports where and when, not why.

