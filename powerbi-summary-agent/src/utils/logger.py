"""Tiny run-scoped logger that also accumulates into LangGraph state.

`logs`/`errors` are reducer-backed channels (operator.add in state.py), so
each node must return ONLY its own new lines — LangGraph concatenates them.
Seeding from the prior state here would double-count every earlier entry on
every node call.
"""

import datetime
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
_logger = logging.getLogger("pbi-summary-agent")


def _stamp(msg: str) -> str:
    return f"[{datetime.datetime.now():%H:%M:%S}] {msg}"


class RunLogger:
    """Collects log/error lines for one node and returns them as state updates."""

    def __init__(self, state: dict):
        self.logs = []
        self.errors = []

    def info(self, msg: str) -> None:
        line = _stamp(msg)
        _logger.info(line)
        self.logs.append(line)

    def error(self, msg: str) -> None:
        line = _stamp("ERROR: " + msg)
        _logger.error(line)
        self.logs.append(line)
        self.errors.append(msg)

    def updates(self) -> dict:
        return {"logs": self.logs, "errors": self.errors}
