"""APScheduler setup."""
import json
import logging
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
import app.config as cfg_module

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

JOB_HISTORY_PATH = Path("data/job_history.json")


def _load_job_history() -> dict[str, dict]:
    try:
        if JOB_HISTORY_PATH.exists():
            return json.loads(JOB_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load job history: {e}")
    return {}


# Track last run results
_job_history: dict[str, dict] = _load_job_history()


def _save_job_history():
    try:
        JOB_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        JOB_HISTORY_PATH.write_text(json.dumps(_job_history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save job history: {e}")


def _record_run(job_id: str, success: bool, message: str = ""):
    """Record a job run result."""
    _job_history[job_id] = {
        "last_run": datetime.now().isoformat(),
        "success": success,
        "message": message,
    }
    _save_job_history()


def _search_subscriptions():
    """Periodic task: search PT sites for subscriptions."""
    from app.services.searcher import search_all_subscriptions
    try:
        search_all_subscriptions()
        _record_run("search_subscriptions", True, "搜索完成")
    except Exception as e:
        logger.error(f"Subscription search failed: {e}")
        _record_run("search_subscriptions", False, str(e)[:200])


def _check_downloads():
    """Periodic task: check QB for completed downloads."""
    from app.services.pipeline import check_completed_downloads
    try:
        check_completed_downloads()
        _record_run("check_downloads", True, "检查完成")
    except Exception as e:
        logger.error(f"Download check failed: {e}")
        _record_run("check_downloads", False, str(e)[:200])


def _assistant_wake():
    """Periodic Assistant wake-up: run a lightweight health/status check."""
    from app.db import SessionLocal
    from app.services.assistant.tools import execute_tool
    from app.services.notify import send_all

    db = SessionLocal()
    try:
        status = execute_tool(db, "get_system_status", {})
        health = execute_tool(db, "query_library_health", {"kind": "", "limit": 3})
        totals = health.get("totals") or {}
        issues = sum(int(v or 0) for v in totals.values()) if totals else 0
        msg = f"助手定时唤醒完成：曲库 {status.get('library_files', 0)} 首，任务 {status.get('tasks', 0)} 个，治理问题 {issues} 项。"
        logger.info(msg)
        # Only notify when there is something useful to say.
        if issues:
            send_all("on_error", f"🤖 <b>助手定时巡检</b>\n{msg}\n请到音乐库治理查看详情。")
        _record_run("assistant_wake", True, msg)
    except Exception as e:
        logger.error(f"Assistant wake failed: {e}")
        _record_run("assistant_wake", False, str(e)[:200])
    finally:
        db.close()


def _cleanup_scan():
    """Periodic task: dry-run cleanup scan, log and notify when candidates appear."""
    from app.db import SessionLocal
    from app.api.tasks import _build_cleanup_preview
    from app.services.notify import notify_cleanup_candidates

    db = SessionLocal()
    try:
        preview = _build_cleanup_preview(db)
        candidate_count = preview.get("candidate_count", 0)
        message = (
            f"候选 {candidate_count}，qB+DB {preview.get('qb_and_db_count', 0)}，"
            f"仅DB {preview.get('db_only_count', 0)}"
        )
        if candidate_count:
            logger.warning(
                "Cleanup scan found %s candidates (qb_and_db=%s, db_only=%s, total_size=%s, amount_left=%s)",
                candidate_count,
                preview.get("qb_and_db_count", 0),
                preview.get("db_only_count", 0),
                preview.get("total_size", 0),
                preview.get("total_amount_left", 0),
            )
            notify_cleanup_candidates(
                candidate_count,
                preview.get("qb_and_db_count", 0),
                preview.get("db_only_count", 0),
                preview.get("total_size", 0),
                preview.get("total_amount_left", 0),
            )
        else:
            logger.info("Cleanup scan found no candidates")
        _record_run("cleanup_scan", True, message)
    except Exception as e:
        logger.error(f"Cleanup scan failed: {e}")
        _record_run("cleanup_scan", False, str(e)[:200])
    finally:
        db.close()


def apply_scheduler_config():
    """Apply current scheduler config to APScheduler jobs without restarting the app."""
    config = cfg_module.config
    scheduler.add_job(
        _search_subscriptions,
        "interval",
        minutes=max(1, config.scheduler.search_interval_minutes),
        id="search_subscriptions",
        replace_existing=True,
    )
    scheduler.add_job(
        _check_downloads,
        "interval",
        minutes=max(1, config.scheduler.check_complete_interval_minutes),
        id="check_downloads",
        replace_existing=True,
    )
    if config.assistant.enabled and getattr(config.assistant, "wake_interval_hours", 0):
        scheduler.add_job(
            _assistant_wake,
            "interval",
            hours=max(1, int(config.assistant.wake_interval_hours or 0)),
            id="assistant_wake",
            replace_existing=True,
        )
    else:
        job = scheduler.get_job("assistant_wake")
        if job:
            scheduler.remove_job("assistant_wake")

    if config.scheduler.cleanup_scan_enabled:
        scheduler.add_job(
            _cleanup_scan,
            "interval",
            hours=max(1, config.scheduler.cleanup_scan_interval_hours),
            id="cleanup_scan",
            replace_existing=True,
        )
    else:
        job = scheduler.get_job("cleanup_scan")
        if job:
            scheduler.remove_job("cleanup_scan")
    logger.info("Scheduler config applied")


def start_scheduler():
    """Start the scheduler with configured intervals."""
    apply_scheduler_config()
    if not scheduler.running:
        scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler():
    """Shutdown scheduler."""
    scheduler.shutdown(wait=False)


def get_scheduler_status() -> list[dict]:
    """Get status of all scheduled jobs."""
    jobs = []
    for job in scheduler.get_jobs():
        history = _job_history.get(job.id, {})
        jobs.append({
            "id": job.id,
            "name": {
                "search_subscriptions": "订阅搜索",
                "check_downloads": "下载检查",
                "cleanup_scan": "清理扫描",
                "assistant_wake": "助手定时唤醒",
            }.get(job.id, job.id),
            "interval": str(job.trigger),
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "last_run": history.get("last_run"),
            "last_success": history.get("success"),
            "last_message": history.get("message", ""),
        })
    return jobs
