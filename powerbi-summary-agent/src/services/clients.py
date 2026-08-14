"""Reading and writing a client record: ``config/<client>/`` and its rulebooks.

A client is a directory, because that is what the pipeline already understands:

    config/<client>/
        config.json                 the ~200 keys
        business_rules.md           injected into every insight/DAX prompt
        summary_business_rules.md   injected into the summary generator only

``file_io.read_business_rules`` resolves both rulebooks as *siblings of the
active config file*, so ``python -m src.main --config config/<client>/config.json``
picks all three up with no code change. They must stay per-client documents: one
shared file would leak one client's scope policy into another's DAX generation.

Writing preserves the existing file's key order and line endings, so re-saving a
client that was authored by hand produces a byte-identical file and the diff
shows only what actually changed. A new client is written in wizard order.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import config_schema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "config"

CONFIG_NAME = "config.json"
RULES_NAME = "business_rules.md"
SUMMARY_RULES_NAME = "summary_business_rules.md"

#: Directories under config/ that are not clients.
_RESERVED = {"__pycache__"}

_CLIENT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,38}[a-z0-9]$")


class ClientError(ValueError):
    """A client name or record that cannot be used."""


@dataclass
class ClientRecord:
    name: str
    path: str
    config: dict = field(default_factory=dict)
    business_rules: str = ""
    summary_business_rules: str = ""
    #: Key order and newline style of the file on disk, so a save round-trips.
    key_order: list = field(default_factory=list)
    newline: str = "\n"
    exists: bool = False
    modified: str = ""

    def json(self, *, include_rules: bool = True) -> dict:
        out = {
            "name": self.name,
            "path": self.path,
            "config": self.config,
            "exists": self.exists,
            "modified": self.modified,
            "hasBusinessRules": bool(self.business_rules.strip()),
            "hasSummaryRules": bool(self.summary_business_rules.strip()),
            "businessRulesBytes": len(self.business_rules.encode("utf-8")),
            "summaryRulesBytes": len(self.summary_business_rules.encode("utf-8")),
        }
        if include_rules:
            out["businessRules"] = self.business_rules
            out["summaryBusinessRules"] = self.summary_business_rules
        return out


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def dumps_config(config: dict, *, key_order: list | None = None, newline: str = "\n") -> str:
    """Render a config exactly the way the committed ones are written.

    ``json.dumps(indent=2)`` plus a trailing newline, keys in ``key_order``
    first (so an edited file keeps its shape) and anything new appended in
    wizard order.
    """
    ordered: dict = {}
    for key in key_order or []:
        if key in config:
            ordered[key] = config[key]
    for key in config_schema.schema_order([k for k in config if k not in ordered]):
        ordered[key] = config[key]
    text = json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"
    if newline != "\n":
        text = text.replace("\n", newline)
    return text


def detect_newline(raw: bytes) -> str:
    return "\r\n" if b"\r\n" in raw else "\n"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def client_dir(name: str) -> Path:
    """Resolve ``config/<name>/``, refusing anything that escapes config/."""
    safe = str(name or "").strip()
    if not _CLIENT_NAME.match(safe):
        raise ClientError(
            f"{name!r} is not a valid client name: lowercase letters, digits, hyphen and "
            "underscore, 2-40 characters."
        )
    path = (CONFIG_ROOT / safe).resolve()
    if path.parent != CONFIG_ROOT.resolve():
        raise ClientError(f"{name!r} does not resolve inside config/.")
    return path


def list_clients() -> list[ClientRecord]:
    """Every ``config/<client>/config.json`` on disk, newest edit first."""
    records: list[ClientRecord] = []
    if not CONFIG_ROOT.exists():
        return records
    for entry in sorted(CONFIG_ROOT.iterdir()):
        if not entry.is_dir() or entry.name in _RESERVED:
            continue
        if not (entry / CONFIG_NAME).exists():
            continue
        try:
            records.append(load_client(entry.name))
        except (ClientError, json.JSONDecodeError):
            continue
    return records


def load_client(name: str) -> ClientRecord:
    directory = client_dir(name)
    config_path = directory / CONFIG_NAME
    record = ClientRecord(name=name, path=str(directory))
    if not config_path.exists():
        return record

    raw = config_path.read_bytes()
    text = raw.decode("utf-8-sig")
    config = json.loads(text)
    if not isinstance(config, dict):
        raise ClientError(f"{config_path} is not a JSON object.")

    record.config = config
    record.key_order = list(config)
    record.newline = detect_newline(raw)
    record.exists = True
    record.modified = datetime.fromtimestamp(
        config_path.stat().st_mtime, tz=timezone.utc
    ).isoformat(timespec="seconds")
    for attr, filename in (
        ("business_rules", RULES_NAME),
        ("summary_business_rules", SUMMARY_RULES_NAME),
    ):
        path = directory / filename
        if path.exists():
            setattr(record, attr, path.read_text(encoding="utf-8"))
    return record


def load_config_file(path: Path | str) -> ClientRecord:
    """Load an arbitrary config path (the root config/config.json, say)."""
    config_path = Path(path)
    raw = config_path.read_bytes()
    config = json.loads(raw.decode("utf-8-sig"))
    directory = config_path.parent
    record = ClientRecord(
        name=directory.name,
        path=str(directory),
        config=config,
        key_order=list(config),
        newline=detect_newline(raw),
        exists=True,
    )
    for attr, filename in (
        ("business_rules", RULES_NAME),
        ("summary_business_rules", SUMMARY_RULES_NAME),
    ):
        sibling = directory / filename
        if sibling.exists():
            setattr(record, attr, sibling.read_text(encoding="utf-8"))
    return record


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def save_client(
    name: str,
    config: dict,
    *,
    business_rules: str | None = None,
    summary_business_rules: str | None = None,
    preserve_order: bool = True,
) -> ClientRecord:
    """Write ``config/<name>/`` and return the record as it now stands on disk.

    A rulebook passed as ``None`` is left alone, so saving config edits cannot
    silently blank a 45 KB document.
    """
    directory = client_dir(name)
    existing = load_client(name) if (directory / CONFIG_NAME).exists() else None
    directory.mkdir(parents=True, exist_ok=True)

    key_order = existing.key_order if (existing and preserve_order) else []
    newline = existing.newline if existing else "\n"
    (directory / CONFIG_NAME).write_bytes(
        dumps_config(config, key_order=key_order, newline=newline).encode("utf-8")
    )

    for text, filename in (
        (business_rules, RULES_NAME),
        (summary_business_rules, SUMMARY_RULES_NAME),
    ):
        if text is None:
            continue
        (directory / filename).write_text(text, encoding="utf-8", newline="")

    return load_client(name)


def delete_client(name: str) -> bool:
    """Remove a client directory. ``client_dir`` refuses anything outside config/."""
    import shutil

    directory = client_dir(name)
    if not directory.exists():
        return False
    shutil.rmtree(directory)
    return True


def clone_client(source: str, target: str, *, overrides: dict | None = None) -> ClientRecord:
    """Start a new client from an existing one.

    The per-client keys are cleared rather than copied: carrying over
    ``azure_blob_prefix`` or ``ai_content_client`` is exactly the mistake that
    makes one client overwrite another's payloads.
    """
    record = load_client(source)
    if not record.exists:
        raise ClientError(f"No client named {source!r}.")
    config = dict(record.config)
    for entry in config_schema.per_client_keys():
        if entry.key in {"output_folder"}:
            config[entry.key] = "outputs"
        elif entry.key in config:
            config[entry.key] = entry.default
    config.update(overrides or {})
    return save_client(
        target,
        config,
        business_rules=record.business_rules,
        summary_business_rules=record.summary_business_rules,
        preserve_order=False,
    )


def bundle(name: str) -> bytes:
    """The three files as a zip, for a deployment that happens elsewhere."""
    record = load_client(name)
    if not record.exists:
        raise ClientError(f"No client named {name!r}.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{name}/{CONFIG_NAME}",
            dumps_config(record.config, key_order=record.key_order, newline=record.newline),
        )
        archive.writestr(f"{name}/{RULES_NAME}", record.business_rules)
        archive.writestr(f"{name}/{SUMMARY_RULES_NAME}", record.summary_business_rules)
        archive.writestr(
            f"{name}/README.txt",
            "Run this client with:\n\n"
            f"    python -m src.main --config config/{name}/config.json\n\n"
            "Both rulebooks must stay as siblings of config.json - file_io resolves them\n"
            "relative to the active config file.\n",
        )
    return buffer.getvalue()


def template_rulebooks() -> dict:
    """Starting points for a new client's two rulebooks."""
    out = {"business_rules": "", "summary_business_rules": ""}
    example = CONFIG_ROOT / "business_rules.example.md"
    if example.exists():
        out["business_rules"] = example.read_text(encoding="utf-8")
    shared_summary = CONFIG_ROOT / SUMMARY_RULES_NAME
    if shared_summary.exists():
        out["summary_business_rules"] = shared_summary.read_text(encoding="utf-8")
    return out


def new_config(**overrides) -> dict:
    """A fresh config: every key at its code default, then the overrides.

    Writing all of them explicitly is deliberate. A key left out does not error
    - it silently changes behaviour, which is how R4 and R6 stayed off in
    production while the code implementing them shipped.
    """
    config = config_schema.defaults()
    config.update(overrides)
    return config
