"""File I/O helpers scoped to the project's output folder."""

import json
from pathlib import Path
from typing import Any

# .../powerbi-summary-agent/src/tools/file_io.py  -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def output_dir(state: dict) -> Path:
    folder = state.get("output_folder", "outputs")
    d = PROJECT_ROOT / folder
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_path(state: dict, name: str) -> Path:
    return output_dir(state) / name


def write_json(state: dict, name: str, obj: Any) -> Path:
    path = output_path(state, name)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def write_text(state: dict, name: str, text: str) -> Path:
    path = output_path(state, name)
    path.write_text(text, encoding="utf-8")
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def read_business_rules(config_path=None) -> str:
    """Read the company business-rules file that sits beside config.json.

    `config_path` is the active config file (so a custom `--config` picks up its
    own sibling `business_rules.md`); when absent, falls back to the default
    `config/business_rules.md` under the project root. Best-effort: a missing
    file returns an empty string (the feature is additive and must never break
    a run). Never raises for a missing file.
    """
    if config_path:
        rules_path = Path(config_path).parent / "business_rules.md"
    else:
        rules_path = PROJECT_ROOT / "config" / "business_rules.md"
    if not rules_path.exists():
        return ""
    return rules_path.read_text(encoding="utf-8")


def business_rules_block(state: dict) -> str:
    """Formatted, injectable system-prompt section for the company business rules.

    Returns "" when no rules are loaded so callers can concatenate it
    unconditionally. Placed after `_global_rules.md` (permanent guardrails)
    and before each node's task prompt. The block states its own precedence
    ceiling: business rules beat generic analytical defaults but never the
    global rules above, the model schema, safety, or branch scope - so a
    company rule can't be used to countermand a guardrail.
    """
    rules = (state.get("business_rules") or "").strip()
    if not rules:
        return ""
    return (
        "\n\n# COMPANY BUSINESS RULES (authoritative)\n"
        "The following calculation and reporting rules are defined by the business. "
        "They OVERRIDE generic defaults and assumptions. Follow them exactly; when a "
        "rule constrains how a metric is computed, filtered, ranked, or reported, "
        "comply even if it means excluding rows or splitting a figure out.\n"
        "Business rules override generic analytical defaults, but never the global "
        "rules above, the model schema (only reference tables/columns/measures that "
        "actually exist), safety, or branch scope. If a business rule conflicts with "
        "any of those, ignore the conflicting part of the rule and follow the "
        "guardrail.\n\n"
        + rules
    )
