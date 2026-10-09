"""The executive brief on the Web App's Home page: one sentence per report.

Home's banner opens with an "AI Executive Summary". Until this existed the
Web App joined the reports' own headlines into it. This package writes it
from what the reports have ALREADY published for the client, after the last
report job of the morning:

    facts      read the client's published content: each report's current
               summary, today's KPI feed and Top Insights, as one fact sheet
               per report (the only thing the model is shown)
    select     which reports speak, in what order: the most severe card or
               figure first, then how many findings share that severity
    author     ONE sentence per selected report and a few suggested questions,
               written by the model from that report's facts only
    validate   every figure in a sentence must be in its report's facts; no
               causes, forecasts, jargon or invented comparisons; one sentence,
               35 words at most. A line that fails twice falls back to the
               report's own headline, so a line is always true
    publish    ai-content/kpi/client/brief.json, in the v1 envelope
    run        the job: ``python -m src.brief.run --config <config>``;
               in a container, ``AGENT_RUNNER=executive_brief``

Behind ``ai_content_executive_brief`` (default off): off, the job reads and
writes nothing. The AI Bot serves the blob at GET /kpi/brief and the Web App
keeps only the lines about reports the reader may open. Contract: Web App
``docs/home-v4/PLAN.md`` section 5.1.
"""
