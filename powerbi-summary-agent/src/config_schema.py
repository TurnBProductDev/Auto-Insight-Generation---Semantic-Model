"""The single source of truth for every ``config.json`` key.

Why this module exists
----------------------
Before it, ~200 configuration keys were read as ``state.get("key", default)``
literals scattered across ~40 modules, with no schema and no validation. A key
missing from a config does not raise - it silently changes behaviour. That is
exactly how ``summary_r4_enabled`` / ``summary_r6_enabled`` stayed off in
production for weeks while the code that implements them shipped.

So this catalogue is authoritative in both directions:

* :func:`state_defaults` builds the pipeline's initial state, so ``main.py``
  cannot drift from the schema - there is only one copy of each default.
* ``scripts/replay_config_schema.py`` asserts the reverse: every config key any
  module reads, and every key any committed config sets, appears here with a
  matching default.

Every key carries three pieces of prose, because two different people read it:

``label``   a plain name a non-technical person recognises
``help``    what it does and what happens if it is wrong, in ordinary words
``detail``  the engineering note - shown in the UI behind "More detail"

and a ``tier`` that decides whether the onboarding wizard shows it at all by
default. Someone setting up a new client should meet about twenty questions,
not two hundred.

It is deliberately dependency-free (stdlib only, no ``src`` imports) so the
config UI, the CLI and the container entry point can all import it cheaply and
without triggering the pipeline's import graph.

Vocabulary in this file is generic - hierarchy role names, band-set names,
channel names. It contains no model-specific table, column, measure, or member
names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

SCHEMA_VERSION = 2

#: How much of the catalogue a given audience needs to see.
#:
#: ``essential`` - a new client cannot work until someone answers this.
#: ``standard``  - worth a look; the default is usually right.
#: ``expert``    - leave it alone unless you know exactly why you are changing it.
TIERS: tuple[str, ...] = ("essential", "standard", "expert")


# ---------------------------------------------------------------------------
# Wizard groups. Order is the onboarding order, and the order is the product:
# several keys cannot be sensibly chosen before the probe has reported what the
# semantic model actually exposes.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Group:
    id: str
    title: str
    blurb: str
    probe_driven: bool = False


GROUPS: tuple[Group, ...] = (
    Group(
        "connection",
        "Connect to your dashboard",
        "Tell the agent which Power BI dashboard to read, and which AI service writes the "
        "reports. Nothing else works until this is right.",
    ),
    Group(
        "scope",
        "Which shops to compare",
        "Comparing this year to last year only makes sense for shops that were trading in both "
        "years. A shop that opened in March has no 'last year' to compare against, and including "
        "it makes growth look worse than it is.",
        probe_driven=True,
    ),
    Group(
        "roles",
        "How your products are organised",
        "Most businesses group products in levels - Division, then Department, then Category. "
        "Here you say which levels get their own written story, and which just get a ranked "
        "table row. The check in the previous step found the levels your data actually has.",
        probe_driven=True,
    ),
    Group(
        "features",
        "What the reports include",
        "Switch whole sections of the report on and off. The defaults are sensible; the two "
        "marked as traps are the ones people forget, and forgetting them quietly removes a "
        "section rather than showing an error.",
    ),
    Group(
        "publishing",
        "Where the reports are saved",
        "There are three separate cloud destinations here, and they are easy to confuse. "
        "(1) The agent's own store - every client shares one container, kept apart only by a "
        "folder name, so getting that wrong overwrites another client's files. "
        "(2) Your app's storage - a container of its own per client, and this is the one your "
        "web app actually reads. "
        "(3) Private memory - what has already been reported, so tomorrow does not repeat today; "
        "no app ever reads it. The panel at the top of this step shows exactly what lands where.",
    ),
    Group(
        "summary_tuning",
        "Daily summary settings",
        "How the daily summary picks what to talk about, how often it repeats a topic, and how "
        "much data it is allowed to fetch. The defaults have been tuned on live data - change "
        "these only if the summary is repeating itself or missing something.",
    ),
    Group(
        "rag_calendar",
        "Targets and moveable holidays",
        "Set what counts as good, watch and bad for each measure, and tell the agent about "
        "holidays that fall on different dates each year. Without the holiday dates the agent "
        "can still spot that something odd happened, but it cannot say why.",
    ),
    Group(
        "insight_tuning",
        "Deep-dive settings",
        "How hard the agent digs for explanations, how unusual something has to be before it is "
        "worth mentioning, and how long it remembers what it has already told you. Almost "
        "everything here can be left alone.",
    ),
)

GROUP_IDS: tuple[str, ...] = tuple(g.id for g in GROUPS)

# Canonical hierarchy vocabulary offered by the UI. Mirrors
# ``summary_roles.HIERARCHY_LEVELS`` (asserted by the drift test); ``store`` is
# deliberately coverage-only and carries no hierarchy depth.
HIERARCHY_ROLES: tuple[str, ...] = (
    "division",
    "department",
    "section",
    "category",
    "subcategory",
    "product_group",
    "special_product_group",
    "brand",
    "product",
    "item",
    "sku",
)
COVERAGE_ROLES: tuple[str, ...] = ("store",) + HIERARCHY_ROLES

DELIVERY_CHANNELS: tuple[str, ...] = (
    "local_report",
    "history",
    "api_payload",
    "blob_report",
    "blob_history",
    "ai_content",
)

#: Plain-English names for the vocabulary the pickers offer.
ROLE_LABELS: dict[str, str] = {
    "store": "Store / branch",
    "division": "Division (broadest)",
    "department": "Department",
    "section": "Section",
    "category": "Category",
    "subcategory": "Sub-category",
    "product_group": "Product group",
    "special_product_group": "Special product group",
    "brand": "Brand",
    "product": "Product",
    "item": "Item",
    "sku": "SKU (narrowest)",
}

CHANNEL_LABELS: dict[str, str] = {
    "local_report": "The report file itself",
    "history": "The dated history record",
    "api_payload": "The app data file",
    "blob_report": "Upload of the app data file",
    "blob_history": "Upload of the history record",
    "ai_content": "Publishing into your app's storage",
}


# ---------------------------------------------------------------------------
# Key records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigKey:
    """One configurable key: what it is, what it defaults to, why it matters."""

    key: str
    type: str  # bool | int | float | string | guid | enum | list | object
    default: Any
    group: str
    #: Plain name shown as the field's title in the wizard.
    label: str
    #: What it does, in ordinary words. Shown under the field.
    help: str
    #: The engineering note. Shown behind "More detail"; never the only
    #: explanation of a setting.
    detail: str = ""
    tier: str = "standard"
    per_client: bool = False
    required: bool = False
    choices: tuple[str, ...] = ()
    #: Plain-English names for the enum choices, keyed by choice.
    choice_labels: tuple[tuple[str, str], ...] = ()
    item_type: str = "string"  # list element type
    item_choices: tuple[str, ...] = ()
    #: False for keys read only from ``state["config"]``; they are never copied
    #: into the graph state, and copying them there would change behaviour.
    in_state: bool = True
    #: True when ``main.py`` computes the state value rather than taking the
    #: plain default (fallback chains, env overrides, composed booleans).
    derived: bool = False
    #: Present in committed configs but read by no code. Kept so the drift test
    #: stays green and the UI can offer to strip it.
    dead: bool = False
    #: A destructive-default trap, in plain words, for the UI to surface before
    #: anything is deployed.
    warn: str = ""

    @property
    def advanced(self) -> bool:
        """Back-compatible view of the tier for anything still asking."""
        return self.tier == "expert"

    def json(self) -> dict:
        out = {
            "key": self.key,
            "type": self.type,
            "default": self.default,
            "group": self.group,
            "label": self.label,
            "help": self.help,
            "detail": self.detail,
            "tier": self.tier,
            "perClient": self.per_client,
            "advanced": self.advanced,
            "required": self.required,
            "inState": self.in_state,
            "derived": self.derived,
            "dead": self.dead,
        }
        if self.choices:
            out["choices"] = list(self.choices)
            out["choiceLabels"] = dict(self.choice_labels)
        if self.type == "list":
            out["itemType"] = self.item_type
            if self.item_choices:
                out["itemChoices"] = list(self.item_choices)
                out["itemLabels"] = {
                    choice: ROLE_LABELS.get(choice, CHANNEL_LABELS.get(choice, choice))
                    for choice in self.item_choices
                }
        if self.warn:
            out["warn"] = self.warn
        return out


def _k(key, type_, default, group, label, help_, detail="", **kw) -> ConfigKey:
    return ConfigKey(
        key=key, type=type_, default=default, group=group,
        label=label, help=help_, detail=detail, **kw,
    )


# ---------------------------------------------------------------------------
# 1. Connect to your dashboard
# ---------------------------------------------------------------------------

_CONNECTION: tuple[ConfigKey, ...] = (
    _k("tenant_id", "guid", "", "connection",
       "Organisation ID",
       "The ID of your Microsoft 365 organisation. Your Power BI administrator can give you "
       "this, or you can copy it from any Power BI web address.",
       "Azure AD tenant. Overridden by the POWERBI_TENANT_ID environment variable. Required, and "
       "a PASTE_-prefixed placeholder is rejected before the graph builds.",
       tier="essential", required=True),
    _k("workspace_id", "guid", "", "connection",
       "Workspace ID",
       "The ID of the Power BI workspace holding the dashboard. Open the workspace in Power BI "
       "and copy the long code from the web address.",
       "Power BI group ID. Required.",
       tier="essential", required=True, per_client=True),
    _k("dataset_id", "guid", "", "connection",
       "Dataset ID",
       "The ID of the data behind the dashboard - not the dashboard itself. If you only have a "
       "report link, paste the report ID into the box above this form and press "
       "'Find the dataset', which looks it up for you.",
       "Semantic model ID. A report ID is not a dataset ID: resolve it with "
       "GET /v1.0/myorg/groups/{workspaceId}/reports/{reportId}.",
       tier="essential", required=True, per_client=True),
    _k("output_folder", "string", "outputs", "connection",
       "Folder for generated reports",
       "Where the agent saves the reports it writes on this computer. Leave it as 'outputs' "
       "unless you are running two clients side by side and want their files kept apart.",
       "Relative to the project root. Must resolve to 'outputs' in the container: /app is "
       "root-owned and only /app/outputs is writable by the agent user.",
       tier="essential", per_client=True,
       warn="In the cloud this must be 'outputs', or the job cannot save anything."),
    _k("ai_provider", "enum", "azure_openai", "connection",
       "AI service",
       "Which AI service writes the report text. Use whichever one your organisation has set up.",
       "Overridden by the LLM_PROVIDER environment variable.",
       tier="essential",
       choices=("azure_openai", "anthropic", "openai"),
       choice_labels=(("azure_openai", "Azure OpenAI"), ("anthropic", "Anthropic (Claude)"),
                      ("openai", "OpenAI")),
       derived=True),
    _k("model", "string", "claude-sonnet-5", "connection",
       "AI model name",
       "Which version of the AI to use. If you chose Azure OpenAI above, this box is ignored - "
       "Azure decides from the deployment name set on the server instead.",
       "For Azure the AZURE_OPENAI_DEPLOYMENT environment variable routes the call, not this "
       "string."),
    _k("max_tokens", "int", 4096, "connection",
       "Maximum length of each AI response",
       "A safety ceiling on how much the AI can write in one go. Higher costs slightly more; "
       "too low and a long report gets cut off mid-sentence.",
       "Output token ceiling per LLM call."),
    _k("llm_max_retries", "int", 6, "connection",
       "Retries when the AI is busy",
       "How many times to try again if the AI service is temporarily overloaded.",
       tier="expert", in_state=False),
    _k("azure_openai_api_key_env", "string", "AZURE_OPENAI_API_KEY", "connection",
       "Azure key: environment variable name",
       "The NAME of the environment variable that holds your Azure key - never the key itself. "
       "Keys live outside this file so they are never saved or shared by accident.",
       tier="expert", in_state=False),
    _k("openai_api_key_env", "string", "OPENAI_API_KEY", "connection",
       "OpenAI key: environment variable name",
       "The NAME of the environment variable that holds your OpenAI key - never the key itself.",
       tier="expert", in_state=False),
    _k("anthropic_api_key_env", "string", "ANTHROPIC_API_KEY", "connection",
       "Anthropic key: environment variable name",
       "The NAME of the environment variable that holds your Anthropic key - never the key itself.",
       tier="expert", in_state=False),
    _k("execution_mode", "enum", "python", "connection",
       "How queries are sent",
       "Leave this on the standard setting. The other option exists only for an old workaround "
       "that is no longer needed.",
       "'powershell' applies to the summary branch only and exists for legacy reasons.",
       tier="expert",
       choices=("python", "powershell"),
       choice_labels=(("python", "Standard (recommended)"), ("powershell", "Legacy PowerShell"))),
    _k("fabric_definitions", "bool", True, "connection",
       "Read the formulas behind your measures",
       "Lets the agent look up how each of your measures is calculated, which makes its "
       "explanations more accurate. If your permissions do not allow it, the run carries on "
       "without it.",
       "Best-effort Fabric/TMSL enrichment recovering measure expressions, which executeQueries "
       "returns blank. Never fatal."),
    _k("powerbi_auth_mode", "enum", "auto", "connection",
       "How the agent signs in to Power BI",
       "Leave on automatic: it signs in as you when run on your computer, and as the server's "
       "own identity when run in the cloud.",
       "Env POWERBI_AUTH_MODE wins over this.",
       tier="expert",
       choices=("auto", "interactive", "managed_identity", "service_principal"),
       choice_labels=(("auto", "Automatic (recommended)"), ("interactive", "Sign in as me"),
                      ("managed_identity", "The server's own identity"),
                      ("service_principal", "A registered app")),
       in_state=False),
    _k("powerbi_query_api", "enum", "auto", "connection",
       "Query response format",
       "A technical detail of how data comes back from Power BI. Leave on automatic.",
       "Arrow for headless runs, JSON for interactive.",
       tier="expert",
       choices=("auto", "json", "arrow"),
       choice_labels=(("auto", "Automatic (recommended)"), ("json", "JSON"), ("arrow", "Arrow")),
       in_state=False),
    _k("powerbi_effective_username", "string", "", "connection",
       "Run as this user (row-level security)",
       "Only needed if your dashboard restricts what each person can see and you want the agent "
       "to see it as one particular person would. Leave empty otherwise.",
       "RLS impersonation.",
       tier="expert", in_state=False),
    _k("powerbi_rls_roles", "list", [], "connection",
       "Security roles to apply",
       "Only needed alongside the setting above. Leave empty otherwise.",
       "RLS roles.",
       tier="expert", in_state=False),
    _k("dataset_client_map", "object", {}, "connection",
       "Multiple datasets to one client",
       "Only needed if one client's app is fed by more than one dataset. Leave empty.",
       "Advanced ai-content publishing mapping.",
       tier="expert", in_state=False),
    # --- report identity (WP1) ----------------------------------------------
    # Before these existed, everything the agent remembers was filed under the
    # dataset alone, so two reports over one dataset shared one memory and
    # quietly overwrote each other. Leave them alone for a single-report client.
    _k("report_id", "string", "sales_yoy", "connection",
       "Short name for this report",
       "A short name for the report this job produces, in lowercase with underscores. It keeps "
       "each report's history separate, so two reports built on the same data do not overwrite "
       "what the other one remembers. Leave it as it is unless you are adding a second report.",
       "Scopes summary memory to <root>/<dataset>/reports/<report_id>/memory.json via "
       "kernel.scoping. A pre-WP1 store at the dataset root is copied in on first use, "
       "non-destructively. Overridden by --report and by AGENT_REPORT_ID.",
       tier="standard"),
    _k("report_name", "string", "Sales vs Previous Year", "connection",
       "Report title readers see",
       "The title printed at the top of the report and shown in the app. Write it the way you "
       "would say it out loud.",
       "Carried on ReportSpec.report_name. Presentation only - it is never part of any "
       "memory key, so renaming a report cannot reset its history.",
       tier="standard"),
    _k("report_domain", "string", "sales", "connection",
       "Kind of business question",
       "The kind of question this report answers - for example sales, or stock. It decides which "
       "set of business words and rules the agent uses.",
       "Selects the domain package (src/domains/<domain>). Only 'sales' exists today; the "
       "inventory domain arrives with WP4-WP7.",
       tier="standard"),
    _k("report_cadence", "enum", "daily", "connection",
       "How often it runs",
       "How often this report is produced. It sets how far back the agent looks before calling "
       "something new, so a weekly report does not repeat itself every day.",
       "Feeds ReportSpec.cadence; memory window and freshness thresholds read from it.",
       tier="standard",
       choices=("daily", "weekly", "monthly"),
       choice_labels=(("daily", "Every day"), ("weekly", "Every week"),
                      ("monthly", "Every month"))),
    _k("report_spine", "string", "period_over_period", "connection",
       "What this report compares against",
       "What the agent measures your numbers against. 'period_over_period' compares with the same "
       "time last year. Stock reports compare against your agreed stock policy instead. Leave it "
       "alone unless you are setting up a report that is not a year-on-year comparison.",
       "Selects the MeasurementSpine from kernel.spine.SPINE_REGISTRY. Only "
       "'period_over_period' is registered today; the inventory spines arrive with WP4. An "
       "unknown name falls back to period_over_period rather than failing the run.",
       tier="standard"),
    _k("chain_id", "string", "sales", "connection",
       "Group this report belongs to",
       "Reports in the same group share one 'why did this happen' investigation, so the agent can "
       "connect a finding in one report to a finding in another. Leave it as it is unless you are "
       "grouping reports together.",
       "Scopes insight memory to <root>/<dataset>/chains/<chain_id>/memory.json. Chain-scoped "
       "rather than report-scoped because WP8 pools a chain's evidence and runs the insight "
       "branch once over all of it - one memory, one consumer, no cross-report suppression.",
       tier="standard"),
)

# ---------------------------------------------------------------------------
# 2. Which shops to compare (probe-driven)
# ---------------------------------------------------------------------------

_SCOPE: tuple[ConfigKey, ...] = (
    _k("insight_comparable_population", "list", [], "scope",
       "Shops included in like-for-like comparisons",
       "The shops that were trading in both this year and last year, so comparing them is fair. "
       "Leave this empty and the agent works it out from your data each run - which is usually "
       "the right choice. Fill it in only if your business has an official list.",
       "Machine-enforced by baseline_scope + scope_validator and audited against the "
       "data-derived classification. Empty derives the population from data.",
       tier="essential", per_client=True),
    _k("insight_excluded_entities", "list", [], "scope",
       "Shops to leave out of year-on-year comparisons",
       "Shops that would distort the comparison - one that opened this year, or closed last "
       "year. They still appear in this year's totals; they are simply not compared against a "
       "year they were not trading in.",
       "Any query using prior/change metrics that includes one of these is rejected by the "
       "scope validator.",
       tier="essential", per_client=True),
)

# ---------------------------------------------------------------------------
# 3. How your products are organised (probe-driven)
# ---------------------------------------------------------------------------

_ROLES: tuple[ConfigKey, ...] = (
    _k("summary_focus_allowed_roles", "list", ["division", "department", "category"], "roles",
       "Levels that get a written story",
       "Which levels of your product hierarchy can be chosen as the subject of a written "
       "paragraph. Broader levels make better stories - 'Grocery is down 4%' means more to a "
       "manager than one shelf label. Deeper levels are still used to explain why.",
       "R4 primary-focus floor. Levels below these remain valid supporting deep-dive evidence.",
       tier="essential", per_client=True, item_choices=HIERARCHY_ROLES),
    _k("summary_focus_role_aliases", "object", {}, "roles",
       "Rename your levels to standard ones",
       "Only needed when the data check did NOT find a level you know exists. Put YOUR name on "
       "the left and the standard name on the right, all inside one pair of braces: "
       "{\"merchandise group\": \"department\", \"buying group\": \"division\"}. "
       "Leave it empty if the data check already listed the levels you expected - renaming one "
       "it found correctly will move that level somewhere it does not belong.",
       "Applied by summary_roles.canonical_role before hierarchy depth is resolved, matching the "
       "semantic role first and then the column name, by whole-token containment. The escape "
       "hatch when the generic patterns do not match - not a way to re-map levels that did match."),
    _k("summary_focus_hierarchy_overrides", "object", {}, "roles",
       "Force a specific drill-down path",
       "Advanced. Tells the agent which level to break a story down by, instead of letting it "
       "choose. Leave empty unless a drill-down is coming out wrong.",
       "Role-matched deep-dive child-level overrides. Validated against metadata and fails "
       "loudly when invalid.",
       tier="expert"),
    _k("summary_coverage_roles", "list", ["store", "division", "department", "section", "category"],
       "roles",
       "Levels that get a full ranked table",
       "Every member of these levels gets one ranked line in the report - every store, every "
       "department, and so on. Nothing is left out; the page just hides the long tail behind a "
       "'show the rest' link. Include more levels here than above.",
       "R5 full coverage. A superset of the focus roles; 'store' is coverage-only and can never "
       "enter the focus rotation.",
       tier="essential", per_client=True, item_choices=COVERAGE_ROLES),
    _k("summary_dashboard_entity_role", "string", "", "roles",
       "Level used for the per-location cards",
       "Which level the dashboard's individual cards represent - usually stores or branches. "
       "Leave empty to let the agent work it out. If the data check said it could not identify "
       "your stores, you must choose one here or that section cannot be produced.",
       "R6 entity level for the per-entity cards and the three-lever split. Empty auto-resolves "
       "from the profile's entity dimension; pin it when the probe reports entity=unresolved.",
       tier="essential", per_client=True),
    _k("summary_dashboard_exposure_role", "string", "", "roles",
       "Level used for the 'at risk' figure",
       "Which level is counted when the report says how much revenue sits in areas that are "
       "declining. Leave empty to let the agent choose.",
       "R6 exposure role for the declining-area signal.",
       per_client=True),
)

# ---------------------------------------------------------------------------
# 4. What the reports include
# ---------------------------------------------------------------------------

_FEATURES: tuple[ConfigKey, ...] = (
    _k("fresh_summary_enabled", "bool", True, "features",
       "Use the modern summary",
       "Keep this on. Turning it off falls back to a much older, plainer summary that predates "
       "everything else on this page.",
       "Master switch for the fresh-summary path; false reverts to the legacy generate_summary "
       "node.",
       tier="essential"),
    _k("summary_focus_enabled", "bool", True, "features",
       "Pick a topic to focus on each day",
       "Lets the agent choose one business area to write about in depth each day, and rotate "
       "through different areas over the week instead of repeating itself.",
       "R1-R3 daily-focus selection. False reproduces the old summary_key rotation exactly."),
    _k("summary_r4_enabled", "bool", False, "features",
       "Balanced report: overall picture plus several areas",
       "Starts the report with how the business did overall, then covers a few significant "
       "areas rather than only one. You almost certainly want this on. If it is left unset the "
       "report quietly goes back to covering a single area, with no error to tell you.",
       "R4. The code default is false, so a config missing this key silently reproduces R1-R3.",
       tier="essential",
       warn="This is not set, so the report will quietly cover only one area instead of a "
            "balanced page. Set it deliberately either way."),
    _k("summary_r6_enabled", "bool", False, "features",
       "Interactive dashboard page",
       "Produces a browsable dashboard with an overview, per-location cards, spotlight areas "
       "and full detail tables, in two time views. If left unset, no dashboard file is "
       "produced - again with no error.",
       "R6, written to report_dashboard.html. Same trap as R4.",
       tier="essential",
       warn="This is not set, so no interactive dashboard will be produced. Set it deliberately "
            "either way."),
    _k("summary_visual_enabled", "bool", True, "features",
       "Charts in the summary",
       "Adds interactive charts to the summary page. They work without any internet connection."),
    _k("summary_llm_authoring_enabled", "bool", True, "features",
       "Let the AI write the wording",
       "On, the AI writes the sentences from figures the agent has already checked. Off, you "
       "get plainer wording assembled from the same figures with no AI involved - useful if you "
       "want the AI out of the loop entirely.",
       "False forces the grounded deterministic draft in both the summary generator and the "
       "dashboard builder."),
    _k("summary_dashboard_entity_levers", "bool", True, "features",
       "Break each location down into trips, basket size and price",
       "Spends one extra query so each location card can show whether revenue moved because of "
       "more customers, fuller baskets, or higher prices. These have very different responses, "
       "so the split is usually worth the query.",
       "R6 three-lever scan: Revenue = Transactions x Basket Size x Price."),
    _k("summary_dashboard_period_view", "bool", True, "features",
       "Offer a single-month view",
       "Adds a toggle so readers can switch from the whole period covered to just the most "
       "recently completed month."),
    _k("summary_dashboard_period_scan", "bool", True, "features",
       "Give that single-month view its own figures",
       "Spends one more query so the month view has real breakdowns of its own. Without it, "
       "that view shows only headline numbers and says so rather than borrowing figures that "
       "do not describe it."),
    _k("summary_dashboard_replaces_summary_html", "bool", False, "features",
       "Serve the dashboard as the main report",
       "Replaces the ordinary summary page with the interactive dashboard everywhere it is "
       "published - including in your live app. Only turn this on once you have looked at a "
       "finished dashboard and are happy with it.",
       "Overwrites report_summary.html so the existing publish path picks the dashboard up.",
       per_client=True,
       warn="This changes what your live app shows people. Confirm you have reviewed a finished "
            "dashboard first."),
    _k("summary_overall_trend_enabled", "bool", True, "features",
       "Show the trend over time",
       "Adds a month-by-month trend line for the business as a whole."),
    _k("summary_focus_deep_dive_enabled", "bool", True, "features",
       "Explain each featured area in depth",
       "For each area the report features, digs into what drove it - which products, which "
       "locations, and whether it was volume or price."),
    _k("summary_focus_daily_trend_enabled", "bool", False, "features",
       "Show a day-by-day trend where possible",
       "Off by default because most dashboards do not have a genuine daily date to trend on. "
       "The agent checks first and silently skips it if the data cannot support it."),
    _k("summary_focus_public_metadata", "bool", False, "features",
       "Include the chosen topics in the app data file",
       "Adds an extra field naming the areas the report focused on. Only switch this on if the "
       "app reading the file has been updated to expect it.",
       "Emits the additive dailyFocus/dailyFocuses field on report_summary.json."),
    _k("insight_temporal_enabled", "bool", True, "features",
       "Look for patterns within the year",
       "Lets the deep-dive report spot which months drove a change, rather than only reporting "
       "the yearly total."),
    _k("insight_recent_week_enabled", "bool", True, "features",
       "Report on last week",
       "Flags anything unusual in the most recently completed week. This needs a genuine daily "
       "trading date in your data - the agent checks, and turns it off with an explanation if "
       "your data cannot support it."),
    _k("insight_daily_enabled", "bool", True, "features",
       "Flag unusual individual days",
       "Points out specific days that were far above or below normal. Same data requirement as "
       "the weekly setting above."),
    _k("insight_memory_enabled", "bool", True, "features",
       "Remember what has already been reported",
       "Stops the agent telling you the same finding every morning. With this on, a daily run "
       "surfaces only things you have not already been told.",
       tier="essential"),
    _k("summary_memory_enabled", "bool", True, "features",
       "Remember which topics have been covered",
       "Stops the summary featuring the same area day after day, so the week's reports cover "
       "different ground.",
       "ANDed with fresh_summary_enabled.",
       tier="essential", derived=True),
    _k("insight_history_enabled", "bool", True, "features",
       "Keep a dated history of insights",
       "Saves each day's findings so your app can show a history rather than only today.",
       in_state=False),
    _k("summary_history_enabled", "bool", True, "features",
       "Keep a dated history of summaries",
       "As above, for the daily summary.",
       "ANDed with fresh_summary_enabled.",
       derived=True),
    _k("api_payloads", "bool", True, "features",
       "Produce data files for your app",
       "Writes the machine-readable files your app reads to display the reports. Turn this off "
       "only if nothing consumes them.",
       in_state=False),
    _k("insight_tiles_enabled", "bool", False, "features",
       "Old tile board (no longer exists)",
       "Left over from a feature that was removed. Nothing reads this - it can be deleted.",
       tier="expert", in_state=False, dead=True),
    _k("insight_thesis_linking_enabled", "bool", False, "features",
       "Experimental: link related findings",
       "Unfinished feature. Leave off.",
       tier="expert"),
    _k("insight_rate_outlier_mode", "enum", "off", "features",
       "Experimental: compare growth rates between peers",
       "Unfinished feature. Leave off.",
       "'off' plans no peer scans at all.",
       tier="expert",
       choices=("off", "shadow", "report"),
       choice_labels=(("off", "Off (recommended)"), ("shadow", "Calculate but do not report"),
                      ("report", "Report"))),
)

# ---------------------------------------------------------------------------
# 5. Where the reports are saved
# ---------------------------------------------------------------------------

_PUBLISHING: tuple[ConfigKey, ...] = (
    _k("azure_blob_upload", "bool", False, "publishing",
       "Upload the app data files to cloud storage",
       "Turn this on for a scheduled cloud run, so your app can read the results. If an upload "
       "fails the run still finishes and tells you.",
       tier="essential", in_state=False),
    _k("azure_blob_account", "string", "", "publishing",
       "Storage account name",
       "The name of the Azure storage account to upload to. Your administrator can tell you this.",
       tier="essential", in_state=False),
    _k("azure_blob_container", "string", "insightgen", "publishing",
       "Storage container",
       "The container inside that storage account. Several clients can share one container as "
       "long as each has its own folder name below.",
       tier="essential", in_state=False),
    _k("azure_blob_prefix", "string", "", "publishing",
       "Folder name inside the container",
       "Each client must have its own folder name here. If two clients share one, the second "
       "run of the day overwrites the first client's files - and nothing reports an error, so "
       "you would only notice days later when the app shows the wrong figures.",
       "Not dataset-scoped, unlike memory and history, which key on dataset_id and cannot "
       "collide.",
       tier="essential", per_client=True, in_state=False,
       warn="Another client already uses this folder. One would overwrite the other's files."),
    _k("azure_blob_history_prefix", "string", "history", "publishing",
       "Folder for the insight history",
       "Where dated copies of past insights are kept.",
       in_state=False),
    _k("azure_blob_history_feed", "string", "insight_history.json", "publishing",
       "Insight history file name",
       "The single file your app reads to show recent insights newest-first.",
       in_state=False),
    _k("azure_blob_summary_history_prefix", "string", "summary-history", "publishing",
       "Folder for the summary history",
       "Where dated copies of past summaries are kept.",
       in_state=False),
    _k("azure_blob_summary_history_feed", "string", "summary_history.json", "publishing",
       "Summary history file name",
       "The single file your app reads to show recent summaries newest-first.",
       in_state=False),
    _k("azure_blob_memory_container", "string", "insightstate", "publishing",
       "Container for the agent's memory",
       "A private container where the agent records what it has already reported. Not for your "
       "app to read.",
       in_state=False),
    _k("azure_blob_memory_prefix", "string", "", "publishing",
       "Folder for insight memory",
       "Optional folder name. Clients cannot clash here even if they share one - memory files "
       "are already named after the dataset.",
       tier="expert", in_state=False),
    _k("azure_blob_summary_memory_prefix", "string", "summary-memory", "publishing",
       "Folder for summary memory",
       "As above, for the summary's own memory.",
       tier="expert", in_state=False),
    _k("insight_memory_storage", "enum", "local", "publishing",
       "Where insight memory is kept",
       "In the cloud this must be 'cloud storage'. A scheduled job gets a fresh, empty machine "
       "every run, so memory kept on that machine is lost each time and the agent repeats "
       "yesterday's findings every morning.",
       tier="essential",
       choices=("local", "azure_blob"),
       choice_labels=(("local", "On this computer"), ("azure_blob", "Cloud storage")),
       in_state=False),
    _k("summary_memory_storage", "enum", "local", "publishing",
       "Where summary memory is kept",
       "Same as above, for the summary's topic rotation. In the cloud this must be 'cloud "
       "storage' or the summary features the same area every day.",
       "Falls back to insight_memory_storage when unset.",
       tier="essential",
       choices=("local", "azure_blob"),
       choice_labels=(("local", "On this computer"), ("azure_blob", "Cloud storage")),
       in_state=False, derived=True),
    _k("insight_memory_runtime_folder", "string", "outputs/.runtime/insight_memory", "publishing",
       "Temporary folder for downloaded memory",
       "A scratch folder used while cloud memory is being read and written. Leave as is.",
       tier="expert", in_state=False, derived=True),
    _k("summary_memory_runtime_folder", "string", "outputs/.runtime/summary_memory", "publishing",
       "Temporary folder for downloaded summary memory",
       "As above. Leave as is.",
       tier="expert", in_state=False, derived=True),
    _k("ai_content_publish_enabled", "bool", False, "publishing",
       "Publish into your app's own storage",
       "Copies the finished reports into the container your customer-facing app reads from.",
       tier="essential", in_state=False),
    _k("ai_content_client", "string", "", "publishing",
       "Your app's storage container",
       "The name of an EXISTING storage container for this client's app. It is not created for "
       "you - if the name is wrong, publishing simply fails.",
       "Creates ai-content/kpi/client/* and ai-content/report-summaries/client/*.",
       tier="essential", per_client=True, in_state=False,
       warn="No storage container with this name exists, so publishing will fail."),
    _k("ai_content_report_ids", "list", [], "publishing",
       "Report IDs to publish under",
       "The Power BI report IDs your app shows these results against. Leave empty and the agent "
       "finds matching reports itself.",
       tier="essential", per_client=True, in_state=False),
    _k("ai_content_report_id", "string", "", "publishing",
       "Single report ID (older format)",
       "Older single-report version of the setting above. Use the list version instead.",
       tier="expert", in_state=False),
    _k("ai_content_ttl_hours", "int", 24, "publishing",
       "How long published results stay fresh",
       "After this many hours your app treats the published results as out of date."),
    _k("ai_content_alert_days", "int", 7, "publishing",
       "How long alerts are kept",
       "Alerts older than this many days drop off.",
       in_state=False),
    _k("ai_content_multi_report_feed", "bool", False, "publishing",
       "Let several reports share one insight feed",
       "Turn this on only after your app has been updated to handle it. It lets more than one "
       "report put findings into the same feed, and stamps each finding with the report it came "
       "from. With it off, the feed looks exactly as it does today.",
       "Adds reportId to every KpiCard and switches card id from a per-run 1..n sequence to a "
       "stable hash of report_id + story_key, because two reports both numbering from 1 collide "
       "in one feed. Also makes the insights/alerts merges report-aware so a run replaces only "
       "its own report's cards for the date. OFF reproduces today's payload byte-for-byte. See "
       "docs/phase5-app-contract-change.md - the consumer must tolerate the field first.",
       tier="expert"),
    _k("ai_content_feed_max_cards", "int", 10, "publishing",
       "How many findings the feed holds in total",
       "The most findings shown for this client at once, shared out between whichever reports "
       "ran. Every report that found something is guaranteed at least one place before the list "
       "is cut, so a quiet report is never squeezed out entirely.",
       "Total budget across reports, divided by kernel.chain.fair_share. Only consulted when "
       "ai_content_multi_report_feed is on; otherwise each report publishes its own "
       "insight_max_new_per_run cards.",
       in_state=False, tier="expert"),
    _k("api_summary_title", "string", "AI Summary", "publishing",
       "Title shown above the summary",
       "The heading your readers see, for example 'Sales vs Last Year'.",
       tier="essential", per_client=True, in_state=False),
    _k("summary_required_delivery_channels", "list", ["local_report", "history"], "publishing",
       "Deliveries that must succeed",
       "The agent only records a topic as 'covered' once these deliveries have worked. If an "
       "optional upload fails, you still see the failure, but tomorrow's report will not repeat "
       "today's topic. Add an upload here if a failed upload should hold the rotation back.",
       item_choices=DELIVERY_CHANNELS),
    _k("insight_history_timezone", "string", "Asia/Kolkata", "publishing",
       "Time zone for dating insights",
       "Which time zone decides what counts as 'today' when insights are filed.",
       tier="essential", in_state=False),
    _k("summary_history_timezone", "string", "Asia/Kolkata", "publishing",
       "Time zone for dating summaries",
       "As above, for the summary.",
       tier="essential", in_state=False),
)

# ---------------------------------------------------------------------------
# 6. Daily summary settings
# ---------------------------------------------------------------------------

_SUMMARY_TUNING: tuple[ConfigKey, ...] = (
    _k("summary_word_limit", "int", 300, "summary_tuning",
       "Old summary length limit",
       "Only used by the older summary. Ignored unless you turned the modern summary off.",
       tier="expert"),
    _k("fresh_summary_max_words", "int", 420, "summary_tuning",
       "Summary length (not in use)",
       "Nothing reads this - it can be deleted.",
       tier="expert", in_state=False, dead=True),
    _k("fresh_summary_metric_tiles", "int", 6, "summary_tuning",
       "Number of headline figures (not in use)",
       "Nothing reads this - it can be deleted.",
       tier="expert", in_state=False, dead=True),
    _k("summary_candidates_max", "int", 12, "summary_tuning",
       "Topics considered before choosing",
       "How many possible angles the agent weighs up before deciding what to write about."),
    _k("summary_focus_target_count", "int", 3, "summary_tuning",
       "Areas covered after the overall picture",
       "How many business areas get their own written section. Three keeps the report readable; "
       "more makes it a list."),
    _k("summary_focus_candidate_pool_per_role", "int", 30, "summary_tuning",
       "Members looked at per level",
       "How many departments, categories and so on the agent examines at each level. Raise it "
       "if a level has many more members than this and you are missing things.",
       "Falls back to summary_focus_members_per_dimension when unset.",
       derived=True),
    _k("summary_focus_universe_max_queries", "int", 4, "summary_tuning",
       "Queries allowed for scanning levels",
       "One query per level you chose for written stories. If you pick more levels than this, "
       "the last ones are not scanned."),
    _k("summary_coverage_max_queries", "int", 3, "summary_tuning",
       "Queries allowed for the ranked tables",
       "Kept separate on purpose, so producing the full tables can never use up the budget the "
       "written stories need."),
    _k("summary_focus_total_deep_dive_queries", "int", 15, "summary_tuning",
       "Total queries for digging into featured areas",
       "Shared across every area the report features.",
       "Falls back to summary_focus_max_queries when unset.",
       derived=True),
    _k("summary_focus_max_queries_per_focus", "int", 5, "summary_tuning",
       "Maximum queries for any one area",
       "Stops the first area using up the whole shared budget above."),
    _k("summary_focus_max_queries", "int", 4, "summary_tuning",
       "Query budget when covering a single area",
       "Only used when the balanced multi-area report is switched off.",
       tier="expert"),
    _k("summary_focus_max_child_dimensions", "int", 2, "summary_tuning",
       "How many ways to break an area down",
       "For example, breaking a department down by both category and location counts as two."),
    _k("summary_focus_max_rows_per_breakdown", "int", 12, "summary_tuning",
       "Rows per breakdown",
       "How many lines each breakdown table returns."),
    _k("summary_focus_members_per_dimension", "int", 10, "summary_tuning",
       "Members re-used from each breakdown",
       "How many individual members the agent picks out of data it has already fetched. Costs "
       "nothing extra."),
    _k("summary_dashboard_max_queries", "int", 2, "summary_tuning",
       "Extra queries for the dashboard",
       "Pays for the per-location breakdown and the single-month view."),
    _k("summary_dashboard_period_scan_rows", "int", 400, "summary_tuning",
       "Row limit for the monthly breakdown",
       "A safety cap on the size of one query. Raise it if you have many locations and many "
       "months."),
    _k("summary_dashboard_entity_rows", "int", 40, "summary_tuning",
       "Location cards shown",
       "How many individual location cards appear on the dashboard."),
    _k("summary_dashboard_movers", "int", 5, "summary_tuning",
       "Top risers and fallers listed",
       "How many of each appear in the detail section."),
    _k("summary_dashboard_tldr", "int", 5, "summary_tuning",
       "Bullet points in 'what matters most'",
       "The short summary at the top of the page."),
    # --- Target Tracker (WP9). Its own report, its own semantic model. ---------
    _k("target_tracker_population", "list", [], "scope",
       "Branches the Target Tracker report covers",
       "The branches measured against target. Leave empty to include every branch in the model.",
       "Applied as a TREATAS filter on LOC_CODE in every Target Tracker query, so a branch left "
       "out here is absent from the totals as well as the tables.",
       tier="essential", per_client=True, in_state=False),
    _k("target_tracker_excluded_entities", "list", [], "scope",
       "Branches the Target Tracker report leaves out",
       "Recorded so the page can say which branches are missing and why.",
       "Documentation only - exclusion is achieved by omitting the branch from "
       "target_tracker_population.",
       tier="standard", per_client=True, in_state=False),
    _k("target_tracker_currency", "string", "SAR", "summary_tuning",
       "Currency shown on the Target Tracker page",
       "The currency code printed beside every figure.",
       "The model's own 'Metrics description' table says QAR on four rows and is stale; the "
       "group is Saudi-based, so SAR is correct. Do not read the currency from that table.",
       tier="standard", in_state=False),
    _k("target_tracker_anchor_override", "string", "", "summary_tuning",
       "Report on a specific date instead of the latest",
       "Leave empty for normal running. Set a date (YYYY-MM-DD) only to reproduce an earlier day.",
       "Normally the report anchors on the latest date that carries a sales target, which is not "
       "always the latest date with sales. When this is set the page says the date was chosen "
       "rather than resolved.",
       tier="expert", in_state=False),
    _k("target_tracker_week_start", "string", "monday", "summary_tuning",
       "First day of the Target Tracker week",
       "Which day the week-to-date figure starts from.",
       "The model's own week numbering runs Monday to Sunday; changing this would put the page "
       "out of step with it.",
       tier="expert", in_state=False),
    _k("target_tracker_llm_authoring_enabled", "bool", False, "features",
       "Let the AI write the Target Tracker wording",
       "When off, the report uses fixed sentences built from the figures. When on, the AI "
       "rewrites those sentences to read better. It can never change a number, add a section "
       "or leave a period out.",
       "Every draft is checked against the rulebook before it is used: figures must exist in "
       "the report and be rounded, no cause may be asserted, no prior-year comparison, no "
       "forecasting, no banned vocabulary. A draft that fails twice is discarded and the "
       "deterministic wording is kept, so the report ships either way.",
       tier="standard", in_state=False),
    _k("target_tracker_material_pct", "float", 5.0, "summary_tuning",
       "Difference from target that counts as significant (%)",
       "A gap smaller than this is treated as normal variation rather than a finding.",
       tier="standard", in_state=False),
    _k("target_tracker_display_rows", "int", 12, "summary_tuning",
       "Rows shown in Target Tracker detail tables",
       "Only affects what is visible at first glance. Every branch and department is always in "
       "the page; this only limits what is shown before scrolling.",
       tier="standard", in_state=False),
    # --- Ageing report. One snapshot, policy-defined risk bands. ------------
    _k("ageing_mapping", "object", {}, "scope",
       "Ageing field mapping",
       "Maps stock value, age band, snapshot date, movement status and breakdown fields.",
       "Automatic discovery proposes this mapping, but a production report keeps the approved "
       "references here so a weak naming guess can never silently change the denominator.",
       tier="expert", per_client=True, in_state=False),
    _k("ageing_currency", "string", "SAR", "summary_tuning",
       "Currency shown on the Ageing page",
       "The currency code printed beside every Ageing value.",
       tier="standard", per_client=True, in_state=False),
    _k("ageing_aged_filter", "string", "", "scope",
       "Rule that identifies aged stock",
       "The approved business rule used to classify exposure as aged.",
       "This is intentionally explicit because different businesses use different age boundaries.",
       tier="expert", per_client=True, in_state=False),
    _k("ageing_high_risk_filter", "string", "", "scope",
       "Rule that identifies high-risk stock",
       "The approved business rule used for the high-risk Ageing view.",
       tier="expert", per_client=True, in_state=False),
    _k("ageing_oldest_filter", "string", "", "scope",
       "Rule that identifies the oldest stock",
       "The approved business rule used for the oldest Ageing drill-down.",
       tier="expert", per_client=True, in_state=False),
    _k("ageing_validation_share_expression", "string", "", "scope",
       "Existing ageing rate to validate",
       "An optional existing report rate checked against the chosen stock-value denominator.",
       tier="expert", per_client=True, in_state=False),
    _k("ageing_validation_numerator_expression", "string", "", "scope",
       "Existing aged amount to validate",
       "An optional existing aged amount checked before it is allowed into reporting.",
       tier="expert", per_client=True, in_state=False),
    _k("ageing_reject_model_aged_share", "bool", True, "features",
       "Reject an invalid existing ageing rate",
       "Keeps a source ageing rate out of the report when it fails the denominator check.",
       tier="standard", per_client=True, in_state=False),
    _k("ageing_top_members", "int", 50, "summary_tuning",
       "Members scanned per Ageing breakdown",
       "Limits each division, section, location or type breakdown while retaining the largest exposures.",
       tier="standard", per_client=True, in_state=False),
    _k("ageing_deep_dive_members", "int", 5, "summary_tuning",
       "Products shown in each Ageing drill-down",
       "Controls the length of the oldest-stock and aged-not-selling product lists.",
       tier="standard", per_client=True, in_state=False),
    _k("summary_dashboard_eyebrow", "string", "AI Insights", "summary_tuning",
       "Small heading above the page title",
       "Appears in small letters above the main title."),
    _k("summary_coverage_display_rows", "int", 8, "summary_tuning",
       "Table rows shown before 'show the rest'",
       "Only affects what is visible at first glance. Every member is always in the page - this "
       "just keeps a long table from filling the screen."),
    _k("summary_coverage_material_change_pct", "float", 10, "summary_tuning",
       "Movement that counts as significant (%)",
       "A change smaller than this is treated as normal fluctuation in the ranked tables."),
    _k("summary_coverage_material_share_pct", "float", 5, "summary_tuning",
       "Size that counts as significant (%)",
       "An area smaller than this share of the business is never flagged as critical, however "
       "large its percentage move. A tiny area doubling is not a business event."),
    _k("summary_focus_material_change_pct", "float", 20, "summary_tuning",
       "Movement needed to be worth a story (%)",
       "How much an area must have moved before it is worth writing a paragraph about."),
    _k("summary_focus_min_movement_impact_pct", "float", 5, "summary_tuning",
       "Minimum impact on the business (%)",
       "How much of the whole company's movement an area must account for to be featured."),
    _k("summary_focus_min_business_share_pct", "float", 5, "summary_tuning",
       "Minimum size of the business (%)",
       "How large an area must be to be featured at all."),
    _k("summary_focus_min_change_pct", "float", 3, "summary_tuning",
       "Minimum change to be considered (%)",
       "Areas that barely moved are not candidates."),
    _k("summary_focus_override_change_pct", "float", 20, "summary_tuning",
       "Big-move threshold (%)",
       "A move this large can jump the queue and be reported out of turn - but only if it also "
       "clears the size threshold below. Both must be true."),
    _k("summary_focus_override_min_impact_share_pct", "float", 2, "summary_tuning",
       "Big-move size threshold (%)",
       "Partner to the setting above. Together they stop a huge percentage on a tiny area from "
       "hijacking the report."),
    _k("summary_focus_fact_overlap_threshold", "float", 0.6, "summary_tuning",
       "How similar two stories can be before one is dropped",
       "Between 0 and 1. If a new story names mostly the same products and locations as a "
       "recent one, it is replaced by something fresher."),
    _k("summary_focus_overlap_window_days", "int", 7, "summary_tuning",
       "How far back to check for repeats (days)",
       "Older stories stop counting after this, so an area can never be suppressed forever."),
    _k("summary_focus_rotation_window_days", "int", 7, "summary_tuning",
       "Rotation window (days)",
       "The period over which the agent tries to cover different ground."),
    _k("summary_focus_min_repeat_gap_days", "int", 2, "summary_tuning",
       "Minimum gap before an area repeats (days)",
       "Stops the same area appearing two mornings running."),
    _k("summary_focus_same_dimension_gap_days", "int", 2, "summary_tuning",
       "Minimum gap before the same level repeats (days)",
       "Stops two consecutive reports both being about departments, say."),
    _k("summary_focus_cooldown_days", "int", 14, "summary_tuning",
       "Rest period after an area is featured (days)",
       "How long before the same area can be the subject again."),
    _k("summary_focus_policy", "enum", "cooldown", "summary_tuning",
       "What happens after an area is featured",
       "Either it can come back after the rest period above, or it is never repeated at all.",
       choices=("cooldown", "never_repeat"),
       choice_labels=(("cooldown", "Rest, then it can return"), ("never_repeat", "Never repeat it"))),
    _k("summary_focus_schedule", "object", {}, "summary_tuning",
       "Preferred topic by day of week",
       "Optional. Nudges the agent towards, say, departments on Mondays. It is a preference, "
       "not a rule - a genuinely big story still wins.",
       "Both {weekday: role} and {role: weekday} forms are accepted case-insensitively.",
       tier="expert"),
    _k("summary_focus_schedule_weight", "float", 0.5, "summary_tuning",
       "How strong that preference is",
       "Higher makes the day-of-week preference harder to override.",
       tier="expert"),
    _k("summary_focus_timezone", "string", "Asia/Kolkata", "summary_tuning",
       "Time zone that decides 'today'",
       "Must be a standard time zone name such as Asia/Kolkata or Europe/London. A name the "
       "agent does not recognise stops the run rather than guessing.",
       tier="essential"),
    _k("summary_focus_reconciliation_tolerance_pct", "float", 2, "summary_tuning",
       "How closely figures must add up (%)",
       "If a breakdown does not add up to its total within this margin, the agent will not "
       "publish it."),
    _k("summary_focus_include_driver_bridge", "bool", True, "summary_tuning",
       "Split changes into volume and price",
       "Shows how much of a change came from selling more units versus charging more."),
    _k("summary_focus_include_trend", "bool", True, "summary_tuning",
       "Include a trend for each featured area",
       "Shows how a featured area has moved over recent periods."),
    _k("summary_focus_daily_trend_min_days", "int", 14, "summary_tuning",
       "Days of history needed for a daily trend",
       "A daily trend is only offered once there is at least this much history."),
    _k("summary_focus_max_replacements_per_slot", "int", 1, "summary_tuning",
       "Substitutions allowed per section",
       "If a chosen area turns out to duplicate another, how many times the agent may swap in a "
       "reserve before simply publishing fewer sections."),
    _k("summary_overall_trend_max_queries", "int", 1, "summary_tuning",
       "Queries for the overall trend",
       "How many queries the company-wide trend line may use."),
    _k("summary_memory_policy", "enum", "never_repeat", "summary_tuning",
       "How long a covered topic stays covered",
       "Either a topic is never repeated, or it becomes available again after the rest period "
       "below.",
       choices=("never_repeat", "cooldown"),
       choice_labels=(("never_repeat", "Never repeat"), ("cooldown", "Repeat after a rest"))),
    _k("summary_memory_cooldown_days", "int", 14, "summary_tuning",
       "Rest period for a covered topic (days)",
       "Only used if you chose 'repeat after a rest' above."),
    _k("summary_resurface_change_pct", "float", 20, "summary_tuning",
       "Change that brings an old topic back (%)",
       "If something already reported moves this much again, it is worth telling you a second "
       "time."),
    _k("summary_temporal_batch_share", "float", 0.5, "summary_tuning",
       "Test for a fake date column",
       "If more than this share of a whole year's sales lands on a single date, that column is "
       "recording when data was loaded, not when trading happened - so the agent refuses to "
       "trend on it."),
    _k("summary_delayed_after_periods", "int", 1, "summary_tuning",
       "Periods behind before data is called 'delayed'",
       "How far behind the data can fall before the report says so."),
    _k("summary_stale_after_periods", "int", 2, "summary_tuning",
       "Periods behind before data is called 'stale'",
       "As above, for the stronger warning."),
    _k("max_rows_per_query", "int", 15, "summary_tuning",
       "Default row limit per query",
       "A general safety cap on how much any single broad query returns.",
       tier="expert"),
    _k("summary_now_override", "string", None, "summary_tuning",
       "Pretend today is a different date",
       "For testing only. It freezes what the agent thinks 'today' is, which would make a live "
       "report wrong every day. Leave empty.",
       tier="expert",
       warn="This freezes the date the agent thinks it is. It must be empty in live use."),
)

# ---------------------------------------------------------------------------
# 7. Targets and moveable holidays
# ---------------------------------------------------------------------------

_RAG_CALENDAR: tuple[ConfigKey, ...] = (
    _k("summary_rag_bands", "object", {}, "rag_calendar",
       "What counts as good, watch and bad",
       "Sets the thresholds behind the green, amber and red marks. Leave empty to use sensible "
       "defaults. You can override one set of thresholds without disturbing the others.",
       "Band definitions keyed by set name, each declaring a direction (higher_is_better / "
       "higher_is_worse) and thresholds. Merged per set."),
    _k("summary_rag_measure_bands", "object", {}, "rag_calendar",
       "Which measures are judged more harshly",
       "Some measures deserve a tougher standard. Units sold and basket size use one, because "
       "flat units while revenue rises means the growth is coming from price alone - which is "
       "already a warning sign, not a green light.",
       "Maps a measure to a band set, e.g. {\"units\": \"tough\", \"basket_size\": \"tough\"}."),
    _k("summary_rag_cautions", "object", {}, "rag_calendar",
       "Custom warning wording",
       "Optional wording shown alongside a measure when it is off track."),
    _k("summary_calendar_events", "list", [], "rag_calendar",
       "Holidays that move each year",
       "Give this year's and last year's dates for holidays like Eid, Easter or Ramadan. This "
       "is the only way the agent can say a broad drop was the calendar shifting rather than "
       "the business declining. Without it, it still spots the pattern - it just says 'check "
       "the calendar' instead of naming the cause.",
       item_type="object", per_client=True, tier="essential"),
    _k("summary_calendar_min_members", "int", 3, "rag_calendar",
       "Areas needed before calling it estate-wide",
       "Two areas moving together is a coincidence, not a pattern."),
    _k("summary_calendar_uniform_count_share_pct", "float", 80, "rag_calendar",
       "Share of areas moving the same way (%)",
       "How much of the business must move in the same direction before the agent suspects a "
       "calendar shift rather than a business problem."),
    _k("summary_calendar_uniform_business_share_pct", "float", 80, "rag_calendar",
       "Same, weighted by size (%)",
       "As above, but counting bigger areas for more."),
    _k("summary_calendar_cluster_spread_pct", "float", 8, "rag_calendar",
       "How tightly clustered the moves must be (%)",
       "Areas moving the same way but by wildly different amounts is not one shared cause."),
    _k("summary_calendar_exception_deviation_pct", "float", 3, "rag_calendar",
       "Deviation that marks an area as a real problem (%)",
       "A calendar shift is never used as a blanket excuse. Areas that moved much further than "
       "the rest are named as genuinely weak."),
)

# ---------------------------------------------------------------------------
# 8. Deep-dive settings
# ---------------------------------------------------------------------------

_INSIGHT_TUNING: tuple[ConfigKey, ...] = (
    # Signals and budgets
    _k("insight_max_signals", "int", 5, "insight_tuning",
       "Findings per report (memory off)",
       "Only applies if you turned off 'remember what has already been reported'."),
    _k("insight_max_new_per_run", "int", 3, "insight_tuning",
       "New findings per report",
       "How many previously unreported findings a daily run may surface. Keeping this small is "
       "what makes a daily report readable.",
       tier="essential"),
    _k("insight_max_dq_signals", "int", 2, "insight_tuning",
       "Data-problem findings per report",
       "A cap on findings about the data itself, so data noise cannot crowd out actual business "
       "findings."),
    _k("insight_materiality_pct", "float", 1.0, "insight_tuning",
       "Smallest finding worth reporting (%)",
       "Anything below this share of the business is not worth a manager's attention."),
    _k("insight_max_scan_queries", "int", 10, "insight_tuning",
       "Queries for the initial data sweep",
       "The shared first pass both reports are built from."),
    _k("insight_metadata_max_dimensions", "int", 5, "insight_tuning",
       "Ways of slicing the data to examine",
       "How many different breakdowns the initial sweep covers."),
    _k("insight_total_gap_scan_budget", "int", 20, "insight_tuning",
       "Total follow-up queries",
       "A ceiling across the whole run, so investigating cannot run away with your query "
       "allowance."),
    _k("insight_max_gap_dimensions_per_signal", "int", 3, "insight_tuning",
       "Follow-up angles per finding",
       "How many ways one finding may be broken down while looking for the cause."),
    _k("insight_max_investigation_rounds", "int", 3, "insight_tuning",
       "Maximum follow-up queries per finding",
       "A hard stop, so one stubborn question cannot loop forever. Most findings need none or a "
       "few."),
    _k("insight_probe_max_rows", "int", 20, "insight_tuning",
       "Rows returned by a follow-up query",
       "Keeps investigation results readable."),
    _k("insight_cross_dimensions", "int", 1, "insight_tuning",
       "Combined breakdowns to try",
       "How many two-way breakdowns, such as department by location, the sweep tries."),
    _k("insight_peer_max_dimensions", "int", 5, "insight_tuning",
       "Peer comparison breadth (experimental)",
       "Part of an unfinished feature.",
       tier="expert"),
    _k("insight_peer_max_rows", "int", 200, "insight_tuning",
       "Peer comparison row limit (experimental)",
       "Part of an unfinished feature.",
       tier="expert"),
    _k("metadata_scope_max_entities", "int", 500, "insight_tuning",
       "Maximum shops to list",
       "A cap on how many individual shops the agent lists when working out which are "
       "comparable. Raise it if you have more than this."),
    # Statistics
    _k("insight_stat_z_cutoff", "float", 3.0, "insight_tuning",
       "How unusual an outlier must be",
       "A statistical threshold. Higher means only very extreme values are flagged.",
       "Robust-z cutoff.",
       tier="expert"),
    _k("insight_stat_concentration_pct", "float", 50.0, "insight_tuning",
       "Concentration threshold (%)",
       "If a handful of items account for more than this share of a change, that concentration "
       "is itself the story.",
       tier="expert"),
    _k("insight_stat_recon_tolerance_pct", "float", 2.0, "insight_tuning",
       "How closely figures must add up (%)",
       "Breakdowns that miss their total by more than this are reported as a data problem.",
       tier="expert"),
    _k("insight_stat_trend_window", "int", 3, "insight_tuning",
       "Periods used to judge a trend",
       "How many recent periods are considered when deciding a direction of travel.",
       tier="expert"),
    _k("insight_stat_max_candidates", "int", 20, "insight_tuning",
       "Findings shortlisted before ranking",
       "How many possible findings survive to be ranked and chosen from.",
       tier="expert"),
    # Memory
    _k("insight_memory_policy", "enum", "never_repeat", "insight_tuning",
       "How long a reported finding stays quiet",
       "Either a finding is never repeated, or it becomes eligible again after the rest period "
       "below.",
       "Applies to the high/period/recent_week/daily levels only - rolling-week never consults it.",
       choices=("never_repeat", "cooldown"),
       choice_labels=(("never_repeat", "Never repeat"), ("cooldown", "Repeat after a rest"))),
    _k("insight_memory_cooldown_days", "int", 14, "insight_tuning",
       "Rest period for a reported finding (days)",
       "Only used if you chose 'repeat after a rest' above."),
    _k("insight_reporting_grain", "enum", "month", "insight_tuning",
       "Reporting period",
       "The period the agent thinks in. When a new one starts, findings about the previous one "
       "can be told afresh.",
       choices=("day", "week", "month", "quarter", "year"),
       choice_labels=(("day", "Daily"), ("week", "Weekly"), ("month", "Monthly"),
                      ("quarter", "Quarterly"), ("year", "Yearly"))),
    _k("insight_candidates_high", "int", 20, "insight_tuning",
       "Year-level findings considered",
       "How many whole-period findings are weighed up.",
       tier="expert"),
    _k("insight_candidates_period", "int", 10, "insight_tuning",
       "Within-year findings considered",
       "How many month-level findings are weighed up.",
       tier="expert"),
    _k("insight_candidates_weekly", "int", 10, "insight_tuning",
       "Weekly findings considered",
       "How many weekly findings are weighed up.",
       tier="expert"),
    _k("insight_candidates_daily", "int", 10, "insight_tuning",
       "Daily findings considered",
       "How many single-day findings are weighed up.",
       tier="expert"),
    _k("insight_re_alert_growth_pct", "float", 50, "insight_tuning",
       "Growth that brings a finding back (%)",
       "If something already reported has grown this much again, it is worth mentioning a "
       "second time."),
    _k("insight_rolling_report_delta_pct", "float", 5.0, "insight_tuning",
       "Drift that brings a rolling finding back",
       "A smaller threshold used only for the trailing-seven-day view, so a slowly worsening "
       "situation is still raised.",
       tier="expert"),
    # NOTE: insight_now_override is deliberately absent. It is a state-only test
    # hook (src/state.py) that main.py never reads from a config, so putting it
    # in a config.json would do nothing - offering it in the UI would be a lie.
    # Temporal (period) level
    _k("insight_temporal_batch_share", "float", 0.5, "insight_tuning",
       "Test for a fake date column",
       "If more than this share of the year's sales lands on one date, that column records when "
       "data was loaded rather than when trading happened, and the agent refuses to analyse "
       "days or weeks on it. This is what correctly disables daily analysis on some dashboards."),
    _k("insight_temporal_min_periods", "int", 6, "insight_tuning",
       "Periods needed to see a pattern",
       "Fewer than this and there is not enough history to say anything."),
    _k("insight_temporal_recon_tolerance_pct", "float", 2.0, "insight_tuning",
       "How closely the monthly series must add up (%)",
       "The months must sum to the year's total within this margin, or the series is rejected.",
       tier="expert"),
    _k("insight_temporal_max_probes", "int", 3, "insight_tuning",
       "Date columns to try",
       "How many candidate date columns the agent tests before giving up on time analysis."),
    _k("insight_temporal_grain_column", "string", "", "insight_tuning",
       "Force a specific date column",
       "Leave empty to let the agent choose. Fill it in only if it is picking the wrong one.",
       per_client=True),
    _k("insight_period_top_movers", "int", 4, "insight_tuning",
       "Months named as drivers",
       "How many individual months are called out as driving a change."),
    _k("insight_period_recent_window", "int", 12, "insight_tuning",
       "Recent months considered",
       "How far back 'recent' reaches."),
    _k("insight_period_drill", "bool", True, "insight_tuning",
       "Explain the worst month",
       "Spends one query breaking down the worst month, so the report can say what was behind "
       "it rather than only that it happened."),
    _k("insight_period_drill_top", "int", 3, "insight_tuning",
       "Rows in that explanation",
       "How many contributors are named."),
    # Recent-week / daily levels
    _k("insight_business_date_override", "string", None, "insight_tuning",
       "Force a specific trading date column",
       "Leave empty to let the agent find your trading date. Fill it in only if it is choosing "
       "the wrong one.",
       per_client=True),
    _k("insight_week_max_date_probes", "int", 3, "insight_tuning",
       "Date columns to try for weekly analysis",
       "How many candidates are tested before weekly and daily analysis switch themselves off."),
    _k("insight_week_max_data_lag_days", "int", 7, "insight_tuning",
       "How out of date the data may be (days)",
       "If your data is further behind than this, weekly and daily analysis switch themselves "
       "off and say so, rather than reporting on a week that never finished loading.",
       tier="essential"),
    _k("insight_business_timezone", "string", "naive", "insight_tuning",
       "Time zone for trading days",
       "Use 'naive' to take dates exactly as stored, or a standard name like Asia/Kolkata. The "
       "word 'auto' is rejected - the agent will not guess which day a sale belongs to."),
    _k("insight_week_start", "enum", "monday", "insight_tuning",
       "First day of your week",
       "Which day your trading week starts on.",
       choices=("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
       choice_labels=(("monday", "Monday"), ("tuesday", "Tuesday"), ("wednesday", "Wednesday"),
                      ("thursday", "Thursday"), ("friday", "Friday"), ("saturday", "Saturday"),
                      ("sunday", "Sunday"))),
    _k("insight_week_mode", "enum", "calendar", "insight_tuning",
       "How a week is measured",
       "Either proper calendar weeks, or the last seven days counting back from today.",
       choices=("calendar", "rolling"),
       choice_labels=(("calendar", "Calendar weeks"), ("rolling", "Last 7 days"))),
    _k("insight_week_history_weeks", "int", 13, "insight_tuning",
       "Weeks of history used as 'normal'",
       "The stretch of past weeks the current week is judged against."),
    _k("insight_week_materiality_pct", "float", 3.0, "insight_tuning",
       "Weekly move worth reporting (%)",
       "A week must move at least this much AND be statistically unusual. Both, so a dramatic "
       "percentage on a trivial amount is not reported."),
    _k("insight_week_z_cutoff", "float", 2.5, "insight_tuning",
       "How unusual a week must be",
       "The statistical half of the test above.",
       tier="expert"),
    _k("insight_week_driver_rows", "int", 30, "insight_tuning",
       "Rows in the weekly explanation",
       "How many contributors are listed when explaining a week."),
    _k("insight_daily_rolling_window", "int", 28, "insight_tuning",
       "Days of history used as 'normal'",
       "The stretch of past days a single day is judged against."),
    _k("insight_daily_recent_days", "int", 3, "insight_tuning",
       "How recent a day must be to report (days)",
       "Stops the agent raising something that happened weeks ago as if it were news."),
    _k("insight_daily_exclude_today", "bool", True, "insight_tuning",
       "Ignore today's part-loaded figures",
       "Today's data is usually still coming in. Including it makes today look catastrophic "
       "every morning."),
    _k("insight_daily_z_cutoff", "float", 3.0, "insight_tuning",
       "How unusual a day must be",
       "Higher means only genuinely extreme days are flagged.",
       tier="expert"),
    _k("insight_daily_materiality_pct", "float", 3.0, "insight_tuning",
       "Daily move worth reporting (%)",
       "A day must move at least this much as well as being unusual."),
    _k("insight_daily_min_weekday_occurrences", "int", 3, "insight_tuning",
       "Same-weekday history needed",
       "Before flagging a quiet Sunday, the agent wants at least this many past Sundays to "
       "compare against - otherwise every Sunday looks alarming next to a weekday average."),
    # Experimental
    _k("insight_rate_z_cutoff", "float", 3.0, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_rate_min_peers", "int", 8, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_rate_min_ordinal_peers", "int", 3, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_rate_exposure_floor_pct", "float", 2.0, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_rate_flat_min_pct", "float", 10.0, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_rate_min_abs_impact_pct", "float", 1.0, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_rate_prior_share_floor_pct", "float", 0.5, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_thesis_max_links", "int", 2, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_thesis_min_shared", "int", 2, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_thesis_min_impact", "float", 0.0, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
    _k("insight_thesis_interaction_tol", "float", 0.15, "insight_tuning",
       "Experimental setting",
       "Part of an unfinished feature. Leave as is.", tier="expert"),
)


KEYS: tuple[ConfigKey, ...] = (
    _CONNECTION + _SCOPE + _ROLES + _FEATURES + _PUBLISHING
    + _SUMMARY_TUNING + _RAG_CALENDAR + _INSIGHT_TUNING
)

BY_KEY: dict[str, ConfigKey] = {entry.key: entry for entry in KEYS}

if len(BY_KEY) != len(KEYS):  # pragma: no cover - a duplicate is a programming error
    seen: set[str] = set()
    dupes = sorted({e.key for e in KEYS if e.key in seen or seen.add(e.key)})
    raise RuntimeError(f"config_schema has duplicate keys: {dupes}")


# ---------------------------------------------------------------------------
# Derived-default resolution
#
# A handful of keys are not a plain ``cfg.get(key, default)``: they read an
# environment variable, fall back to a legacy key, or compose two flags. They
# live here so ``main.py`` and the UI agree on what a config actually means.
# ---------------------------------------------------------------------------


def resolve(key: str, cfg: dict, *, env: dict | None = None) -> Any:
    """The value the pipeline will actually use for ``key`` given ``cfg``."""
    import os

    env = os.environ if env is None else env
    entry = BY_KEY.get(key)
    fallback = entry.default if entry else None

    if key == "ai_provider":
        return env.get("LLM_PROVIDER") or cfg.get("ai_provider", fallback)
    if key == "summary_focus_candidate_pool_per_role":
        # The legacy per-dimension member count is the backward-compatible
        # fallback for the per-role candidate-pool size.
        return cfg.get(key, cfg.get("summary_focus_members_per_dimension", fallback))
    if key == "summary_focus_total_deep_dive_queries":
        # Legacy summary_focus_max_queries is the fallback for the shared
        # (total) deep-dive budget across all selected focuses.
        return cfg.get(key, cfg.get("summary_focus_max_queries", fallback))
    if key in {"summary_memory_enabled", "summary_history_enabled"}:
        return bool(cfg.get("fresh_summary_enabled", True) and cfg.get(key, True))
    if key == "summary_memory_storage":
        return str(
            cfg.get("summary_memory_storage")
            or str(cfg.get("insight_memory_storage", "local") or "local").lower()
        ).lower()
    if key in {"insight_memory_runtime_folder", "summary_memory_runtime_folder"}:
        return cfg.get(key)
    return cfg.get(key, fallback)


def state_defaults(cfg: dict, *, env: dict | None = None) -> dict:
    """Every ``in_state`` key resolved against ``cfg``.

    This is what ``main.build_initial_state`` starts from, so a key added here
    reaches the graph with no further edit.
    """
    return {
        entry.key: resolve(entry.key, cfg, env=env)
        for entry in KEYS
        if entry.in_state
    }


def defaults(*, include_dead: bool = False) -> dict:
    """Every key at its code default - the config an empty file behaves like."""
    return {
        entry.key: entry.default
        for entry in KEYS
        if include_dead or not entry.dead
    }


# ---------------------------------------------------------------------------
# Lookup / rendering helpers used by the UI and the validators
# ---------------------------------------------------------------------------


def get(key: str) -> ConfigKey | None:
    return BY_KEY.get(key)


def label(key: str) -> str:
    """The plain name for a key, for use in a message someone has to read."""
    entry = BY_KEY.get(key)
    return entry.label if entry else key


def group_keys(group: str) -> tuple[ConfigKey, ...]:
    return tuple(entry for entry in KEYS if entry.group == group)


def per_client_keys() -> tuple[ConfigKey, ...]:
    return tuple(entry for entry in KEYS if entry.per_client)


def tier_keys(tier: str) -> tuple[ConfigKey, ...]:
    return tuple(entry for entry in KEYS if entry.tier == tier)


def warned_keys() -> tuple[ConfigKey, ...]:
    return tuple(entry for entry in KEYS if entry.warn)


def unknown_keys(cfg: dict) -> list[str]:
    """Keys in ``cfg`` that no code reads and this schema does not know."""
    return sorted(key for key in cfg if key not in BY_KEY)


def to_json() -> dict:
    """The whole catalogue, for the config UI to render a form from."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "groups": [
            {"id": g.id, "title": g.title, "blurb": g.blurb, "probeDriven": g.probe_driven,
             "counts": {
                 tier: sum(1 for k in group_keys(g.id) if k.tier == tier) for tier in TIERS
             }}
            for g in GROUPS
        ],
        "keys": [entry.json() for entry in KEYS],
        "tiers": list(TIERS),
        "vocabulary": {
            "hierarchyRoles": list(HIERARCHY_ROLES),
            "coverageRoles": list(COVERAGE_ROLES),
            "deliveryChannels": list(DELIVERY_CHANNELS),
            "roleLabels": dict(ROLE_LABELS),
            "channelLabels": dict(CHANNEL_LABELS),
        },
    }


