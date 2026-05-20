"""Background inbound message queue.

Messaging providers should acknowledge inbound updates quickly.  The actual
Assistant run can be slow because it may call tools/LLMs, so process one queue
per conversation key in daemon workers.  This mirrors MoviePilot's per-session
worker model without pulling in a full async graph runtime.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.db import SessionLocal
from app.services.notify import IncomingMessage, handle_incoming_message, log_notify_event

logger = logging.getLogger(__name__)


@dataclass
class _QueuedIncoming:
    incoming: IncomingMessage
    queued_at: float


_lock = threading.RLock()
_queues: dict[str, queue.Queue[_QueuedIncoming]] = {}
_workers: dict[str, threading.Thread] = {}
_status: dict[str, dict[str, Any]] = {}
_worker_idle_timeout = 60.0


def _queue_key(incoming: IncomingMessage) -> str:
    channel = (incoming.channel or "unknown").lower()
    identity = incoming.user_id or incoming.target or incoming.chat_id or "anonymous"
    return f"{channel}:{identity}"


def enqueue_incoming_message(incoming: IncomingMessage) -> dict[str, Any]:
    """Queue an inbound message and return immediately."""
    key = _queue_key(incoming)
    with _lock:
        q = _queues.get(key)
        if q is None:
            q = queue.Queue()
            _queues[key] = q
        q.put(_QueuedIncoming(incoming=incoming, queued_at=time.time()))
        status = _status.setdefault(key, {})
        status.update({
            "key": key,
            "queued": q.qsize(),
            "last_enqueued_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "last_error": "",
        })
        worker = _workers.get(key)
        if not worker or not worker.is_alive():
            worker = threading.Thread(target=_worker_loop, args=(key,), name=f"incoming-{key}", daemon=True)
            _workers[key] = worker
            worker.start()
        return {"ok": True, "queued": True, "key": key, "queue_size": q.qsize()}


def _worker_loop(key: str) -> None:
    logger.info("Inbound queue worker started: %s", key)
    with _lock:
        _status.setdefault(key, {}).update({"running": True})
    try:
        while True:
            q = _queues.get(key)
            if q is None:
                break
            try:
                item = q.get(timeout=_worker_idle_timeout)
            except queue.Empty:
                break
            wait_ms = int((time.time() - item.queued_at) * 1000)
            db = SessionLocal()
            try:
                with _lock:
                    _status.setdefault(key, {}).update({
                        "running": True,
                        "processing": True,
                        "queued": q.qsize(),
                        "last_started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "last_wait_ms": wait_ms,
                    })
                handle_incoming_message(db, item.incoming)
                with _lock:
                    _status.setdefault(key, {}).update({
                        "processing": False,
                        "queued": q.qsize(),
                        "last_finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "last_error": "",
                    })
            except Exception as exc:
                logger.exception("Inbound queue worker failed: %s", key)
                with _lock:
                    _status.setdefault(key, {}).update({
                        "processing": False,
                        "queued": q.qsize(),
                        "last_error": str(exc)[:300],
                    })
                try:
                    log_notify_event(
                        channel=item.incoming.channel or "unknown",
                        direction="inbound",
                        status="error",
                        message=f"queued inbound failed: {str(exc)[:200]}",
                        raw={"incoming": item.incoming.meta(), "raw": item.incoming.raw},
                        db=db,
                    )
                except Exception:
                    pass
            finally:
                db.close()
                q.task_done()
    finally:
        with _lock:
            q = _queues.get(key)
            if q is not None and q.empty():
                _queues.pop(key, None)
            _workers.pop(key, None)
            _status.setdefault(key, {}).update({"running": False, "processing": False, "queued": 0})
        logger.info("Inbound queue worker stopped: %s", key)


def incoming_queue_status() -> dict[str, Any]:
    with _lock:
        items = []
        for key, status in _status.items():
            q = _queues.get(key)
            item = dict(status)
            item["queued"] = q.qsize() if q else int(item.get("queued") or 0)
            item["thread_alive"] = bool(_workers.get(key) and _workers[key].is_alive())
            items.append(item)
        return {"items": items, "active": sum(1 for i in items if i.get("thread_alive"))}
