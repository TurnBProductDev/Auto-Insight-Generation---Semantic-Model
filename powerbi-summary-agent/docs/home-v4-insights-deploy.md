# Home Ver 4: Top Insights and the executive brief — deployment runbook

For the owner. Nothing here has been deployed. Claude cannot write Container Apps job
secrets, so the secret steps below are yours. The Web App plan is
`TurnB_ScanB_WebApplication_latest/docs/home-v4/PLAN.md` (Phase 9).

Order matters only for what the reader sees. Each piece fails safe on its own: until a
blob exists the AI Bot answers 404 and Home shows its fallbacks (the reports' headlines
for the summary, the KPI feed's positive findings for Top Insights).

1. Web App deployed with Home Ver 4 (PLAN 9.1).
2. AI Bot deployed with `GET /kpi/brief` and `GET /kpi/highlights`; the Web App's UAT
   `appsettings.json` gets `FastApi:KpiBriefPath=/kpi/brief` and
   `FastApi:KpiHighlightsPath=/kpi/highlights` (PLAN 9.2).
3. The Auto-Insight steps below (PLAN 9.3).

## 1. Build one dated image

From `powerbi-summary-agent/`:

```powershell
az acr build --registry insightgenacr --image insightgen-agent:<yyyymmdd>-home-v4 --no-logs .
az acr task list-runs --registry insightgenacr -o table     # wait for Succeeded
```

`--no-logs` is required on Windows: log streaming crashes on pip's progress bar and still
reports exit 0. Point only the jobs below at the new tag; the others keep theirs.

## 2. Top Insights: three existing jobs

`ai_content_highlights` (default off) makes each report add its facts to
`sb-mart/ai-content/kpi/client/highlights.json` after its own blobs. A failure shows as
`highlightsStatus: "failed: ..."` in the job's printed receipt and never fails the report.

For the Daily Sales job (`insightgen-sbmart-daily-sales`), the Target Tracker job
(`insightgen-sbmart-target-daily`) and the Sales YoY job (`insightgen-sbmart-yoy-daily`):

Images in use on 2026-10-01: Daily Sales and Target Tracker run
`20260929-home-scorecard-3` (built 29 Sep 10:53 UTC); the new image adds only the Home
Ver 4 code to it. Sales YoY still runs `20260916-narrated-cost`, so moving it also ships
the 16–29 Sep changes the other two already run (`src/tools/ai_tier.py`,
`src/tools/api_payloads.py`, `prompts/scorecard_lines_prompt.md`). Run it once by hand
after the switch and read its receipt.

1. Decode the deployed config secret `agent-config-b64` and diff it against the repo's
   `config/sbmart-*/config.json`. **Deployed configs lag the repo**: add only
   `"ai_content_highlights": true` to the deployed one unless you mean to ship the other
   differences too.
2. Write the secret back (base64 of the edited JSON). On Windows, `az` runs through
   `cmd.exe`, whose command line stops at 8,191 characters: the Sales YoY config is
   larger than that once encoded and fails with "The command line is too long" (nothing
   is written). Put `agent-config-b64=<base64>` in a file (ASCII, no newline) and pass
   `--secrets "@<file>"`; delete the file afterwards.
3. `az containerapp job update -n <job> -g Summary_generator_PBI --image insightgenacr.azurecr.io/insightgen-agent:<tag>`

Optional: `ai_content_highlights_per_report` (default 2) and
`ai_content_highlights_max_items` (default 8).

## 3. The executive brief: a new job, `insightgen-sbmart-brief`

It reads what the three reports published (their summaries, the KPI feed, Top Insights)
and writes `sb-mart/ai-content/kpi/client/brief.json`: one sentence per report, written
by the model from that report's facts and checked figure by figure, falling back to the
report's own headline. It makes no Power BI query.

- **Create it** from the settings of an existing SB Mart job (same resource group,
  registry, identity with access to `turnbtestblobstorage`, and the same Azure OpenAI
  environment: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`).
- **Image:** the dated tag from step 1.
- **Environment:** `AGENT_RUNNER=executive_brief`; `AGENT_CONFIG_B64` from a new secret
  `agent-config-b64` = base64 of `config/sbmart-brief/config.json` with
  `"ai_content_executive_brief": true` (the repo copy ships with it off). No rules
  secrets are needed. `AGENT_PUBLISH` unset (a scheduled run publishes).
- **Schedule:** after the last of the three report jobs has finished, e.g. 45 minutes
  after the latest of their cron times
  (`az containerapp job show -n <job> -g Summary_generator_PBI --query properties.configuration.scheduleTriggerConfig.cronExpression`).
  If it runs before a report, that report's line uses yesterday's summary.
  On 2026-10-01 the three ran at 06:50 (YoY), 07:15 (TT) and 07:45 (DS) UTC and each
  finished within 2 minutes, so `30 8 * * *` (UTC; 14:00 IST) fits.
- **Not needed:** `AGENT_REPORT_ID` (the value `target_tracker` would route the job to
  that report instead), `AI_CONTENT_PUBLISH_ENABLED` (the brief config already sets
  `ai_content_publish_enabled: true`).
- **Timeout:** 600 seconds is ample (at most two model calls).
- **Reports covered:** `brief_reports` in the config (slug, name, Power BI report GUIDs,
  copied from each report's own config). Add an entry when a new report should speak.

## 4. Check

1. Run each job once by hand (`az containerapp job start -n <job> -g Summary_generator_PBI`).
2. In the logs: the Daily Sales and Target Tracker jobs print `"highlightsStatus": "ok"`;
   the brief prints `"status": "ok"`, `"published": true` and each line's `mode` (`llm`,
   or `headline` where the model's sentence failed validation twice). The Sales YoY job
   does not print its receipt: check `highlights.json` for `reportSlug: "sales_yoy"`
   items stamped with the run day instead. Logs are in the job environment's workspace
   (customerId `bfd2ac34-ded1-4231-a742-78de691a97bc`), table `ContainerAppConsoleLogs_CL`,
   filtered on `ContainerGroupName_s` containing the execution name.
3. The blobs exist in `turnbtestblobstorage/sb-mart/ai-content/kpi/client/`.
4. The AI Bot answers 200 on `/kpi/brief` and `/kpi/highlights`; Home's summary paragraph
   changes to the brief (`#sbExec` gets `data-source="live"`) and Top Insights shows the
   published facts.

## Rollback

Set `ai_content_highlights` / `ai_content_executive_brief` back to false (or suspend the
brief job), and delete the two blobs if they must disappear at once. Home falls back to
the headlines and the feed by itself.

## Know before you look

SB Mart's warehouse stopped loading in mid-September 2026. Until it resumes, the brief and
Top Insights describe that old data; the brief's `dataAsOf` says which day.
