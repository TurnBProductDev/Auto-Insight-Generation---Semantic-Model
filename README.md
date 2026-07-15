# Power BI AI Analysis Agent

Turn a Power BI semantic model into AI-generated analysis — the user never writes
any DAX. Two related pieces:

- **`pbi_agent.py`** — a minimal MVP: headless MSAL auth + a single DAX round-trip
  against the Power BI REST `executeQueries` API. Proves the authentication approach.
- **[`powerbi-summary-agent/`](powerbi-summary-agent/)** — the full product: a
  LangGraph + LangChain multi-agent pipeline that inspects the model, auto-generates
  and executes its own DAX, and produces **two reports in one concurrent run**:
  a descriptive `report_summary.md` (*what* the numbers are) and an investigative
  `insight_report.md` (*why* they moved).

See **[powerbi-summary-agent/README.md](powerbi-summary-agent/README.md)** for the
architecture and full setup.

## Quick start

```bash
git clone <this-repo>
cd <repo>/powerbi-summary-agent

# Create your own copies of the gitignored template files:
cp .env.example .env                                     # LLM + Power BI creds
cp config/config.example.json config/config.json         # tenant/dataset GUIDs
cp config/business_rules.example.md config/business_rules.md   # optional

# ...edit those three files with your values, then:
pip install -r requirements.txt
python -m src.main
```

The first run opens a browser once to authenticate; every run afterwards is silent
(a refresh-token cache is written to `.pbi_token_cache.json`, which is gitignored).

## Authentication

Power BI auth is **headless MSAL with a persisted refresh-token cache** using the
well-known Azure PowerShell public client (`CLIENT_ID`) — no app registration
required. Requires the tenant's **Execute Queries** setting enabled and read/build
permission on the dataset.

## What is *not* in this repo (and why)

These are gitignored so nothing sensitive is published. Recreate them from the
`*.example.*` templates:

| Ignored path | What it holds |
|---|---|
| `powerbi-summary-agent/.env` | LLM API keys / endpoints |
| `.pbi_token_cache.json` | MSAL refresh token |
| `powerbi-summary-agent/config/config.json` | Your tenant/workspace/dataset GUIDs |
| `powerbi-summary-agent/config/business_rules.md` | Your company calculation logic |
| `powerbi-summary-agent/outputs*/` | Generated reports (real business data) |

## License

No license file is included yet — add one before treating this as open source.
