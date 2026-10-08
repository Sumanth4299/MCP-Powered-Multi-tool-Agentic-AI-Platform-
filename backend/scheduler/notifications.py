from datetime import datetime, timezone
import logging
import uuid
import zoneinfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.reminder import InAppNotification, Reminder
from backend.models.task import Task
from backend.models.user import User

logger = logging.getLogger("notifications")
logging.basicConfig(level=logging.INFO)


class NotificationDispatcher:
    """Dispatches durable task reminder notifications to logging and user inbox tables."""

    @staticmethod
    async def dispatch(
        db: AsyncSession,
        reminder: Reminder,
        task: Task,
        is_catchup: bool = False,
    ) -> bool:
        """
        Dispatches notification and records in-app notification entry.
        Converts UTC due time to user's configured IANA timezone for readable alerts.
        """
        # Resolve user timezone
        user_stmt = select(User).where(User.id == reminder.user_id)
        user_res = await db.execute(user_stmt)
        user = user_res.scalar_one_or_none()

        user_tz = "UTC"
        if user and user.timezone:
            user_tz = user.timezone

        tz_info = zoneinfo.ZoneInfo(user_tz)
        local_due = (
            task.due_at.astimezone(tz_info).strftime("%Y-%m-%d %I:%M %p %Z")
            if task.due_at
            else "Shortly"
        )

        prefix = "🚨 [MISSED / CATCH-UP ALERT]" if is_catchup else "⏰ [TASK REMINDER]"
        title = f"{prefix}: {task.title}"
        body = (
            f"Reminder for task: '{task.title}' (Priority: {task.priority.value.upper()}). "
            f"Scheduled deadline: {local_due}."
        )

        # 1. Log alert to system out
        logger.info(
            f"DISPATCH NOTIFICATION | User={reminder.user_id} | Task={task.id} | {title} | Body={body}"
        )

        # 2. Persist in-app notification record
        notification = InAppNotification(
            user_id=reminder.user_id,
            title=title,
            message=body,
            is_read=False,
        )
        db.add(notification)
        return True