# ---------------------------------------------------------------------------
# Coercion and type checking
# ---------------------------------------------------------------------------

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class CoercionError(ValueError):
    """A submitted value cannot be represented as the key's declared type."""


def coerce(key: str, raw: Any) -> Any:
    """Turn a form/JSON value into the type the pipeline expects.

    Strings arrive from HTML inputs even for numeric and boolean keys, so the UI
    can post a flat object and let one function own the conversion.
    """
    entry = BY_KEY.get(key)
    if entry is None:
        return raw
    if raw is None:
        return None
    kind = entry.type
    name = entry.label

    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise CoercionError(f"{name}: this must be yes or no; got {raw!r}.")

    if kind == "int":
        if isinstance(raw, bool):
            raise CoercionError(f"{name}: this must be a whole number; got {raw!r}.")
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError) as exc:
            raise CoercionError(f"{name}: this must be a whole number; got {raw!r}.") from exc
        return value

    if kind == "float":
        if isinstance(raw, bool):
            raise CoercionError(f"{name}: this must be a number; got {raw!r}.")
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError) as exc:
            raise CoercionError(f"{name}: this must be a number; got {raw!r}.") from exc
        # Keep 20 as 20 rather than 20.0 so a written config matches the
        # committed ones byte for byte.
        return int(value) if value.is_integer() and isinstance(entry.default, int) else value

    if kind == "list":
        if isinstance(raw, list):
            return raw
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise CoercionError(f"{name}: this must be a list; got {raw!r}.")
            return parsed
        return [part.strip() for part in text.split(",") if part.strip()]

    if kind == "object":
        if isinstance(raw, dict):
            return raw
        text = str(raw).strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise CoercionError(f"{name}: this must be a set of name/value pairs; got {raw!r}.")
        return parsed

    if kind == "enum":
        text = str(raw).strip()
        if entry.choices and text not in entry.choices:
            raise CoercionError(
                f"{name}: choose one of {', '.join(entry.choices)}; got {raw!r}."
            )
        return text

    return str(raw)


