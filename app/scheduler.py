"""APScheduler setup."""
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import app.config as cfg_module

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

# Track last run results
_job_history: dict[str, dict] = {}


def _record_run(job_id: str, success: bool, message: str = ""):
    """Record a job run result."""
    _job_history[job_id] = {
        "last_run": datetime.now().isoformat(),
        "success": success,
        "message": message,
    }


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


def start_scheduler():
    """Start the scheduler with configured intervals."""
    config = cfg_module.config
    scheduler.add_job(
        _search_subscriptions,
        "interval",
        minutes=config.scheduler.search_interval_minutes,
        id="search_subscriptions",
        replace_existing=True,
    )
    scheduler.add_job(
        _check_downloads,
        "interval",
        minutes=config.scheduler.check_complete_interval_minutes,
        id="check_downloads",
        replace_existing=True,
    )
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
            }.get(job.id, job.id),
            "interval": str(job.trigger),
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "last_run": history.get("last_run"),
            "last_success": history.get("success"),
            "last_message": history.get("message", ""),
        })
    return jobs
