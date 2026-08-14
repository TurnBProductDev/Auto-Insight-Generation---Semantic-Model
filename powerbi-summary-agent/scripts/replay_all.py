"""One gate over every offline replay. Non-zero exit if any of them fails.

    python scripts/replay_all.py                 # run them all
    python scripts/replay_all.py --list          # show what would run
    python scripts/replay_all.py -k coverage     # substring filter, for iterating
    python scripts/replay_all.py --with-golden   # also run the golden master

WP0 deliverable 2 of the domain-verticals programme. Every replay is offline:
no auth, no LLM, no network. As of writing, 22 scripts run in about 30 seconds,
so there is no excuse for not running this before a commit.

Discovery, not a hand-maintained list
-------------------------------------
Scripts are found by globbing ``scripts/replay_*.py``, so a new replay joins the
gate the moment it is written - nobody has to remember to register it. The
failure mode of discovery is the opposite one: a replay that gets deleted or
renamed silently shrinks the gate. ``MIN_EXPECTED`` guards that, so shrinking
the gate takes a deliberate, reviewable edit.

Sequential on purpose
---------------------
Several replays write into a shared ``outputs_replay/`` directory. Running them
concurrently would let one clobber another's artifacts and produce failures that
do not reproduce. The whole suite is fast enough that parallelism buys nothing.

Not included
------------
``smoke_*.py`` (they can reach for a live connection) and ``golden_master.py``
(a separate row in the brief's testing strategy - available here via
``--with-golden``, since both are meant to run on every commit).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Lowering this is a deliberate act: it means the gate now covers less than it
# did. Raise it when you add a replay; only lower it when one is genuinely and
# intentionally retired.
MIN_EXPECTED = 30

PER_SCRIPT_TIMEOUT = 600
TAIL_LINES = 25


def discover() -> list[Path]:
    """Every replay script except this one - the glob matches its own name."""
    this = Path(__file__).name
    return sorted(path for path in PROJECT_ROOT.glob("scripts/replay_*.py")
                  if path.name != this)


def _tail(text: str, limit: int = TAIL_LINES) -> list[str]:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[-limit:]


def run_one(script: Path) -> tuple[str, float, str, str]:
    """Returns (status, seconds, stdout, stderr). Status is PASS/FAIL/TIMEOUT/ERROR."""
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, f"scripts/{script.name}"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
            # Replay output carries currency and punctuation that is not cp1252
            # clean. Decoding must never be what fails the gate.
            encoding="utf-8", errors="replace",
            timeout=PER_SCRIPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", time.time() - start, "", f"exceeded {PER_SCRIPT_TIMEOUT}s"
    except OSError as exc:
        return "ERROR", time.time() - start, "", str(exc)
    status = "PASS" if result.returncode == 0 else "FAIL"
    return status, time.time() - start, result.stdout, result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="show what would run and exit")
    parser.add_argument("-k", "--filter", default=None,
                        help="only scripts whose name contains this substring")
    parser.add_argument("--with-golden", action="store_true",
                        help="also run scripts/golden_master.py")
    args = parser.parse_args()

    scripts = discover()
    if not scripts:
        print(f"[FAIL] no replay scripts found under {PROJECT_ROOT / 'scripts'}")
        return 1

    short = len(scripts) < MIN_EXPECTED
    if args.filter:
        scripts = [s for s in scripts if args.filter in s.name]
        if not scripts:
            print(f"[FAIL] no replay script matches {args.filter!r}")
            return 1

    if args.list:
        for script in scripts:
            print(f"  {script.name}")
        print(f"\n{len(scripts)} script(s)")
        return 0

    print(f"Running {len(scripts)} offline replay(s)\n")
    results: list[tuple[str, str, float, str, str]] = []
    for index, script in enumerate(scripts, start=1):
        print(f"  [{index:2d}/{len(scripts)}] {script.name:44s} ", end="", flush=True)
        status, elapsed, out, err = run_one(script)
        print(f"{status:7s} {elapsed:6.1f}s")
        results.append((script.name, status, elapsed, out, err))

    if args.with_golden:
        print(f"\n  {'[golden]':>9s} {'golden_master.py':44s} ", end="", flush=True)
        status, elapsed, out, err = run_one(PROJECT_ROOT / "scripts" / "golden_master.py")
        print(f"{status:7s} {elapsed:6.1f}s")
        results.append(("golden_master.py", status, elapsed, out, err))

    failed = [row for row in results if row[1] != "PASS"]

    for name, status, _elapsed, out, err in failed:
        print("\n" + "-" * 72)
        print(f"{status}: {name}")
        print("-" * 72)
        for line in _tail(out):
            print(f"  {line}")
        for line in _tail(err, 10):
            print(f"  [stderr] {line}")

    total = sum(row[2] for row in results)
    print("\n" + "=" * 72)
    print(f"{len(results) - len(failed)}/{len(results)} passed in {total:.1f}s")

    if short and not args.filter:
        # Reported alongside the result, never instead of it.
        print(f"\n[FAIL] discovered {len(discover())} replay script(s), expected at "
              f"least {MIN_EXPECTED}.")
        print("       A replay was deleted or renamed, which shrinks this gate.")
        print("       If that was deliberate, lower MIN_EXPECTED in this script.")

    if failed or (short and not args.filter):
        print("\nREPLAY GATE FAILED")
        return 1

    print("REPLAY GATE GREEN - every offline replay passed")
    if not args.with_golden:
        print("\nReminder: the other half of the commit gate is")
        print("  python scripts/golden_master.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


