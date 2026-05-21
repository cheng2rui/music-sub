"""Background inbound message queue.

Messaging providers should acknowledge inbound updates quickly.  The actual
Assistant run can be slow because it may call tools/LLMs, so process one queue
per conversation key in daemon workers.  This keeps each chat session
worker model without pulling in a full async graph runtime.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import app.config as cfg_module
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


def _worker_idle_timeout() -> float:
    try:
        value = float(getattr(cfg_module.config.assistant, "incoming_queue_idle_timeout_seconds", 300) or 300)
    except Exception:
        value = 300.0
    return max(30.0, min(value, 3600.0))


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
                item = q.get(timeout=_worker_idle_timeout())
            except queue.Empty:
                break
            wait_ms = int((time.time() - item.queued_at) * 1000)
            db = SessionLocal()
            started_at = time.time()
            try:
                with _lock:
                    _status.setdefault(key, {}).update({
                        "running": True,
                        "processing": True,
                        "queued": q.qsize(),
                        "last_started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "last_wait_ms": wait_ms,
                    })
                result = handle_incoming_message(db, item.incoming)
                duration_ms = int((time.time() - started_at) * 1000)
                with _lock:
                    _status.setdefault(key, {}).update({
                        "processing": False,
                        "queued": q.qsize(),
                        "last_finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "last_duration_ms": duration_ms,
                        "last_result_ok": bool((result or {}).get("ok", True)),
                        "last_ignored": bool((result or {}).get("ignored")),
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
            status = _status.setdefault(key, {})
            status.update({"running": False, "processing": False, "queued": 0, "last_stopped_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
            # Keep only recent idle statuses so the status API stays useful without
            # accumulating stale identities forever.
            idle_keys = [k for k, v in _status.items() if not v.get("running") and not v.get("processing")]
            for stale_key in idle_keys[:-20]:
                _status.pop(stale_key, None)
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
