"""Background scrape job runner.

In-process job queue for batch rescrape so HTTP requests don't block on long
scrape chains. One worker thread processes jobs sequentially; clients poll
`GET /api/library/jobs/{job_id}` for progress.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue, Empty
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobStep:
    label: str
    status: str = "pending"  # pending | running | ok | failed | skipped
    message: str = ""
    finished_at: Optional[str] = None


@dataclass
class ScrapeJob:
    id: str
    kind: str  # "rescrape_albums" | "rescrape_files" | "rescan_metadata"
    total: int
    steps: list[JobStep] = field(default_factory=list)
    status: str = "queued"  # queued | running | done | failed | cancelled
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    progress: int = 0  # completed steps
    summary: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "total": self.total,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "error": self.error,
            "steps": [
                {"label": s.label, "status": s.status, "message": s.message, "finished_at": s.finished_at}
                for s in self.steps
            ],
        }


class ScrapeJobRunner:
    def __init__(self, max_history: int = 50):
        self._jobs: dict[str, ScrapeJob] = {}
        self._queue: "Queue[tuple[ScrapeJob, Callable[[ScrapeJob], None]]]" = Queue()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._max_history = max_history

    def _ensure_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._loop, name="scrape-job-worker", daemon=True)
        self._worker.start()

    def submit(self, kind: str, total: int, runner: Callable[[ScrapeJob], None],
               step_labels: Optional[list[str]] = None) -> ScrapeJob:
        job = ScrapeJob(id=uuid.uuid4().hex[:12], kind=kind, total=total)
        if step_labels:
            job.steps = [JobStep(label=lbl) for lbl in step_labels]
        with self._lock:
            self._jobs[job.id] = job
            self._evict_old()
        self._queue.put((job, runner))
        self._ensure_worker()
        return job

    def get(self, job_id: str) -> Optional[ScrapeJob]:
        return self._jobs.get(job_id)

    def list(self, limit: int = 20) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def _evict_old(self):
        if len(self._jobs) <= self._max_history:
            return
        keep = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[: self._max_history]
        keep_ids = {j.id for j in keep}
        self._jobs = {k: v for k, v in self._jobs.items() if k in keep_ids}

    def _loop(self):
        while True:
            try:
                job, runner = self._queue.get(timeout=60)
            except Empty:
                return
            job.status = "running"
            job.started_at = datetime.utcnow().isoformat()
            try:
                runner(job)
                if job.status not in {"failed", "cancelled"}:
                    job.status = "done"
            except Exception as e:
                logger.exception(f"[scrape-job {job.id}] failed: {e}")
                job.status = "failed"
                job.error = str(e)[:500]
            finally:
                job.finished_at = datetime.utcnow().isoformat()
                self._queue.task_done()


runner = ScrapeJobRunner()


def mark_step(step: JobStep, status: str, message: str = ""):
    step.status = status
    step.message = message
    step.finished_at = datetime.utcnow().isoformat()
