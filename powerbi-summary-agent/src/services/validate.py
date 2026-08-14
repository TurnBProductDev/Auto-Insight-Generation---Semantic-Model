"""Config validation: the destructive defaults, stated before they destroy.

Most keys are harmless if wrong. A handful are not, and they share a shape -
they fail silently, after the run, in someone else's data:

* ``azure_blob_prefix`` is not dataset-scoped, so two clients sharing a
  container with the same prefix overwrite each other's ``api/*.json``.
* ``ai_content_client`` names an existing blob container; it is not created.
* ``output_folder`` other than ``outputs`` is permission-denied in the image,
  because ``/app`` is root-owned and only ``/app/outputs`` is writable.
* ``summary_r4_enabled`` / ``summary_r6_enabled`` absent silently reverts to the
  R1-R3 summary - which is exactly how production drifted.
* ``summary_dashboard_replaces_summary_html`` changes what the live app serves.

Errors block a deployment. Warnings do not, but they are things a reviewer
should have to read. Every check is pure except the two that take an explicit
``existing`` / ``containers`` argument, so this module needs no credentials and
is fully testable offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .. import config_schema

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_CLIENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")

#: Keys whose absence changes behaviour silently rather than failing. The UI
#: must always write them explicitly.
MUST_BE_EXPLICIT = (
    "summary_r4_enabled",
    "summary_r6_enabled",
    "insight_memory_storage",
    "summary_memory_storage",
)


@dataclass
class Finding:
    level: str  # error | warning | info
    key: str
    message: str
    fix: str = ""

    @property
    def title(self) -> str:
        """The plain name of the setting, for someone who has never seen the key."""
        if self.key == "__probe__":
            return "Data check"
        return config_schema.label(self.key)

    def json(self) -> dict:
        return {
            "level": self.level,
            "key": self.key,
            "title": self.title,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, key: str, message: str, fix: str = "") -> None:
        self.findings.append(Finding("error", key, message, fix))

    def warn(self, key: str, message: str, fix: str = "") -> None:
        self.findings.append(Finding("warning", key, message, fix))

    def info(self, key: str, message: str, fix: str = "") -> None:
        self.findings.append(Finding("info", key, message, fix))

    def json(self) -> dict:
        return {
            "ok": self.ok,
            "errorCount": len(self.errors),
            "warningCount": len(self.warnings),
            "findings": [f.json() for f in self.findings],
        }


def _known_timezone(name: str) -> bool:
    """An unsupported IANA name must be rejected loudly, never silently naive."""
    if not name or name == "naive":
        return True
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)
        return True
    except Exception:  # noqa: BLE001 - any resolution failure means "not a zone"
        return False


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_identity(cfg: dict, report: ValidationReport) -> None:
    for key in ("tenant_id", "workspace_id", "dataset_id"):
        name = config_schema.label(key)
        value = str(cfg.get(key) or "").strip()
        if not value:
            report.error(key, f"{name} is empty, and the agent cannot run without it.",
                         "Fill it in on the Connect step.")
        elif value.startswith("PASTE_"):
            report.error(key, f"{name} still has the example text in it, not a real value.",
                         "Replace it with the real ID from Power BI.")
        elif not _GUID.match(value):
            report.error(
                key,
                f"{name} does not look like an ID. It should be 36 characters of letters, digits "
                f"and dashes, like 1a2b3c4d-5e6f-...",
                "Copy it again from the Power BI web address.",
            )
    if cfg.get("workspace_id") and cfg.get("dataset_id") and cfg["workspace_id"] == cfg["dataset_id"]:
        report.error("dataset_id",
                     "The workspace ID and the dataset ID are the same, so one of them is wrong.",
                     "The dataset ID identifies the data behind the dashboard, not the workspace "
                     "holding it. Use 'Find the dataset' on the Connect step.")


def _check_types(cfg: dict, report: ValidationReport) -> None:
    for message in config_schema.type_errors(cfg):
        key = message.split(" ", 1)[0]
        report.error(key, message)
    for key in config_schema.unknown_keys(cfg):
        report.warn(key, f"'{key}' is not a setting the agent recognises, so it does nothing.",
                    "Safe to remove. If it is a genuinely new setting, it needs adding to the "
                    "catalogue in src/config_schema.py first.")
    for entry in config_schema.KEYS:
        if entry.dead and entry.key in cfg:
            report.warn(entry.key,
                        "This is left over from a feature that no longer exists. Nothing reads "
                        "it, so changing it has no effect.",
                        "Safe to remove.")


def _check_explicit_flags(cfg: dict, report: ValidationReport) -> None:
    for key in MUST_BE_EXPLICIT:
        if key not in cfg:
            entry = config_schema.get(key)
            shown = {True: "yes", False: "no"}.get(entry.default, entry.default)
            report.error(
                key,
                f"'{entry.label}' has not been answered, so the agent will quietly assume "
                f"'{shown}'.",
                "Choose it deliberately, either way. This is the setting most often forgotten, "
                "and forgetting it removes part of the report with no error to warn you.",
            )


#: The env-var -> config-key map ``main._apply_environment_overrides`` applies.
#: Env wins. Setting both and letting them disagree is the single most likely
#: bug in a deployment, so the UI is told about every disagreement by name.
ENV_OVERRIDES = {
    "POWERBI_TENANT_ID": "tenant_id",
    "POWERBI_WORKSPACE_ID": "workspace_id",
    "POWERBI_DATASET_ID": "dataset_id",
    "POWERBI_QUERY_API": "powerbi_query_api",
    "POWERBI_EFFECTIVE_USERNAME": "powerbi_effective_username",
    "POWERBI_AUTH_MODE": "powerbi_auth_mode",
    "AGENT_OUTPUT_FOLDER": "output_folder",
    "INSIGHT_HISTORY_TIMEZONE": "insight_history_timezone",
    "INSIGHT_MEMORY_STORAGE": "insight_memory_storage",
    "INSIGHT_MEMORY_RUNTIME_FOLDER": "insight_memory_runtime_folder",
    "SUMMARY_HISTORY_TIMEZONE": "summary_history_timezone",
    "SUMMARY_MEMORY_STORAGE": "summary_memory_storage",
    "SUMMARY_MEMORY_RUNTIME_FOLDER": "summary_memory_runtime_folder",
    "AZURE_BLOB_ACCOUNT": "azure_blob_account",
    "AZURE_BLOB_CONTAINER": "azure_blob_container",
    "AZURE_BLOB_PREFIX": "azure_blob_prefix",
    "AZURE_BLOB_HISTORY_PREFIX": "azure_blob_history_prefix",
    "AZURE_BLOB_HISTORY_FEED": "azure_blob_history_feed",
    "AZURE_BLOB_MEMORY_CONTAINER": "azure_blob_memory_container",
    "AZURE_BLOB_MEMORY_PREFIX": "azure_blob_memory_prefix",
    "AZURE_BLOB_SUMMARY_HISTORY_PREFIX": "azure_blob_summary_history_prefix",
    "AZURE_BLOB_SUMMARY_HISTORY_FEED": "azure_blob_summary_history_feed",
    "AZURE_BLOB_SUMMARY_MEMORY_PREFIX": "azure_blob_summary_memory_prefix",
    "AI_CONTENT_CLIENT": "ai_content_client",
    "POWERBI_REPORT_ID": "ai_content_report_id",
    "AI_CONTENT_REPORT_IDS": "ai_content_report_ids",
    "AZURE_BLOB_UPLOAD": "azure_blob_upload",
    "INSIGHT_HISTORY_ENABLED": "insight_history_enabled",
    "FRESH_SUMMARY_ENABLED": "fresh_summary_enabled",
    "SUMMARY_HISTORY_ENABLED": "summary_history_enabled",
    "SUMMARY_MEMORY_ENABLED": "summary_memory_enabled",
    "SUMMARY_VISUAL_ENABLED": "summary_visual_enabled",
    "AI_CONTENT_PUBLISH_ENABLED": "ai_content_publish_enabled",
}


def effective(cfg: dict, env: dict | None = None) -> dict:
    """What the run will actually see once environment overrides are applied.

    Mirrors ``main._apply_environment_overrides`` exactly, including the part
    that catches people out: presence is what counts, not truthiness. An
    ``AZURE_BLOB_PREFIX`` set to the empty string overrides a configured prefix
    back to the container root - and the container root is where another
    client's payloads already live.
    """
    merged = dict(cfg)
    for env_name, key in ENV_OVERRIDES.items():
        if not env or env_name not in env:
            continue
        raw = env[env_name]
        entry = config_schema.get(key)
        if entry and entry.type == "bool":
            raw = str(raw).strip().lower() in {"1", "true", "yes", "on"}
        merged[key] = raw
    return merged


def _check_env_overrides(cfg: dict, report: ValidationReport, *, env: dict | None) -> None:
    if not env:
        return
    for env_name, key in ENV_OVERRIDES.items():
        if env_name not in env:
            continue
        configured = cfg.get(key)
        override = env[env_name]
        if configured is None or str(configured) == str(override):
            continue
        report.warn(
            key,
            f"The cloud job sets {config_schema.label(key)!r} to {override!r}, which overrides the "
            f"{configured!r} on this form. The job's value is the one that will be used.",
            "Set it in one place, not both. Two different answers to the same question is the "
            "most common cause of a job behaving differently from what the form says.",
        )


def _check_output_folder(cfg: dict, report: ValidationReport, *, target: str, env: dict | None) -> None:
    folder = str(cfg.get("output_folder") or "outputs")
    resolved = str((env or {}).get("AGENT_OUTPUT_FOLDER") or folder)
    if target == "container" and resolved != "outputs":
        report.error(
            "output_folder",
            f"In the cloud the agent would try to save into '{resolved}', which it is not allowed "
            "to write to. The run would fail immediately.",
            "Set the folder to 'outputs', or add AGENT_OUTPUT_FOLDER=outputs to the job's "
            "environment on the Go live step.",
        )
    elif target == "container" and folder != "outputs":
        report.info(
            "output_folder",
            f"On this computer reports go to '{folder}'. In the cloud the job's environment "
            "redirects them to 'outputs', which is correct.",
        )
    if folder.startswith("/") or (len(folder) > 1 and folder[1] == ":"):
        report.warn("output_folder",
                    "This is a full path starting from the drive root. Everywhere else the folder "
                    "is treated as being inside the project, so this may not end up where you "
                    "expect.")


def _check_blob(cfg: dict, report: ValidationReport, *, existing: Iterable[dict], containers: Iterable[str] | None) -> None:
    upload = bool(cfg.get("azure_blob_upload"))
    container = str(cfg.get("azure_blob_container") or "insightgen")
    prefix = str(cfg.get("azure_blob_prefix") or "")

    if upload and not cfg.get("azure_blob_account"):
        report.error("azure_blob_account",
                     "Uploading to cloud storage is switched on, but no storage account is named, "
                     "so there is nowhere to upload to.",
                     "Enter the storage account name, or switch the upload off.")

    # The collision check is the single most valuable thing in this module: the
    # failure is silent, it lands in another client's data, and it is only
    # visible as stale payloads days later.
    for other in existing:
        other_cfg = other.get("config") or {}
        if other.get("name") and other.get("name") == cfg.get("__client_name__"):
            continue
        if str(other_cfg.get("dataset_id") or "") == str(cfg.get("dataset_id") or ""):
            continue
        same_container = str(other_cfg.get("azure_blob_container") or "insightgen") == container
        same_prefix = str(other_cfg.get("azure_blob_prefix") or "") == prefix
        if same_container and same_prefix:
            where = f"the folder {prefix!r}" if prefix else "the top level"
            report.error(
                "azure_blob_prefix",
                f"The client {other.get('name')!r} already saves its files to exactly this place: "
                f"container {container!r}, {where}. Whichever of the two runs second would "
                "overwrite the other's reports, and nothing would report an error.",
                "Give this client a folder name of its own - the client's own name is a good "
                "choice.",
            )

    ai_client = str(cfg.get("ai_content_client") or "")
    if cfg.get("ai_content_publish_enabled"):
        if not ai_client:
            report.error("ai_content_client",
                         "Publishing into your app's storage is switched on, but no storage "
                         "container has been named.",
                         "Enter the container name, or switch the publishing off.")
        elif containers is not None and ai_client not in set(containers):
            report.error(
                "ai_content_client",
                f"There is no storage container called {ai_client!r}. It is not created for you, "
                "so publishing would fail on every run.",
                "Ask whoever manages your storage to create it, or choose one that exists: "
                f"{', '.join(sorted(containers)[:8]) or 'none were found'}.",
            )
    if ai_client and not _CLIENT_NAME.match(ai_client):
        report.warn("ai_content_client",
                    f"{ai_client!r} cannot be a storage container name.",
                    "Use lowercase letters, digits and hyphens only, 3 to 40 characters.")

    for key in ("insight_memory_storage", "summary_memory_storage"):
        if str(cfg.get(key) or "local") == "local":
            report.warn(
                key,
                f"{config_schema.label(key)!r} is set to this computer. A scheduled cloud job gets "
                "a brand new machine every run, so anything remembered there is thrown away - and "
                "you would be told the same things again every morning.",
                "Change it to cloud storage before scheduling this client.",
            )


def _check_features(cfg: dict, report: ValidationReport) -> None:
    if cfg.get("summary_r6_enabled") and not cfg.get("summary_r4_enabled"):
        report.warn(
            "summary_r4_enabled",
            "The interactive dashboard is on, but the balanced multi-area report is off, so the "
            "dashboard's areas section will have nothing to show.",
            "Switch the balanced report on as well.",
        )
    if cfg.get("summary_dashboard_replaces_summary_html"):
        report.warn(
            "summary_dashboard_replaces_summary_html",
            "From the next run onwards, everyone using your app sees the interactive dashboard "
            "instead of the ordinary summary page.",
            "Only leave this on if you have already looked at a finished dashboard for this "
            "client and are happy with it.",
        )
    if not cfg.get("fresh_summary_enabled", True):
        report.warn("fresh_summary_enabled",
                    "The modern summary is switched off, so this client gets a much older and "
                    "plainer report with none of the features on this page.",
                    "Switch it back on unless you have a specific reason not to.")
    if cfg.get("summary_now_override"):
        report.error("summary_now_override",
                     "A fixed date has been set, so the agent will believe it is that date "
                     "forever and every report will be wrong.",
                     "Clear this box. It exists only for testing.")
    if cfg.get("summary_focus_public_metadata"):
        report.info("summary_focus_public_metadata",
                    "An extra field naming the report's chosen topics will be added to the app "
                    "data file.",
                    "Confirm with whoever maintains the app that it expects this field.")

    target = int(cfg.get("summary_focus_target_count", 3) or 3)
    per_focus = int(cfg.get("summary_focus_max_queries_per_focus", 5) or 5)
    total = int(cfg.get("summary_focus_total_deep_dive_queries",
                        cfg.get("summary_focus_max_queries", 15)) or 15)
    if target * per_focus > total:
        report.warn(
            "summary_focus_total_deep_dive_queries",
            f"Covering {target} areas at up to {per_focus} queries each needs "
            f"{target * per_focus} queries, but only {total} are allowed in total. The last areas "
            "would be explained in less depth than the first.",
            f"Raise the total to {target * per_focus}, or cover fewer areas.",
        )


def _check_timezones(cfg: dict, report: ValidationReport) -> None:
    for key in ("summary_focus_timezone", "summary_history_timezone",
                "insight_history_timezone", "insight_business_timezone"):
        value = str(cfg.get(key) or "").strip()
        if not value:
            continue
        if key == "insight_business_timezone" and value == "auto":
            report.error(key,
                         "'auto' is not allowed here. The agent will not guess which day a sale "
                         "belongs to, because guessing wrong moves sales between days.",
                         "Use 'naive' to take dates exactly as stored, or a real time zone name "
                         "such as Asia/Kolkata.")
            continue
        if not _known_timezone(value):
            report.error(key,
                         f"{value!r} is not a time zone the agent recognises, so the run would "
                         "stop rather than guess.",
                         "Use a standard name such as Asia/Kolkata, Asia/Riyadh, Europe/London or "
                         "America/New_York.")


def _check_roles(cfg: dict, report: ValidationReport, *, probe: dict | None) -> None:
    focus = [str(r).strip().casefold() for r in (cfg.get("summary_focus_allowed_roles") or [])]
    coverage = [str(r).strip().casefold() for r in (cfg.get("summary_coverage_roles") or [])]

    if not focus:
        report.error("summary_focus_allowed_roles",
                     "No product level has been chosen, so the report has nothing it is allowed "
                     "to write a story about.",
                     "Pick at least one level on the 'Product levels' step.")
    # 'store' is a level the agent knows perfectly well - it is just not part of
    # the product hierarchy. Reporting it as unrecognised alongside the specific
    # explanation below gives one mistake two contradictory messages.
    unknown = [
        r for r in focus
        if r not in config_schema.HIERARCHY_ROLES and r not in config_schema.COVERAGE_ROLES
    ]
    if unknown:
        report.error(
            "summary_focus_allowed_roles",
            f"The agent does not know what these levels are: {', '.join(unknown)}.",
            "Either pick from the standard levels (division, department, section, category and "
            "so on), or use 'Rename your levels to standard ones' to say which standard level "
            "each of yours corresponds to.",
        )
    if "store" in focus:
        report.error("summary_focus_allowed_roles",
                     "Stores cannot be the subject of a written story. A store is not a level of "
                     "the product hierarchy - every category exists inside every store - so "
                     "treating it as one would confuse the report's structure.",
                     "Remove it here. Stores still get a full ranked table row: add them under "
                     "'Levels that get a full ranked table' instead.")
    missing_coverage = [r for r in focus if r not in coverage]
    if missing_coverage:
        report.warn("summary_coverage_roles",
                    f"These levels get a written story but no ranked table: "
                    f"{', '.join(missing_coverage)}. A reader could see one member discussed with "
                    "nothing to compare it against.",
                    "Add them here as well - this list should include everything above it.")

    aliases = cfg.get("summary_focus_role_aliases") or {}

    # The rename box is an escape hatch for a level the agent could NOT find.
    # Pointing it at a level that resolved on its own silently moves that level
    # somewhere it does not belong - renaming Division to Department does not
    # add a Department, it destroys the Division.
    resolved_now = {r["role"] for r in (probe or {}).get("roles", {}).get("resolved", [])}
    for key, value in aliases.items():
        left = str(key).strip().casefold()
        right = str(value).strip().casefold()
        if left == right:
            report.warn("summary_focus_role_aliases",
                        f"Renaming '{left}' to itself does nothing.",
                        "Remove this line.")
        elif left in config_schema.HIERARCHY_ROLES and left in resolved_now:
            report.error(
                "summary_focus_role_aliases",
                f"'{left}' is already a level the data check found in this dashboard, and this "
                f"line renames it to '{right}'. That does not add a '{right}' level - it removes "
                f"the '{left}' one, and any story about it goes with it.",
                "This box is only for levels the check could NOT find. Remove this line.",
            )
        elif left in config_schema.HIERARCHY_ROLES:
            report.warn(
                "summary_focus_role_aliases",
                f"'{left}' is already a standard level name, so renaming it to '{right}' is "
                "unusual.",
                "The left side should be what YOUR dashboard calls the level, not a standard name.",
            )

    bad_alias = [f"{k} -> {v}" for k, v in aliases.items()
                 if str(v).strip().casefold() not in config_schema.HIERARCHY_ROLES]
    if bad_alias:
        report.error("summary_focus_role_aliases",
                     f"These renames point at something the agent does not recognise: "
                     f"{', '.join(bad_alias)}.",
                     "The right-hand side must be one of: "
                     f"{', '.join(config_schema.HIERARCHY_ROLES[:6])}.")

    budget = int(cfg.get("summary_focus_universe_max_queries", 4) or 4)
    if len(focus) > budget:
        report.warn("summary_focus_universe_max_queries",
                    f"You chose {len(focus)} levels for written stories, but only {budget} "
                    f"queries are allowed to look at them, so the last "
                    f"{len(focus) - budget} would be skipped entirely.",
                    f"Raise the query allowance to {len(focus)}, or choose fewer levels.")
    coverage_only = [r for r in coverage if r not in focus]
    coverage_budget = int(cfg.get("summary_coverage_max_queries", 3) or 3)
    if len(coverage_only) > coverage_budget:
        report.warn("summary_coverage_max_queries",
                    f"{len(coverage_only)} levels need a ranked table of their own, but only "
                    f"{coverage_budget} queries are allowed for them, so some tables would be "
                    "missing.",
                    f"Raise the allowance to {len(coverage_only)}.")

    if not probe:
        return

    # Roles the probe could not resolve will simply produce nothing.
    resolved = {r["role"] for r in (probe.get("roles") or {}).get("resolved", [])}
    if resolved:
        for role in focus:
            if role not in resolved:
                report.error(
                    "summary_focus_allowed_roles",
                    f"The data check did not find a '{role}' level in this dashboard, so it can "
                    "never produce a story.",
                    f"The levels this dashboard actually has are: "
                    f"{', '.join(sorted(resolved)) or 'none were found'}.",
                )
        for role in coverage:
            if role not in resolved:
                report.warn("summary_coverage_roles",
                            f"The data check did not find a '{role}' level, so it will simply be "
                            "skipped.",
                            f"Available levels: {', '.join(sorted(resolved))}.")

    entity_role = str(cfg.get("summary_dashboard_entity_role") or "")
    if entity_role and resolved and entity_role.casefold() not in resolved:
        report.error("summary_dashboard_entity_role",
                     f"'{entity_role}' is not a level this dashboard has.",
                     f"Choose one of: {', '.join(sorted(resolved))}.")
    if not entity_role and probe.get("model") and not probe["model"].get("entityResolved"):
        report.error(
            "summary_dashboard_entity_role",
            "The data check could not work out which column identifies your stores, and no level "
            "has been chosen instead - so the dashboard has nothing to build its per-location "
            "cards from.",
            "Choose a level here. Department is often a safe choice: pick one where the figures "
            "add up to the company total.",
        )

    exposure_role = str(cfg.get("summary_dashboard_exposure_role") or "")
    if exposure_role and resolved and exposure_role.casefold() not in resolved:
        report.error("summary_dashboard_exposure_role",
                     f"'{exposure_role}' is not a level this dashboard has.",
                     f"Choose one of: {', '.join(sorted(resolved))}, or leave it empty.")


def _check_populations(cfg: dict, report: ValidationReport, *, probe: dict | None) -> None:
    if not probe:
        return
    entities = probe.get("entities") or {}
    known = {
        str(code) for code in
        (entities.get("comparable") or []) + (entities.get("excluded") or [])
        + (entities.get("currentOnly") or []) + (entities.get("priorOnly") or [])
    }
    if not known:
        return
    for key in ("insight_comparable_population", "insight_excluded_entities"):
        unknown = [str(code) for code in (cfg.get(key) or []) if str(code) not in known]
        if unknown:
            report.error(
                key,
                f"{len(unknown)} of these do not exist in the dashboard's data: "
                f"{', '.join(unknown[:6])}{'...' if len(unknown) > 6 else ''}. They would be "
                "silently ignored.",
                "Check the spelling, or pick from the list the data check produced.",
            )
    overlap = set(map(str, cfg.get("insight_comparable_population") or [])) & set(
        map(str, cfg.get("insight_excluded_entities") or [])
    )
    if overlap:
        report.error("insight_excluded_entities",
                     f"These shops are listed both as comparable and as excluded, which cannot "
                     f"both be true: {', '.join(sorted(overlap))}.",
                     "Remove them from one list or the other.")


def _check_probe_state(report: ValidationReport, *, probe: dict | None, target: str) -> None:
    if probe is None:
        if target == "container":
            report.error("__probe__",
                         "The data check has not been run, so nobody has confirmed this "
                         "dashboard's figures add up.",
                         "Go to the 'Check the data' step and run it. Several answers on this "
                         "form cannot be verified without it.")
        else:
            report.warn("__probe__",
                        "The data check has not been run yet, so the answers about product "
                        "levels and shops have not been verified against the real dashboard.",
                        "Go to the 'Check the data' step and run it.")
        return
    # ProbeResult.reason is set to blocking[0], so reporting both prints the
    # same sentence twice and makes one problem look like two.
    blockers = list(probe.get("blocking") or [])
    if not blockers and probe.get("status") == "failed":
        blockers = [str(probe.get("reason") or "The data check failed.")]
    for index, blocker in enumerate(blockers):
        report.error(
            "__probe__", blocker,
            "Fix this, then run the data check again." if index == len(blockers) - 1 else "",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def validate(
    cfg: dict,
    *,
    target: str = "local",
    probe: dict | None = None,
    existing_clients: Iterable[dict] = (),
    containers: Iterable[str] | None = None,
    client_name: str = "",
    env: dict | None = None,
) -> ValidationReport:
    """Validate a config for ``target`` ('local' or 'container').

    ``probe`` is a :class:`~src.services.probe.ProbeResult` as a dict. When it
    is present the role, population and reconciliation checks become real
    rather than structural - which is why the container target refuses to pass
    without one.

    ``env`` is the deployment's environment block. Because env wins over
    config, the checks run against the *resolved* values, and every silent
    disagreement between the two is reported by name.
    """
    report = ValidationReport()
    cfg = dict(cfg)
    if client_name:
        cfg["__client_name__"] = client_name

    # Root cause first. When the model itself cannot be used, the settings
    # findings below are all consequences of that, and burying it under them
    # sends someone to fix the wrong thing.
    _check_probe_state(report, probe=probe, target=target)
    _check_identity(cfg, report)
    _check_types({k: v for k, v in cfg.items() if not k.startswith("__")}, report)
    _check_explicit_flags(cfg, report)
    _check_env_overrides(cfg, report, env=env)
    _check_output_folder(cfg, report, target=target, env=env)
    _check_blob(effective(cfg, env), report, existing=existing_clients, containers=containers)
    _check_features(cfg, report)
    _check_timezones(cfg, report)
    _check_roles(cfg, report, probe=probe)
    _check_populations(cfg, report, probe=probe)
    return report


def validate_rulebooks(business_rules: str, summary_rules: str) -> ValidationReport:
    """Structural checks only - semantic correctness cannot be automated.

    These are 39-45 KB human-authored documents encoding company calculation
    policy, injected into every insight/DAX prompt. A UI can check that one
    exists, is not a placeholder and is not so large it crowds out the model
    context; it cannot check that it is right.
    """
    report = ValidationReport()
    for label, key, text, floor in (
        ("business_rules.md", "business_rules", business_rules, 500),
        ("summary_business_rules.md", "summary_business_rules", summary_rules, 200),
    ):
        size = len(text.encode("utf-8"))
        if not text.strip():
            report.warn(key,
                        f"{label} is empty. The agent will use generic accounting assumptions "
                        "rather than how your business actually calculates things.",
                        "Paste in your rules, or start from the template.")
            continue
        if size < floor:
            report.warn(key,
                        f"{label} is only {size} characters, which is far shorter than a working "
                        "rulebook. It may be a stub rather than the real document.")
        if size > 120_000:
            report.warn(key,
                        f"{label} is {size / 1024:.0f} KB. Everything in it is sent to the AI on "
                        "every single request, so a document this long leaves less room for your "
                        "actual data and costs more per run.",
                        "Trim it to the rules that genuinely change the numbers.")
        if "PASTE_" in text or "TODO" in text:
            report.warn(key,
                        f"{label} still contains placeholder text (PASTE_ or TODO), which the AI "
                        "will read as if it were a real rule.")
        # base64 of the rulebook becomes a container-app secret; the CLI path
        # breaks well before the ARM limit, which is why deploy uses a body file.
        if size * 4 / 3 > 32_767:
            report.info(key,
                        f"{label} is large enough that it cannot be uploaded by the usual command "
                        "line tool. This app uploads it a different way, so there is nothing for "
                        "you to do - it is noted only in case someone tries to deploy by hand.")
    return report


def merge(*reports: ValidationReport) -> ValidationReport:
    out = ValidationReport()
    for report in reports:
        out.findings.extend(report.findings)
    return out
