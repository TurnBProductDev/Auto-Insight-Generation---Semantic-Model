"""Offline replay: the client-onboarding services and API.

Covers the parts of onboarding where being wrong is expensive and silent:

* a config written by the UI round-trips byte-identically, so re-onboarding an
  existing client produces no diff (the regression test that proves the UI
  models the real surface rather than an approximation of it)
* the destructive-default guards actually refuse - prefix collision, missing
  ai-content container, output_folder in the container, unset R4/R6, an
  unsupported timezone, a role or entity the model does not have
* env-versus-config disagreements are reported, because env wins silently
* an ARM upsert carries forward secrets it does not own, since ARM replaces the
  whole array and never returns a stored value
* the probe's findings translate into blocking errors and key recommendations
* the API surface answers, and the deployment endpoints stay shut by default

No Power BI, Azure, or LLM credentials are required, and no live call is made.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import config_schema  # noqa: E402
from src.services import clients, deploy, jobs, validate  # noqa: E402
from src.services.probe import ProbeResult, _derive_findings  # noqa: E402

FAILURES: list[str] = []
TEST_CLIENT = "zz-replay-client"
TEST_CLONE = "zz-replay-clone"


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _base_config(**overrides) -> dict:
    config = clients.new_config(
        tenant_id="315642c5-e14a-4c12-bf77-41ee070def79",
        workspace_id="7111406b-1fff-4a8b-bd52-fa6131682262",
        dataset_id="643336e7-4360-4b56-82f8-7b72cefad3ed",
        output_folder="outputs",
        summary_r4_enabled=True,
        summary_r6_enabled=True,
        insight_memory_storage="azure_blob",
        summary_memory_storage="azure_blob",
    )
    config.update(overrides)
    return config


# ---------------------------------------------------------------------------


def test_round_trip() -> None:
    print("\nA committed config round-trips byte-identically")
    for name in ("scanb", "experiment"):
        directory = clients.CONFIG_ROOT / name
        if not (directory / clients.CONFIG_NAME).exists():
            continue
        record = clients.load_client(name)
        rendered = clients.dumps_config(
            record.config, key_order=record.key_order, newline=record.newline
        ).encode("utf-8")
        original = (directory / clients.CONFIG_NAME).read_bytes()
        check(f"config/{name}/config.json re-renders byte for byte",
              rendered == original,
              f"{len(rendered)} vs {len(original)} bytes")

    root = clients.CONFIG_ROOT / clients.CONFIG_NAME
    if root.exists():
        record = clients.load_config_file(root)
        rendered = clients.dumps_config(
            record.config, key_order=record.key_order, newline=record.newline
        ).encode("utf-8")
        check("config/config.json re-renders byte for byte", rendered == root.read_bytes())

    # CRLF is preserved, and a new key lands in wizard order at the end.
    crlf = clients.dumps_config({"b": 1, "a": 2}, key_order=["b", "a"], newline="\r\n")
    check("line endings are preserved", crlf.endswith("}\r\n") and "\r\n" in crlf)
    ordered = clients.dumps_config(
        {"summary_r6_enabled": True, "tenant_id": "t"}, key_order=["summary_r6_enabled"]
    )
    check("known keys keep their file order, new keys append in wizard order",
          list(json.loads(ordered)) == ["summary_r6_enabled", "tenant_id"])


def test_client_store() -> None:
    print("\nWriting, cloning and bundling a client")
    for name in (TEST_CLIENT, TEST_CLONE):
        try:
            clients.delete_client(name)
        except clients.ClientError:
            pass

    record = clients.save_client(
        TEST_CLIENT, _base_config(azure_blob_prefix="zzreplay", ai_content_client="zzreplay"),
        business_rules="# rules\n" + "x" * 900,
        summary_business_rules="# summary rules\n" + "y" * 400,
    )
    check("three files are written", record.exists
          and (Path(record.path) / clients.RULES_NAME).exists()
          and (Path(record.path) / clients.SUMMARY_RULES_NAME).exists())
    check("every schema key is written explicitly",
          set(record.config) >= set(config_schema.defaults()),
          f"missing: {sorted(set(config_schema.defaults()) - set(record.config))[:5]}")

    # Saving config edits alone must not blank a 45 KB rulebook.
    again = clients.save_client(TEST_CLIENT, {**record.config, "summary_dashboard_tldr": 6})
    check("a config-only save leaves the rulebooks untouched",
          again.business_rules == record.business_rules
          and again.summary_business_rules == record.summary_business_rules)
    check("the edit landed", again.config["summary_dashboard_tldr"] == 6)

    clone = clients.clone_client(TEST_CLIENT, TEST_CLONE)
    check("cloning copies the rulebooks", clone.business_rules == record.business_rules)
    check("cloning clears azure_blob_prefix rather than colliding",
          clone.config["azure_blob_prefix"] == config_schema.BY_KEY["azure_blob_prefix"].default)
    check("cloning clears ai_content_client", clone.config["ai_content_client"] == "")
    check("cloning keeps the shared keys", clone.config["summary_r6_enabled"] is True)

    archive = clients.bundle(TEST_CLIENT)
    check("the bundle is a non-trivial zip", archive[:2] == b"PK" and len(archive) > 400)

    check("a traversing client name is refused", _raises(lambda: clients.client_dir("../evil")))
    check("an absolute client name is refused", _raises(lambda: clients.client_dir("/etc")))
    check("an empty client name is refused", _raises(lambda: clients.client_dir("")))

    check("deleting removes the directory", clients.delete_client(TEST_CLONE) is True)
    check("deleting twice is not an error", clients.delete_client(TEST_CLONE) is False)


def test_validation_guards() -> None:
    print("\nThe destructive defaults are refused, not warned about")
    others = [{"name": "cityflower", "config": {
        "dataset_id": "b3458a38-ad83-4e9a-b2f2-39d15c6aa22c",
        "azure_blob_container": "insightgen", "azure_blob_prefix": "",
    }}]

    collide = validate.validate(_base_config(azure_blob_prefix=""), existing_clients=others)
    check("a blob prefix collision is a blocking error",
          any(f.key == "azure_blob_prefix" and f.level == "error" for f in collide.findings))
    clear = validate.validate(_base_config(azure_blob_prefix="northstar"), existing_clients=others)
    check("a distinct prefix passes",
          not any(f.key == "azure_blob_prefix" and f.level == "error" for f in clear.findings))

    missing = validate.validate(
        _base_config(ai_content_publish_enabled=True, ai_content_client="northstar"),
        containers=["insightgen", "cityflower", "scanb"],
    )
    check("ai_content_client naming a container that does not exist blocks",
          any(f.key == "ai_content_client" and f.level == "error" for f in missing.findings))
    present = validate.validate(
        _base_config(ai_content_publish_enabled=True, ai_content_client="scanb"),
        containers=["insightgen", "scanb"],
    )
    check("an existing container passes",
          not any(f.key == "ai_content_client" and f.level == "error" for f in present.findings))

    folder = validate.validate(_base_config(output_folder="outputs_x"), target="container")
    check("output_folder other than 'outputs' blocks a container deploy",
          any(f.key == "output_folder" and f.level == "error" for f in folder.findings))
    overridden = validate.validate(
        _base_config(output_folder="outputs_x"), target="container",
        env={"AGENT_OUTPUT_FOLDER": "outputs"},
    )
    check("AGENT_OUTPUT_FOLDER=outputs resolves it",
          not any(f.key == "output_folder" and f.level == "error" for f in overridden.findings))

    bare = dict(_base_config())
    for key in ("summary_r4_enabled", "summary_r6_enabled"):
        bare.pop(key)
    report = validate.validate(bare)
    check("an absent R4/R6 flag blocks - the key silently reverts to R1-R3",
          {f.key for f in report.errors} >= {"summary_r4_enabled", "summary_r6_enabled"})

    timezone = validate.validate(_base_config(summary_focus_timezone="Mars/Olympus"))
    check("an unsupported IANA timezone blocks",
          any(f.key == "summary_focus_timezone" and f.level == "error" for f in timezone.findings))
    auto = validate.validate(_base_config(insight_business_timezone="auto"))
    check("insight_business_timezone='auto' blocks rather than falling back to naive",
          any(f.key == "insight_business_timezone" and f.level == "error" for f in auto.findings))

    now = validate.validate(_base_config(summary_now_override="2026-01-01"))
    check("summary_now_override blocks in any target",
          any(f.key == "summary_now_override" and f.level == "error" for f in now.findings))

    identity = validate.validate({**_base_config(), "dataset_id": "PASTE_DATASET_ID"})
    check("a PASTE_ placeholder blocks",
          any(f.key == "dataset_id" and f.level == "error" for f in identity.findings))
    same = validate.validate({**_base_config(), "dataset_id": _base_config()["workspace_id"]})
    check("dataset_id equal to workspace_id blocks - a report id is not a dataset id",
          any(f.key == "dataset_id" and f.level == "error" for f in same.findings))

    replaces = validate.validate(_base_config(summary_dashboard_replaces_summary_html=True))
    check("replacing report_summary.html warns that the live app changes",
          any(f.key == "summary_dashboard_replaces_summary_html" and f.level == "warning"
              for f in replaces.findings))

    local_memory = validate.validate(_base_config(insight_memory_storage="local"))
    check("local memory storage warns that rotation resets every run",
          any(f.key == "insight_memory_storage" and f.level == "warning" for f in local_memory.findings))


def test_env_disagreement() -> None:
    print("\nEnv-versus-config disagreements are named, because env wins silently")
    report = validate.validate(
        _base_config(azure_blob_prefix="northstar"),
        env={"AZURE_BLOB_PREFIX": "somethingelse"},
    )
    check("a disagreement is reported by key",
          any(f.key == "azure_blob_prefix" and "overrides" in f.message for f in report.findings))
    resolved = validate.effective(
        {"azure_blob_prefix": "a", "azure_blob_upload": False},
        {"AZURE_BLOB_PREFIX": "b", "AZURE_BLOB_UPLOAD": "true"},
    )
    check("effective() applies string overrides", resolved["azure_blob_prefix"] == "b")
    check("effective() coerces boolean overrides", resolved["azure_blob_upload"] is True)
    check("an agreeing env var is not reported",
          not any(f.key == "azure_blob_prefix" for f in validate.validate(
              _base_config(azure_blob_prefix="x"), env={"AZURE_BLOB_PREFIX": "x"}).findings))
    # The collision check must run against the resolved value, not the file.
    collide = validate.validate(
        _base_config(azure_blob_prefix="unique"),
        env={"AZURE_BLOB_PREFIX": ""},
        existing_clients=[{"name": "cityflower", "config": {
            "dataset_id": "other", "azure_blob_container": "insightgen", "azure_blob_prefix": ""}}],
    )
    check("a collision introduced by an env override is still caught",
          any(f.key == "azure_blob_prefix" and f.level == "error" for f in collide.findings))


def test_role_and_population_checks() -> None:
    print("\nRoles and populations are checked against what the model actually has")
    probe = {
        "status": "ok",
        "model": {"entityResolved": False},
        "roles": {"resolved": [
            {"role": "division", "focusEligible": True, "reconciled": True, "status": "ok"},
            {"role": "department", "focusEligible": True, "reconciled": True, "status": "ok"},
            {"role": "store", "coverageOnly": True, "focusEligible": False, "status": "ok"},
        ]},
        "entities": {"comparable": ["S1", "S2"], "excluded": [], "currentOnly": ["S9"], "priorOnly": []},
        "blocking": [],
    }
    report = validate.validate(
        _base_config(summary_focus_allowed_roles=["division", "category"],
                     summary_coverage_roles=["store", "division", "category"],
                     summary_dashboard_entity_role="department"),
        probe=probe,
    )
    check("a focus role the probe did not resolve blocks",
          any(f.key == "summary_focus_allowed_roles" and "category" in f.message and f.level == "error"
              for f in report.findings))
    check("pinning the entity role to a resolved level passes",
          not any(f.key == "summary_dashboard_entity_role" and f.level == "error" for f in report.findings))

    unpinned = validate.validate(
        _base_config(summary_focus_allowed_roles=["division"],
                     summary_coverage_roles=["store", "division"]),
        probe=probe,
    )
    check("entity=unresolved with no pinned entity role blocks",
          any(f.key == "summary_dashboard_entity_role" and f.level == "error" for f in unpinned.findings))

    store_focus = validate.validate(_base_config(summary_focus_allowed_roles=["store"]))
    store_finding = next((f for f in store_focus.errors
                          if f.key == "summary_focus_allowed_roles"), None)
    check("'store' can never consume a focus slot", store_finding is not None)
    check("and the reason is explained rather than asserted",
          store_finding is not None
          and "every category exists inside every store" in store_finding.message)

    alias = validate.validate(_base_config(summary_focus_role_aliases={"merch group": "widget"}))
    check("an alias must map onto a canonical role",
          any(f.key == "summary_focus_role_aliases" and f.level == "error" for f in alias.findings))

    # The rename box is an escape hatch for a level the check could NOT find.
    # Pointing it at one that resolved on its own destroys that level instead of
    # adding anything - renaming Division to Department removes the Division.
    hijack = validate.validate(
        _base_config(summary_focus_role_aliases={"division": "department"}), probe=probe)
    hijack_finding = next((f for f in hijack.errors
                           if f.key == "summary_focus_role_aliases"), None)
    check("renaming a level the check already found is blocked", hijack_finding is not None)
    check("and the consequence is spelled out",
          hijack_finding is not None and "removes the 'division' one" in hijack_finding.message)
    check("a legitimate alias for a level the model lacks is allowed",
          not any(f.key == "summary_focus_role_aliases" and f.level == "error"
                  for f in validate.validate(
                      _base_config(summary_focus_role_aliases={"merchandise group": "department"}),
                      probe=probe).findings))
    check("an alias pointing at itself is called out as pointless",
          any(f.key == "summary_focus_role_aliases" and "does nothing" in f.message
              for f in validate.validate(
                  _base_config(summary_focus_role_aliases={"brand": "brand"})).findings))
    check("an empty rename box is never a finding",
          not any(f.key == "summary_focus_role_aliases"
                  for f in validate.validate(_base_config(), probe=probe).findings))

    population = validate.validate(
        _base_config(insight_comparable_population=["S1", "GHOST"]), probe=probe)
    check("an entity the model never returned blocks",
          any(f.key == "insight_comparable_population" and "GHOST" in f.message
              for f in population.findings))

    overlap = validate.validate(
        _base_config(insight_comparable_population=["S1"], insight_excluded_entities=["S1"]),
        probe=probe)
    check("an entity cannot be both comparable and excluded",
          any(f.key == "insight_excluded_entities" and f.level == "error" for f in overlap.findings))

    budget = validate.validate(_base_config(
        summary_focus_allowed_roles=["division", "department", "section", "category"],
        summary_focus_universe_max_queries=2))
    check("more focus roles than scans warns",
          any(f.key == "summary_focus_universe_max_queries" for f in budget.findings))

    failed_probe = validate.validate(
        _base_config(), target="container",
        probe={"status": "failed", "reason": "reconciliation", "blocking": ["level x did not reconcile"]})
    check("a failed probe blocks a deployment",
          any(f.key == "__probe__" and f.level == "error" for f in failed_probe.findings))
    check("a container deploy with no probe at all blocks",
          any(f.key == "__probe__" and f.level == "error"
              for f in validate.validate(_base_config(), target="container").findings))


def test_plain_language() -> None:
    """The words someone has to read are the product, so they are tested too."""
    print("\nMessages are written for someone who has not seen the code")

    # A message must not be the only place a key name appears - the reader has
    # no idea what azure_blob_prefix is, but does understand "storage folder".
    report = validate.validate(_base_config(azure_blob_prefix=""), existing_clients=[
        {"name": "cityflower", "config": {"dataset_id": "x", "azure_blob_container": "insightgen",
                                          "azure_blob_prefix": ""}}])
    collision = next(f for f in report.errors if f.key == "azure_blob_prefix")
    check("the collision error names the other client and the consequence",
          "cityflower" in collision.message and "overwrite" in collision.message)
    check("it says what to do about it", "folder name of its own" in collision.fix)
    check("it does not make the reader decode a key name",
          "azure_blob_prefix" not in collision.message)
    check("the finding carries a plain title", collision.title == "Folder name inside the container")

    missing = validate.validate({k: v for k, v in _base_config().items()
                                 if k != "summary_r6_enabled"})
    r6 = next(f for f in missing.errors if f.key == "summary_r6_enabled")
    check("an unanswered trap explains what silently happens instead",
          "quietly assume" in r6.message and "no" in r6.message)

    zone = validate.validate(_base_config(summary_focus_timezone="Mars/Olympus"))
    tz = next(f for f in zone.errors if f.key == "summary_focus_timezone")
    check("a bad timezone suggests real ones", "Asia/Kolkata" in tz.fix)

    # Every error a person can act on should say what to do about it.
    everything = validate.validate(
        _base_config(output_folder="wrong", summary_now_override="2026-01-01",
                     insight_business_timezone="auto", summary_focus_allowed_roles=["store"]),
        target="container")
    silent = [f.key for f in everything.errors if not f.fix and f.key != "__probe__"]
    check("every actionable error says what to do", not silent, f"no fix given for: {silent}")

    check("probe findings are phrased for a reader, not a maintainer",
          all(term not in f.message.lower()
              for f in everything.findings
              for term in ("reconcile", "coverage_kind", "state.get", "TREATAS")))


#: Blob paths observed in the live turnbtestblobstorage account on 2026-08-13.
#: The preview is only useful if it matches reality, so it is pinned to reality
#: rather than to itself. Both clients share the insightgen container and are
#: kept apart by azure_blob_prefix alone - which is exactly why a clash there is
#: a blocking error and not a warning.
LIVE_LAYOUT = {
    "cityflower": {
        "config": "config/config.json",
        "insightgen": [
            "report_summary.json",
            "kpi_insights.json",
            "insight_history.json",
            "summary_history.json",
            "history/b3458a38-ad83-4e9a-b2f2-39d15c6aa22c/2026/08/13/"
            "insightgen-daily-job-29776530.json",
            "summary-history/b3458a38-ad83-4e9a-b2f2-39d15c6aa22c/2026/08/13/"
            "insightgen-daily-job-29776530.json",
        ],
        "cityflower": [
            "ai-content/kpi/client/insights.json",
            "ai-content/kpi/client/alerts.json",
            "ai-content/report-summaries/client/20abf754-1bc0-444d-8789-baad7a1dca57.json",
            "ai-content/report-summaries/client/20abf754-1bc0-444d-8789-baad7a1dca57.html",
        ],
        "insightstate": [
            "b3458a38-ad83-4e9a-b2f2-39d15c6aa22c/memory.json",
            "summary-memory/b3458a38-ad83-4e9a-b2f2-39d15c6aa22c/memory.json",
        ],
    },
    "scanb": {
        "config": "config/scanb/config.json",
        "insightgen": [
            "scanb/report_summary.json",
            "scanb/kpi_insights.json",
            "scanb/insight_history.json",
            "scanb/summary_history.json",
            "scanb/history/643336e7-4360-4b56-82f8-7b72cefad3ed/2026/08/12/"
            "insightgen-scanb-daily-job-6eawv5d.json",
        ],
        "scanb": [
            "ai-content/kpi/client/insights.json",
            "ai-content/report-summaries/client/12f3b3b3-2db3-48b9-a483-4d7962aad92f.json",
            "ai-content/report-summaries/client/12f3b3b3-2db3-48b9-a483-4d7962aad92f.html",
        ],
        "insightstate": [
            "643336e7-4360-4b56-82f8-7b72cefad3ed/memory.json",
            "summary-memory/643336e7-4360-4b56-82f8-7b72cefad3ed/memory.json",
        ],
    },
}


def _matches(predicted: str, actual: str) -> bool:
    """A predicted path with {placeholders} matches a real dated blob."""
    import re

    pattern = re.escape(predicted)
    # {report-id} is a wildcard for the same reason as {run}: cityflower leaves
    # ai_content_report_ids empty, so the agent discovers the report from Power
    # BI at run time and the preview honestly cannot name it in advance.
    for token in ("\\{yyyy\\}", "\\{mm\\}", "\\{dd\\}", "\\{run\\}", "\\{report\\-id\\}"):
        pattern = pattern.replace(token, "[^/]+")
    return re.fullmatch(pattern, actual) is not None


def test_storage_plan() -> None:
    """The 'where does it go' preview must match where things actually go."""
    print("\nThe storage preview matches the live containers")
    from src.services import storage

    for client, observed in LIVE_LAYOUT.items():
        cfg = json.loads((PROJECT_ROOT / observed["config"]).read_text(encoding="utf-8"))
        result = storage.plan(cfg)
        by_container: dict[str, list[str]] = {}
        for dest in result["destinations"]:
            by_container.setdefault(dest["container"], []).extend(
                item["path"] for item in dest["paths"])

        for container, blobs in observed.items():
            if container == "config":
                continue
            predicted = by_container.get(container, [])
            unexplained = [
                blob for blob in blobs
                if not any(_matches(guess, blob) for guess in predicted)
            ]
            check(f"{client}: every real blob in '{container}' was predicted",
                  not unexplained, f"not predicted: {unexplained}")

    # The three destinations are distinct, and the app-facing one is not the
    # one the azure_blob_* settings control. Conflating them is the confusion
    # this panel exists to remove.
    cityflower = json.loads((PROJECT_ROOT / "config/config.json").read_text(encoding="utf-8"))
    plan = storage.plan(cityflower)
    containers = {d["id"]: d["container"] for d in plan["destinations"]}
    check("the agent's store and your app's store are different containers",
          containers["agent_store"] != containers["app_store"],
          f"{containers}")
    check("the app's container is the one ai_content_client names",
          containers["app_store"] == cityflower["ai_content_client"])
    check("memory is a third container again, never the app's",
          containers["memory"] not in {containers["app_store"]})
    check("every destination says who reads it",
          all(d["audience"] for d in plan["destinations"]))
    check("every destination names the settings that control it",
          all(d["settings"] for d in plan["destinations"]))
    check("every named setting is a real schema key",
          all(config_schema.get(k) for d in plan["destinations"] for k in d["settings"]))

    # An empty prefix is right for exactly one client and wrong for the rest.
    root = next(d for d in plan["destinations"] if d["id"] == "agent_store")
    check("writing to the top level is flagged", "no folder of its own" in root["warning"])
    scanb = json.loads((PROJECT_ROOT / "config/scanb/config.json").read_text(encoding="utf-8"))
    scanb_root = next(d for d in storage.plan(scanb)["destinations"] if d["id"] == "agent_store")
    check("a client with its own folder is not flagged", not scanb_root["warning"])

    clash = storage.plan(scanb, other_clients=[{"name": "someone-else", "config": {
        "dataset_id": "other", "azure_blob_container": "insightgen", "azure_blob_prefix": "scanb"}}])
    clash_root = next(d for d in clash["destinations"] if d["id"] == "agent_store")
    check("a client writing to the same place is named in the preview too",
          "someone-else" in clash_root["warning"])

    local = storage.plan({**scanb, "insight_memory_storage": "local",
                          "summary_memory_storage": "local"})
    local_memory = next(d for d in local["destinations"] if d["id"] == "memory")
    check("memory kept on the machine is flagged as forgetting nightly",
          "forget everything nightly" in local_memory["warning"])

    off = storage.plan({"azure_blob_upload": False, "ai_content_publish_enabled": False,
                        "insight_memory_storage": "local", "summary_memory_storage": "local"})
    check("nothing configured means nothing claimed to be written",
          all(not d["enabled"] for d in off["destinations"]))

    # An empty report list is not a mistake - it means "discover it" - and the
    # preview has to say so rather than showing a path nobody can look up.
    discovered = next(d for d in plan["destinations"] if d["id"] == "app_store")
    check("an empty report list is explained as discovery, not left as a mystery",
          "look them up in Power BI" in discovered["note"])
    check("and the path shows a placeholder rather than a wrong id",
          any("{report-id}" in item["path"] for item in discovered["paths"]))


def test_rulebook_checks() -> None:
    print("\nRulebooks are checked structurally - semantics cannot be automated")
    empty = validate.validate_rulebooks("", "")
    check("an empty rulebook warns", len(empty.warnings) >= 2)
    placeholder = validate.validate_rulebooks("# rules\nPASTE_YOUR_RULES" + "x" * 600, "y" * 300)
    check("a placeholder is caught",
          any("placeholder" in f.message for f in placeholder.findings))
    big = validate.validate_rulebooks("x" * 45_000, "y" * 3_500)
    check("a realistic pair passes with no warning", not big.warnings, str([f.message for f in big.warnings]))
    check("a rulebook too large for the usual upload path is noted, without alarming anyone",
          any("uploads it a different way" in f.message for f in big.findings))
    huge = validate.validate_rulebooks("x" * 200_000, "y" * 3_500)
    check("an oversized rulebook explains the cost in plain terms",
          any("less room for your actual data" in f.message for f in huge.findings))


def test_deploy_payload() -> None:
    print("\nAn ARM upsert never drops a secret it does not own")
    existing = [
        {"name": "agent-config-b64"},
        {"name": "azure-openai-api-key"},
        {"name": "vault-backed", "keyVaultUrl": "https://v.vault.azure.net/secrets/x", "identity": "system"},
    ]
    updates = deploy.secret_payload('{"a":1}', "# rules", "# summary")
    secrets, carried = deploy.merge_secrets(existing, updates)
    names = [s["name"] for s in secrets]
    check("unrelated secrets survive", "azure-openai-api-key" in names and "vault-backed" in names)
    check("a carried secret is sent by name only, so ARM keeps its stored value",
          all("value" not in s for s in secrets if s["name"] == "azure-openai-api-key"))
    check("a Key Vault reference is carried with its url and identity",
          next(s for s in secrets if s["name"] == "vault-backed")["keyVaultUrl"].endswith("/x"))
    check("our three secrets carry values", sum(1 for s in secrets if "value" in s) == 3)
    check("nothing is duplicated", len(names) == len(set(names)))
    check("carried names exclude the ones we replaced", "agent-config-b64" not in carried)

    check("empty existing secrets is fine", deploy.merge_secrets([], updates)[0][0]["name"] in updates)

    # A 45 KB rulebook is past the 32,767-character command-line limit, which is
    # why this path uses the request body rather than the az CLI.
    big = "x" * 45_000
    encoded = deploy.encode(big)
    check("a 45 KB rulebook base64s past the command-line limit", len(encoded) > 32_767)
    import base64
    check("the encoding is exactly what the container entry point decodes",
          base64.b64decode(encoded, validate=True).decode("utf-8") == big)

    spec = deploy.JobSpec(
        subscription_id="0300da4d-3a63-4241-a129-42b4f8b0c5cc",
        resource_group="Summary_generator_PBI",
        job_name="insightgen-zz-daily-job",
        environment_id="/subscriptions/s/resourceGroups/r/providers/Microsoft.App/managedEnvironments/e",
        location="eastus2",
        image="insightgenacr.azurecr.io/insightgen-agent:20260812-1200",
        identity_resource_id="/subscriptions/s/resourceGroups/r/providers/Microsoft.ManagedIdentity/"
                             "userAssignedIdentities/insightgen-mi",
        registry_server="insightgenacr.azurecr.io",
        env={"AGENT_OUTPUT_FOLDER": "outputs", "POWERBI_AUTH_MODE": "managed_identity"},
        secret_env={"AZURE_OPENAI_API_KEY": "azure-openai-api-key"},
    )
    body = deploy.build_job_body(spec, secrets)
    properties = body["properties"]
    check("the trigger is a schedule", properties["configuration"]["triggerType"] == "Schedule")
    check("the cron reaches the body",
          properties["configuration"]["scheduleTriggerConfig"]["cronExpression"] == "30 3 * * *")
    env_names = {e["name"] for e in properties["template"]["containers"][0]["env"]}
    check("plain and secret-backed env both land", {
        "AGENT_OUTPUT_FOLDER", "AZURE_OPENAI_API_KEY", "AGENT_CONFIG_B64",
        "AGENT_RULES_B64", "AGENT_SUMMARY_RULES_B64",
    } <= env_names)
    check("the three runtime files are always connected to their owned secrets",
          {
              "AGENT_CONFIG_B64": "agent-config-b64",
              "AGENT_RULES_B64": "agent-rules-b64",
              "AGENT_SUMMARY_RULES_B64": "agent-summary-rules-b64",
          }.items() <= {
              e["name"]: e.get("secretRef")
              for e in properties["template"]["containers"][0]["env"]
          }.items())
    check("the secret-backed var references the secret, not a value",
          all("value" not in e for e in properties["template"]["containers"][0]["env"]
              if e["name"] == "AZURE_OPENAI_API_KEY"))
    check("the user-assigned identity is attached", body["identity"]["type"] == "UserAssigned")
    check("the resource id is well formed",
          spec.resource_id.endswith("/providers/Microsoft.App/jobs/insightgen-zz-daily-job"))

    redacted = deploy.redact(body)
    check("redaction removes every secret value",
          all("redacted" in s["value"] for s in redacted["properties"]["configuration"]["secrets"]
              if "value" in s))
    check("redaction does not mutate the original",
          any("value" in s and "redacted" not in s["value"]
              for s in body["properties"]["configuration"]["secrets"] if "value" in s))

    bare = deploy.JobSpec(subscription_id="s", resource_group="r", job_name="j")
    check("a create with no environment id is refused, not half-sent",
          _raises(lambda: deploy.build_job_body(bare, [])))
    check("a create with no image is refused",
          _raises(lambda: deploy.build_job_body(
              deploy.JobSpec(subscription_id="s", resource_group="r", job_name="j",
                             environment_id="e", location="eastus2"), [])))

    result = deploy.deploy(spec, config_json="{}", business_rules="", summary_business_rules="",
                           allowed_job_names=["something-else"])
    check("a job name off the allow-list is refused before any call",
          result.status == "failed" and "allow-list" in result.reason)


def test_probe_findings() -> None:
    print("\nProbe findings become blocking errors and key recommendations")
    out = ProbeResult()
    out.universe = {"status": "ok"}
    out.model = {"entityResolved": False, "measureFamilies": [{"family": "revenue"}],
                 "dimensionCount": 14}
    out.entities = {"resolved": True, "comparable": ["S1", "S2"], "currentOnly": ["S9"], "priorOnly": []}
    out.freshness = {"freshness_status": "stale", "data_as_of": "2023-12-31", "today": "2026-08-12"}
    out.time_axes = [{"column": "UPDATED_DATE", "verdict": "batch_date", "selected": True}]
    out.roles = {
        "resolved": [
            {"role": "division", "focusEligible": True, "reconciled": True, "status": "ok",
             "coverageOnly": False, "poolCapped": False, "depth": 10},
            {"role": "department", "focusEligible": True, "reconciled": False, "status": "ok",
             "coverageOnly": False, "poolCapped": True, "depth": 20},
        ],
        "mirrored": {"section": ["division"]},
    }
    _derive_findings(out, {})
    check("an unreconciled level is a hard stop",
          out.status == "failed"
          and any("parts do not add up to the whole" in b for b in out.blocking))
    # mirrored_roles maps role -> the single role it copies, as a plain string.
    # Joining it as if it were a list printed "d, i, v, i, s, i, o, n" to a user.
    check("a mirrored level is surfaced, never silently omitted",
          any("exactly the same members and the same figures" in w for w in out.warnings))
    check("the level it copies is named as a word, not spelled out letter by letter",
          any("'division'" in w for w in out.warnings),
          str([w for w in out.warnings if "copy" in w]))
    check("and the reader is told nothing was lost",
          any("nothing is lost" in w for w in out.warnings))
    listed = ProbeResult()
    listed.universe = {"status": "ok"}
    listed.model = {"entityResolved": True, "measureFamilies": [{"family": "revenue"}],
                    "dimensionCount": 14}
    listed.entities, listed.freshness = {"resolved": True, "comparable": ["S1"]}, {"freshness_status": "current"}
    listed.roles = {"resolved": [{"role": "division", "focusEligible": True, "reconciled": True,
                                  "status": "ok", "coverageOnly": False, "poolCapped": False,
                                  "depth": 10}],
                    "mirrored": {"section": ["division", "department"]}}
    _derive_findings(listed, {})
    check("a list of mirrored levels still reads correctly",
          any("'division, department'" in w for w in listed.warnings),
          str(listed.warnings))
    check("a capped pool is surfaced",
          any("more members than the agent looked at" in w for w in out.warnings))
    check("a load date is called out, and why it cannot be used",
          any("record when data was loaded" in w and "meaningless" in w for w in out.warnings))
    check("stale data disables the daily levels",
          {r["key"] for r in out.recommendations} >= {"insight_recent_week_enabled", "insight_daily_enabled"})
    check("entity=unresolved recommends pinning the entity role",
          any(r["key"] == "summary_dashboard_entity_role" and r["value"] for r in out.recommendations))
    check("the comparable population is recommended from data",
          any(r["key"] == "insight_comparable_population" and r["value"] == ["S1", "S2"]
              for r in out.recommendations))
    check("a current-only entity is recommended for exclusion",
          any(r["key"] == "insight_excluded_entities" and r["value"] == ["S9"] for r in out.recommendations))
    check("only reconciled levels are recommended as focus roles",
          any(r["key"] == "summary_focus_allowed_roles" and r["value"] == ["division"]
              for r in out.recommendations))
    check("every recommendation names a real schema key",
          all(config_schema.get(r["key"]) for r in out.recommendations))

    clean = ProbeResult()
    clean.universe = {"status": "ok"}
    clean.model = {"entityResolved": True, "measureFamilies": [{"family": "revenue"}],
                   "dimensionCount": 14}
    clean.entities = {"resolved": True, "comparable": ["S1"], "currentOnly": [], "priorOnly": []}
    clean.freshness = {"freshness_status": "current"}
    clean.roles = {"resolved": [
        {"role": "division", "focusEligible": True, "reconciled": True, "status": "ok",
         "coverageOnly": False, "poolCapped": False, "depth": 10}], "mirrored": {}}
    _derive_findings(clean, {})
    check("a clean model probes ok", clean.status == "ok", f"{clean.status}: {clean.reason}")

    broken = ProbeResult()
    broken.universe = {"status": "failed", "reason": "nothing matched"}
    broken.roles = {"resolved": []}
    broken.model = {"entityResolved": True, "measureFamilies": [{"family": "revenue"}],
                    "dimensionCount": 14}
    broken.entities = {"resolved": False, "warnings": []}
    broken.freshness = {}
    _derive_findings(broken, {})
    check("a universe scan that did not complete blocks", broken.status == "failed")
    check("no usable product level blocks, and points at the fix",
          any("Rename your levels to standard ones" in b for b in broken.blocking))

    # The advice has to match the cause. A model with no this-year/last-year
    # measures cannot be reported on at all, and sending someone to the rename
    # box sends them to fix something that is not broken.
    no_measures = ProbeResult()
    no_measures.universe = {"status": "failed", "reason": "no metric family"}
    no_measures.model = {"entityResolved": False, "measureFamilies": [], "dimensionCount": 0}
    no_measures.entities = {"resolved": False, "warnings": []}
    no_measures.roles = {"resolved": [], "mirrored": {}}
    no_measures.freshness = {}
    _derive_findings(no_measures, {})
    check("a model with no year-on-year measures blocks", no_measures.status == "failed")
    check("and the blocker names the real requirement",
          any("compare one period with the same period a year earlier" in b
              for b in no_measures.blocking))
    check("it does not send you to the rename box, which cannot help",
          not any("Rename your levels" in b for b in no_measures.blocking),
          str(no_measures.blocking))
    check("and one root cause is reported once, not three times",
          len(no_measures.blocking) == 1, str(len(no_measures.blocking)))

    # Measures but nothing to group them by: also not a naming problem.
    no_dims = ProbeResult()
    no_dims.universe = {"status": "ok"}
    no_dims.model = {"entityResolved": True, "measureFamilies": [{"family": "revenue"}],
                     "dimensionCount": 0}
    no_dims.entities = {"resolved": True, "comparable": ["S1"]}
    no_dims.roles = {"resolved": [], "mirrored": {}}
    no_dims.freshness = {"freshness_status": "current"}
    _derive_findings(no_dims, {})
    check("measures with no groupable columns blocks with its own reason",
          any("nothing to rename" in b for b in no_dims.blocking), str(no_dims.blocking))

    # Measures AND columns, but none recognised: now renaming IS the fix.
    nameable = ProbeResult()
    nameable.universe = {"status": "ok"}
    nameable.model = {"entityResolved": True, "measureFamilies": [{"family": "revenue"}],
                      "dimensionCount": 12}
    nameable.entities = {"resolved": True, "comparable": ["S1"]}
    nameable.roles = {"resolved": [], "mirrored": {}}
    nameable.freshness = {"freshness_status": "current"}
    _derive_findings(nameable, {})
    check("unrecognised but present columns are pointed at the rename box",
          any("Rename your levels to standard ones" in b for b in nameable.blocking))


def test_probe_findings_reach_the_form() -> None:
    """One root cause must read as one problem, and lead."""
    print("\nA failed data check reads as one problem, at the top")

    # ProbeResult.reason is blocking[0]; reporting both printed it twice and
    # made a single fault look like two separate ones on screen.
    probe = {"status": "failed",
             "reason": "This dashboard has no measures that compare periods.",
             "blocking": ["This dashboard has no measures that compare periods."],
             "roles": {"resolved": []}, "model": {"entityResolved": True}, "entities": {}}
    report = validate.validate(_base_config(), target="container", probe=probe)
    probe_errors = [f for f in report.errors if f.key == "__probe__"]
    check("the same sentence is not reported twice", len(probe_errors) == 1,
          str([f.message for f in probe_errors]))
    check("the root cause is the first thing listed",
          report.errors[0].key == "__probe__", report.errors[0].key)
    check("and it tells you to re-run the check once fixed",
          "run the data check again" in probe_errors[0].fix)

    two = {"status": "failed", "reason": "first",
           "blocking": ["first", "second"], "roles": {"resolved": []},
           "model": {"entityResolved": True}, "entities": {}}
    both = [f for f in validate.validate(_base_config(), probe=two).errors
            if f.key == "__probe__"]
    check("two genuinely different blockers are both kept", len(both) == 2)
    check("only the last carries the re-run instruction",
          both[0].fix == "" and "run the data check again" in both[1].fix)

    failed_no_list = {"status": "failed", "reason": "something went wrong", "blocking": [],
                      "roles": {"resolved": []}, "model": {"entityResolved": True}, "entities": {}}
    fallback = [f for f in validate.validate(_base_config(), probe=failed_no_list).errors
                if f.key == "__probe__"]
    check("a failure with no blocker list still reports its reason",
          len(fallback) == 1 and "something went wrong" in fallback[0].message)


def test_job_runner() -> None:
    print("\nLong operations run as jobs, not as a request")
    runner = jobs.JobRunner()
    job = runner.submit("test", lambda log, j: ([log("one"), log("two")], "result")[1])
    for _ in range(80):
        if job.status in {"done", "failed"}:
            break
        time.sleep(0.02)
    check("a job completes and keeps its result", job.status == "done" and job.result == "result")
    check("log lines are captured in order", job.logs == ["one", "two"])
    check("the log offset returns only the tail", job.json(log_offset=1)["logs"] == ["two"])

    failing = runner.submit("test", lambda log, j: (_ for _ in ()).throw(RuntimeError("boom")))
    for _ in range(80):
        if failing.status in {"done", "failed"}:
            break
        time.sleep(0.02)
    check("a failing job reports rather than crashing the process",
          failing.status == "failed" and "boom" in failing.error)

    slow = runner.submit("test", lambda log, j: [time.sleep(0.02) for _ in range(20)] and None)
    check("a running job can be asked to cancel", runner.cancel(slow.id) is True)
    check("an unknown job id cannot be cancelled", runner.cancel("nope") is False)
    check("recent() filters by kind", all(j.kind == "test" for j in runner.recent(kind="test")))


def test_api() -> None:
    print("\nThe API answers, and deployment stays shut by default")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  [SKIP] fastapi.testclient unavailable")
        return
    from src.api.app import create_app

    client = TestClient(create_app(allow_deploy=False))

    schema = client.get("/api/schema").json()
    check("/api/schema returns the whole catalogue",
          len(schema["keys"]) == len(config_schema.KEYS) and schema["groups"])
    check("every key reaches the form with a plain label, help and tier",
          all(k.get("label") and k.get("help") and k.get("tier") for k in schema["keys"]))
    check("the form knows how many settings each step really needs",
          all("counts" in g for g in schema["groups"]))
    check("the schema carries the role vocabulary the pickers need",
          "division" in schema["vocabulary"]["hierarchyRoles"]
          and "store" in schema["vocabulary"]["coverageRoles"])

    listing = client.get("/api/clients").json()
    check("/api/clients lists what is on disk", isinstance(listing["clients"], list))
    check("a listed client does not carry its rulebook text",
          all("businessRules" not in c for c in listing["clients"]))

    defaults = client.get(f"/api/clients/{TEST_CLIENT}/defaults").json()
    check("defaults offer every key explicitly",
          set(defaults["config"]) == set(config_schema.defaults()))

    saved = client.put(f"/api/clients/{TEST_CLIENT}", json={
        "config": {**_base_config(), "summary_dashboard_tldr": "7"},
        "businessRules": "# rules\n" + "x" * 900,
        "summaryBusinessRules": "# summary\n" + "y" * 300,
    })
    check("PUT saves and coerces form strings",
          saved.status_code == 200
          and clients.load_client(TEST_CLIENT).config["summary_dashboard_tldr"] == 7)
    check("PUT reports the run command",
          saved.json()["runCommand"].endswith(f"config/{TEST_CLIENT}/config.json"))

    bad = client.put(f"/api/clients/{TEST_CLIENT}", json={"config": {"max_tokens": "lots"}})
    check("a value that cannot be coerced is rejected with a reason", bad.status_code == 400)

    got = client.get(f"/api/clients/{TEST_CLIENT}").json()
    check("GET returns config and both rulebooks",
          got["config"]["summary_r6_enabled"] is True and got["businessRules"].startswith("# rules"))

    validation = client.post("/api/validate", json={
        "name": TEST_CLIENT, "config": _base_config(output_folder="wrong"), "target": "container",
    }).json()
    check("/api/validate reports blocking errors", validation["ok"] is False and validation["errorCount"] > 0)
    check("every finding carries a plain title, not just a key name",
          all(f.get("title") for f in validation["findings"]))
    check("a finding about a setting names that setting in plain words",
          any(f["title"] == "Folder for generated reports" for f in validation["findings"]),
          str([f["title"] for f in validation["findings"]]))
    check("/api/validate reports the effective config after env overrides",
          "effective" in validation)

    probe_missing = client.post("/api/probe", json={"config": {"tenant_id": "t"}})
    check("a probe without the three identifiers is refused up front",
          probe_missing.status_code == 400)

    # Resolving a report id signs in, and signing in needs the tenant from the
    # form. Omitting it silently falls back to the POWERBI_TENANT_ID deployment
    # variable, which is normally unset locally - so the lookup reported "tenant
    # is not configured" while the ID sat filled in on screen.
    import src.tools.powerbi_executor as executor
    import requests as requests_module

    seen: dict = {}
    real_token, real_get = executor.get_powerbi_token, requests_module.get

    class _Response:
        status_code, ok = 200, True

        @staticmethod
        def json():
            return {"datasetId": "ds-123", "name": "Sales", "webUrl": "https://x"}

    executor.get_powerbi_token = lambda tenant_id=None: seen.setdefault("tenant", tenant_id) or "tok"
    requests_module.get = lambda url, **kw: (seen.update(url=url), _Response)[1]
    try:
        resolved = client.post("/api/resolve-dataset", json={
            "tenantId": "315642c5-e14a-4c12-bf77-41ee070def79",
            "workspaceId": "7111406b-1fff-4a8b-bd52-fa6131682262",
            "reportId": "dbc3406e-f73e-4b04-bdca-458c611cff55",
        })
        check("resolving a report id signs in with the tenant from the form, not the environment",
              seen.get("tenant") == "315642c5-e14a-4c12-bf77-41ee070def79", str(seen.get("tenant")))
        check("and returns the dataset id", resolved.json().get("datasetId") == "ds-123")
        check("the lookup asks Power BI for that report in that workspace",
              "7111406b-1fff-4a8b-bd52-fa6131682262/reports/dbc3406e" in seen.get("url", ""))

        no_tenant = client.post("/api/resolve-dataset", json={
            "workspaceId": "w", "reportId": "r"})
        check("a lookup with no tenant is refused with a plain reason, not an auth error",
              no_tenant.status_code == 400
              and "Organisation ID" in no_tenant.json()["detail"])
    finally:
        executor.get_powerbi_token, requests_module.get = real_token, real_get

    plan = client.post("/api/storage-plan", json={
        "name": TEST_CLIENT, "config": _base_config(azure_blob_prefix="zzreplay",
                                                    ai_content_client="zzreplay",
                                                    ai_content_publish_enabled=True)}).json()
    check("/api/storage-plan answers with all three destinations",
          [d["id"] for d in plan["destinations"]] == ["agent_store", "app_store", "memory"])
    check("and separates the agent's store from the app's",
          plan["destinations"][0]["container"] != plan["destinations"][1]["container"])

    check("an unknown job id is a 404", client.get("/api/jobs/deadbeef").status_code == 404)

    deploy_response = client.post("/api/deploy", json={"name": TEST_CLIENT, "job": {}})
    check("deployment is refused while it is disabled", deploy_response.status_code == 403)
    check("so is starting a job", client.post("/api/deploy/start", json={"job": {}}).status_code == 403)

    preview = client.post("/api/deploy/preview", json={
        "name": TEST_CLIENT,
        "job": {"subscriptionId": "s", "resourceGroup": "r", "jobName": "j",
                "environmentId": "e", "location": "eastus2", "image": "i"},
    })
    check("preview renders the ARM body with no network call and no allow-deploy",
          preview.status_code == 200)
    body = preview.json()
    check("preview redacts every secret value",
          all("redacted" in s.get("value", "") for s in
              body["body"]["properties"]["configuration"]["secrets"]))
    check("preview reports the encoded sizes", set(body["secretSizes"]) == set(deploy.OWNED_SECRETS))

    bundle = client.get(f"/api/clients/{TEST_CLIENT}/bundle")
    check("the bundle downloads as a zip",
          bundle.status_code == 200 and bundle.content[:2] == b"PK")

    check("deleting the test client cleans up",
          client.delete(f"/api/clients/{TEST_CLIENT}").json()["deleted"] is True)
    check("a traversing client name is a 400",
          client.get("/api/clients/..%2F..%2Fetc").status_code in {400, 404})

    check("the UI itself is served", client.get("/").status_code == 200)


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:  # noqa: BLE001 - the point is that it refuses
        return True
    return False


def cleanup() -> None:
    for name in (TEST_CLIENT, TEST_CLONE):
        path = clients.CONFIG_ROOT / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    print("=" * 72)
    print("REPLAY: client-onboarding services and API")
    print("=" * 72)
    try:
        test_round_trip()
        test_client_store()
        test_validation_guards()
        test_env_disagreement()
        test_role_and_population_checks()
        test_probe_findings_reach_the_form()
        test_storage_plan()
        test_plain_language()
        test_rulebook_checks()
        test_deploy_payload()
        test_probe_findings()
        test_job_runner()
        test_api()
    finally:
        cleanup()
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