def coerce_config(raw: dict) -> tuple[dict, list[str]]:
    """Coerce a whole submitted object. Unknown keys pass through untouched."""
    out: dict = {}
    errors: list[str] = []
    for key, value in raw.items():
        try:
            out[key] = coerce(key, value)
        except (CoercionError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            out[key] = value
    return out, errors


def type_errors(cfg: dict) -> list[str]:
    """Type/enum problems in an already-parsed config, phrased for a reader."""
    problems: list[str] = []
    for key, value in cfg.items():
        entry = BY_KEY.get(key)
        if entry is None or value is None:
            continue
        kind, name = entry.type, entry.label
        if kind == "bool" and not isinstance(value, bool):
            problems.append(f"{key}: '{name}' must be yes or no.")
        elif kind == "int" and (isinstance(value, bool) or not isinstance(value, int)):
            problems.append(f"{key}: '{name}' must be a whole number (it is set to {value!r}).")
        elif kind == "float" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            problems.append(f"{key}: '{name}' must be a number (it is set to {value!r}).")
        elif kind == "list" and not isinstance(value, list):
            problems.append(f"{key}: '{name}' must be a list.")
        elif kind == "object" and not isinstance(value, dict):
            problems.append(f"{key}: '{name}' must be a set of name/value pairs.")
        elif kind in {"string", "guid"} and not isinstance(value, str):
            problems.append(f"{key}: '{name}' must be text.")
        elif kind == "enum":
            if not isinstance(value, str):
                problems.append(f"{key}: '{name}' must be text.")
            elif entry.choices and value not in entry.choices:
                problems.append(
                    f"{key}: '{name}' must be one of {', '.join(entry.choices)} "
                    f"(it is set to {value!r})."
                )
    return problems


def schema_order(keys: Iterable[str]) -> list[str]:
    """Order keys the way the wizard presents them; unknown keys sort last."""
    index = {entry.key: position for position, entry in enumerate(KEYS)}
    known = sorted((k for k in keys if k in index), key=lambda k: index[k])
    unknown = sorted(k for k in keys if k not in index)
    return known + unknown
