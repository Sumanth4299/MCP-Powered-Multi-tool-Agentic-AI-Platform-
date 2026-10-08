from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.reminder import Reminder, ReminderStatus
from backend.models.task import Task, TaskPriority, TaskStatus
from backend.schemas.task import TaskCreate, TaskUpdate


class TaskService:
    """
    Domain service for task lifecycle.
    Automatically maintains durable reminder schedules when tasks specify due_at.
    """

    @staticmethod
    async def create_task(
        db: AsyncSession,
        user_id: uuid.UUID,
        data: TaskCreate,
    ) -> Task:
        now = datetime.now(timezone.utc)
        completed_at = now if data.status == TaskStatus.COMPLETED else None

        task = Task(
            user_id=user_id,
            title=data.title.strip(),
            description=data.description.strip() if data.description else None,
            due_at=data.due_at,
            priority=data.priority,
            status=data.status,
            source=data.source.strip().lower(),
            completed_at=completed_at,
        )
        db.add(task)
        await db.flush()  # Generate task.id before creating reminder

        # Durable reminder scheduling:
        # Default policy: trigger reminder 15 minutes before due_at (or at due_at if tight window)
        if task.due_at and task.status != TaskStatus.COMPLETED:
            target_scheduled = task.due_at - timedelta(minutes=15)
            # If 15 minutes before is already in the past, schedule for due_at
            if target_scheduled <= now:
                target_scheduled = task.due_at

            reminder = Reminder(
                task_id=task.id,
                user_id=user_id,
                scheduled_at=target_scheduled,
                status=ReminderStatus.SCHEDULED,
            )
            db.add(reminder)

        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def complete_task(
        db: AsyncSession,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> Task | None:
        stmt = select(Task).where(
            and_(
                Task.id == task_id,
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
            )
        )
        res = await db.execute(stmt)
        task = res.scalar_one_or_none()
        if not task:
            return None

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc)

        # Cancel any pending scheduled reminders when task is marked complete
        cancel_stmt = (
            update(Reminder)
            .where(
                and_(
                    Reminder.task_id == task.id,
                    Reminder.status == ReminderStatus.SCHEDULED,
                )
            )
            .values(status=ReminderStatus.CANCELLED)
        )
        await db.execute(cancel_stmt)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def delete_task(
        db: AsyncSession,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> bool:
        stmt = select(Task).where(
            and_(
                Task.id == task_id,
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
            )
        )
        res = await db.execute(stmt)
        task = res.scalar_one_or_none()
        if not task:
            return False

        task.deleted_at = datetime.now(timezone.utc)

        # Cancel scheduled reminders on soft delete
        cancel_stmt = (
            update(Reminder)
            .where(
                and_(
                    Reminder.task_id == task.id,
                    Reminder.status == ReminderStatus.SCHEDULED,
                )
            )
            .values(status=ReminderStatus.CANCELLED)
        )
        await db.execute(cancel_stmt)
        await db.commit()
        return True

    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        user_id: uuid.UUID,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        search: str | None = None,
    ) -> list[Task]:
        conditions = [Task.user_id == user_id, Task.deleted_at.is_(None)]
        if status:
            conditions.append(Task.status == status)
        if priority:
            conditions.append(Task.priority == priority)
        if search:
            s = f"%{search.strip()}%"
            conditions.append(or_(Task.title.ilike(s), Task.description.ilike(s)))

        stmt = select(Task).where(and_(*conditions)).order_by(Task.due_at.asc().nulls_last())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_task(db: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID) -> Task | None:
        stmt = select(Task).where(
            and_(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def update_task(
        db: AsyncSession,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
        data: TaskUpdate,
    ) -> Task | None:
        task = await TaskService.get_task(db, user_id=user_id, task_id=task_id)
        if not task:
            return None

        patch = data.model_dump(exclude_unset=True)
        for k, v in patch.items():
            setattr(task, k, v)

        if "due_at" in patch and patch["due_at"] is not None:
            # Reschedule pending reminders
            target_scheduled = patch["due_at"] - timedelta(minutes=15)
            await db.execute(
                update(Reminder)
                .where(
                    and_(
                        Reminder.task_id == task.id,
                        Reminder.status == ReminderStatus.SCHEDULED,
                    )
                )
                .values(scheduled_at=target_scheduled)
            )

        await db.commit()
        await db.refresh(task)
        return task