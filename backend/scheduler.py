"""Planned jobs: tracked prices at TRACK_SCHEDULE (09:00 and 18:00 Istanbul by default), the daily
database backup at 08:50, an order-email scan at each tracking time — and every ACTIVE_SCAN_MINUTES while
an order is still open, so a delivery shows soon after its email — and a catch-up for whatever was
missed while the Mac was asleep."""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import backup, config, db, mailbox, orders, tracking

log = logging.getLogger("commerceos.scheduler")

_sched = None
ACTIVE_SCAN_MINUTES = 15


def active_orders_scan():
    """Read the order emails again while something is on its way (no tokens: plain IMAP)."""
    if mailbox.configured() and orders.open_count():
        orders.start_scan("active")


def _backup_job():
    try:
        backup.run()
    except Exception:
        log.exception("backup failed")


def last_slot(now=None):
    """The most recent planned tracking time at or before `now`."""
    tz = ZoneInfo(config.TIMEZONE)
    now = (now or datetime.now(tz)).astimezone(tz)
    best = None
    for days in (0, 1):
        day = now - timedelta(days=days)
        for h, m in config.track_times():
            t = day.replace(hour=h, minute=m, second=0, microsecond=0)
            if t <= now and (best is None or t > best):
                best = t
    return best


def missed_check(now=None):
    """True when the last planned tracking check did not run (app closed or Mac asleep at the time)."""
    slot = last_slot(now)
    last = db.get_meta("track_last_run")
    if slot is None or not db.one("SELECT id FROM tracked LIMIT 1"):
        return False
    return last is None or datetime.fromisoformat(last) < slot


def missed_orders(now=None):
    """True when the order emails were not read at the last planned time."""
    slot = last_slot(now)
    last = db.get_meta("orders_last_scan")
    return slot is not None and (last is None or datetime.fromisoformat(last) < slot)


def start():
    global _sched
    tz = ZoneInfo(config.TIMEZONE)
    _sched = BackgroundScheduler(timezone=tz)
    for h, m in config.track_times():
        _sched.add_job(tracking.check_all, CronTrigger(hour=h, minute=m, timezone=tz), args=("scheduled",),
                       id=f"track-{h:02d}{m:02d}", misfire_grace_time=3600, coalesce=True, max_instances=1)
        _sched.add_job(orders.start_scan, CronTrigger(hour=h, minute=m, timezone=tz), args=("scheduled",),
                       id=f"orders-{h:02d}{m:02d}", misfire_grace_time=3600, coalesce=True, max_instances=1)
    _sched.add_job(active_orders_scan, IntervalTrigger(minutes=ACTIVE_SCAN_MINUTES, timezone=tz), id="orders-active",
                   misfire_grace_time=300, coalesce=True, max_instances=1)
    _sched.add_job(_backup_job, CronTrigger(hour=8, minute=50, timezone=tz), id="backup",
                   misfire_grace_time=3600, coalesce=True)
    _sched.start()
    if not backup.has_today():
        _backup_job()
    if missed_check():
        log.info("tracking check missed — catching up")
        tracking.start_check_all("catch-up")
    if missed_orders() and mailbox.configured():
        log.info("order scan missed — catching up")
        orders.start_scan("catch-up")


def next_check():
    if not _sched:
        return None
    times = [j.next_run_time for j in _sched.get_jobs() if j.id.startswith("track-") and j.next_run_time]
    return min(times).isoformat() if times else None


def stop():
    if _sched:
        _sched.shutdown(wait=False)
