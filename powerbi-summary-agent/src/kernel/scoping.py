"""The single authority for every path that used to be keyed on the dataset alone.

The bug this closes: ``summary_memory`` and ``insight_memory`` both filed their
store under ``<root>/<dataset_id>/memory.json``. Two reports over one semantic
model therefore shared one rotation history and one reported-findings set - each
would suppress the other's findings and overwrite the other's daily plan, with
nothing to detect it.

The layout, after WP1::

    <root>/<dataset>/reports/<report_id>/memory.json    summary  (per report)
    <root>/<dataset>/chains/<chain_id>/memory.json      insight  (per chain)
    <root>/<dataset>/memory.json                        legacy, migrated from

Summary memory is per **report** because a descriptive summary rotates through
one report's own focus areas. Insight memory is per **chain** because WP8 pools
evidence across a chain's reports and runs the investigative branch once over
all of it - one memory, one consumer.

The dataset segment is passed in already sanitised
--------------------------------------------------
Deliberate. The two memory modules historically sanitised the dataset id with
slightly different rules (``str.isalnum`` admits non-ASCII letters, the regex
does not). Re-sanitising here would relocate an existing store for any id where
the two disagree, orphaning real memory. So each caller keeps its own
dataset-segment rule, and this module only owns the segments it introduced.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")

REPORTS_DIR = "reports"
CHAINS_DIR = "chains"
STORE_FILENAME = "memory.json"


def safe_segment(value: object, fallback: str = "unknown") -> str:
    """One path segment, safe on every filesystem and never empty.

    Applied only to the report/chain identifiers this module introduced, never
    to the dataset segment - see the module docstring.
    """
    text = _UNSAFE.sub("_", str(value or "").strip())
    return text or fallback


def legacy_dir(root: Path, dataset_segment: str) -> Path:
    """Where a pre-WP1 store lives: dataset-scoped, nothing more."""
    return Path(root) / dataset_segment


def report_dir(root: Path, dataset_segment: str, report_id: object) -> Path:
    """A report belongs to exactly one dataset, so its store nests under it."""
    return (Path(root) / dataset_segment / REPORTS_DIR
            / safe_segment(report_id, "unknown_report"))


def chain_dir(root: Path, chain_id: object) -> Path:
    """A chain's store is NOT nested under a dataset (WP8).

    The dataset is a property of a *report*, not of a chain. WP0 found the two
    inventory reports live in different semantic models
    (`64eefa4b…` and `84212fd9…`), so nesting chain memory under a dataset gave
    the `inventory` chain two separate stores:

        64eefa4b…/chains/inventory/memory.json
        84212fd9…/chains/inventory/memory.json

    which is precisely the sharing WP8 exists to provide. Chain memory therefore
    lives at ``<root>/chains/<chain_id>/memory.json``, one store per chain
    however many models it spans. Story identities stay distinct per model
    regardless, because `insight_memory.story_key` includes the dataset.
    """
    return Path(root) / CHAINS_DIR / safe_segment(chain_id, "unknown_chain")


def migrate_store(legacy_path: Path, scoped_path: Path) -> str:
    """Bring a pre-WP1 store into its scoped home. Non-destructive, idempotent.

    Returns one of:

    ``already_scoped``  the scoped store exists; nothing to do (the steady state)
    ``migrated``        the legacy store was **copied** into the scoped path
    ``no_legacy``       nothing to migrate - a genuinely new store
    ``failed``          the copy did not succeed; the caller starts empty rather
                        than pretending a store was carried over

    It **copies** rather than moves. "Non-destructive" has to mean the old file
    survives: a rollback to pre-WP1 code must still find its memory, and losing
    a reported-findings set would re-announce every finding a user already read.
    The copy runs once - on every later run the scoped store already exists and
    this returns ``already_scoped`` after a single stat call.
    """
    legacy_path, scoped_path = Path(legacy_path), Path(scoped_path)
    if scoped_path.exists():
        return "already_scoped"
    if not legacy_path.exists():
        return "no_legacy"
    try:
        scoped_path.parent.mkdir(parents=True, exist_ok=True)
        # copy2 preserves mtime, so freshness heuristics reading the file's age
        # do not see a store that just appeared.
        shutil.copy2(legacy_path, scoped_path)
        return "migrated"
    except OSError:
        return "failed"


def scoped_store(root: Path, dataset_segment: str, *, report_id: object = None,
                 chain_id: object = None) -> tuple[Path, str]:
    """Resolve a store path, migrating an older store into it on first use.

    Exactly one of ``report_id`` / ``chain_id`` must be given - a store is
    scoped to a report or to a chain, never both.

    A chain store migrates from **two** possible older homes, newest layout
    first: the WP1 dataset-nested chain path, then the pre-WP1 dataset root.
    Both are copies, so an older code version still finds its memory.
    """
    if (report_id is None) == (chain_id is None):
        raise ValueError("pass exactly one of report_id or chain_id")

    if report_id is not None:
        directory = report_dir(root, dataset_segment, report_id)
        scoped_path = directory / STORE_FILENAME
        status = migrate_store(
            legacy_dir(root, dataset_segment) / STORE_FILENAME, scoped_path)
    else:
        directory = chain_dir(root, chain_id)
        scoped_path = directory / STORE_FILENAME
        # The WP1 location, which this dataset would have written last run.
        status = migrate_store(
            Path(root) / dataset_segment / CHAINS_DIR
            / safe_segment(chain_id, "unknown_chain") / STORE_FILENAME,
            scoped_path)
        if status == "no_legacy":
            status = migrate_store(
                legacy_dir(root, dataset_segment) / STORE_FILENAME, scoped_path)

    directory.mkdir(parents=True, exist_ok=True)
    return scoped_path, status
