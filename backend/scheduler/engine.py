from datetime import datetime, timezone
import logging
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session_factory
from backend.models.reminder import Reminder, ReminderStatus
from backend.models.task import Task
from backend.scheduler.notifications import NotificationDispatcher

logger = logging.getLogger("scheduler")
logging.basicConfig(level=logging.INFO)

scheduler = AsyncIOScheduler()


async def process_due_reminders(is_startup_recovery: bool = False) -> int:
    """
    Core polling worker:
    1. Selects due reminders atomically.
    2. Uses status transition from SCHEDULED -> PROCESSING to ensure idempotency.
    3. Triggers notifications and marks status as SENT.
    """
    now_utc = datetime.now(timezone.utc)
    processed_count = 0

    async with async_session_factory() as db:
        # Atomic selection: filter status=SCHEDULED and scheduled_at <= now
        stmt = (
            select(Reminder, Task)
            .join(Task, Reminder.task_id == Task.id)
            .where(
                and_(
                    Reminder.status == ReminderStatus.SCHEDULED,
                    Reminder.scheduled_at <= now_utc,
                    Task.deleted_at.is_(None),
                )
            )
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(stmt)
        records = result.all()

        if not records:
            return 0

        for reminder, task in records:
            try:
                # Mark as processing immediately
                reminder.status = ReminderStatus.PROCESSING
                await db.flush()

                # Dispatch notification
                success = await NotificationDispatcher.dispatch(
                    db=db,
                    reminder=reminder,
                    task=task,
                    is_catchup=is_startup_recovery,
                )

                if success:
                    reminder.status = ReminderStatus.SENT
                    reminder.sent_at = datetime.now(timezone.utc)
                    processed_count += 1
                else:
                    reminder.status = ReminderStatus.FAILED
                    reminder.retry_count += 1

            except Exception as e:
                logger.error(f"Failed processing reminder {reminder.id}: {str(e)}", exc_info=True)
                reminder.status = ReminderStatus.FAILED
                reminder.retry_count += 1

        await db.commit()

    if processed_count > 0:
        mode_str = "RECOVERY" if is_startup_recovery else "POLL"
        logger.info(f"[{mode_str}] Dispatched {processed_count} due reminder(s).")

    return processed_count


async def run_startup_recovery() -> None:
    """
    Run on application boot:
    Recovers any reminders that fell due while the server was down or restarting.
    """
    logger.info("Initializing Scheduler Startup Recovery scan...")
    # Reset any leftover orphaned 'PROCESSING' states from a sudden crash back to SCHEDULED
    async with async_session_factory() as db:
        reset_stmt = (
            update(Reminder)
            .where(Reminder.status == ReminderStatus.PROCESSING)
            .values(status=ReminderStatus.SCHEDULED)
        )
        await db.execute(reset_stmt)
        await db.commit()

    # Process all overdue reminders immediately as catch-up alerts
    recovered = await process_due_reminders(is_startup_recovery=True)
    logger.info(f"Scheduler Startup Recovery complete. Processed {recovered} missed reminder(s).")


def start_scheduler() -> AsyncIOScheduler:
    """Registers periodic polling job and boots APScheduler."""
    if not scheduler.running:
        scheduler.add_job(
            process_due_reminders,
            trigger="interval",
            seconds=30,
            id="poll_due_reminders",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            kwargs={"is_startup_recovery": False},
        )
        scheduler.start()
        logger.info("AsyncIOScheduler started (30s polling cycle).")
    return scheduler


def stop_scheduler() -> None:
    """Graceful shutdown for background worker."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("AsyncIOScheduler shutdown.")