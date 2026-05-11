"""APScheduler setup."""
from apscheduler.schedulers.background import BackgroundScheduler
from app.config import config

scheduler = BackgroundScheduler()


def _search_subscriptions():
    """Periodic task: search PT sites for subscriptions."""
    from app.services.searcher import search_all_subscriptions
    search_all_subscriptions()


def _check_downloads():
    """Periodic task: check QB for completed downloads."""
    from app.services.pipeline import check_completed_downloads
    check_completed_downloads()


def start_scheduler():
    """Start the scheduler with configured intervals."""
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


def stop_scheduler():
    """Shutdown scheduler."""
    scheduler.shutdown(wait=False)
