"""A tiny in-process job runner for the long operations.

A probe is 30-120 seconds and 10-20 REST calls; a full acceptance run is 4-5
minutes. Neither fits a request/response cycle honestly - the browser would
either time out or show a spinner with nothing behind it. So the API returns a
job id immediately and the UI polls for status and log lines.

Deliberately in-memory: this is the local-first tool, one user, one process.
The interface (submit / status / cancel / stream) is the part that matters, and
it is small enough to re-point at a real queue when the API is hosted.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | failed | cancelled
    created_at: str = field(default_factory=_now)
    started_at: str = ""
    finished_at: str = ""
    logs: list = field(default_factory=list)
    result: Any = None
    error: str = ""
    meta: dict = field(default_factory=dict)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def json(self, *, log_offset: int = 0) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "logs": self.logs[log_offset:],
            "logCount": len(self.logs),
            "result": self.result,
            "error": self.error,
            "meta": self.meta,
        }


class JobRunner:
    """Runs one callable per job on a daemon thread, capturing its log lines."""

    def __init__(self, *, keep: int = 40) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._keep = keep

    def submit(self, kind: str, fn: Callable[..., Any], *, meta: dict | None = None) -> Job:
        """``fn`` is called with ``(log, job)``; whatever it returns is the result."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, meta=meta or {})
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self._keep:
                stale = self._order.pop(0)
                if self._jobs.get(stale) and self._jobs[stale].status in {"done", "failed", "cancelled"}:
                    self._jobs.pop(stale, None)
                else:
                    self._order.insert(0, stale)
                    break

        def runner() -> None:
            job.status = "running"
            job.started_at = _now()
            try:
                job.result = fn(job.logs.append, job)
                job.status = "cancelled" if job.cancelled else "done"
            except Exception as exc:  # noqa: BLE001 - the job reports its own failure
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.logs.append(job.error)
                job.logs.extend(traceback.format_exc().splitlines()[-6:])
            finally:
                job.finished_at = _now()

        threading.Thread(target=runner, name=f"job-{kind}-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """Request cancellation. A job must check ``job.cancelled`` to honour it."""
        job = self._jobs.get(job_id)
        if not job or job.status in {"done", "failed", "cancelled"}:
            return False
        job._cancel.set()
        return True

    def recent(self, *, kind: str = "", limit: int = 20) -> list[Job]:
        with self._lock:
            ids = list(reversed(self._order))
        jobs = [self._jobs[i] for i in ids if i in self._jobs]
        if kind:
            jobs = [j for j in jobs if j.kind == kind]
        return jobs[:limit]


#: One runner per process. The API imports this rather than making its own.
RUNNER = JobRunner()
