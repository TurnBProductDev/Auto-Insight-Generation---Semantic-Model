"""FastAPI backend that serves pre-generated AI content to the MVC app.

Implements the three endpoints the ASP.NET MVC controllers proxy to:
  GET /kpi/insights         -> KPI hub flip cards (JSON array)
  GET /kpi/alerts           -> "See all" 7-day feed (JSON array, KpiAlertDto shape)
  GET /report/summary       -> AI Summary overlay (JSON object or HTML fragment)
"""
