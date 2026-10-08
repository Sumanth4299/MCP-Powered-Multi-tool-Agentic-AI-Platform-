from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
import os
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["SECRET_KEY"] = "test-secret-key-32-characters-long-minimum-abc123"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from backend.models.base import Base
from backend.models.reminder import InAppNotification, Reminder, ReminderStatus
from backend.models.task import Task
from backend.models.user import User
from backend.schemas.task import TaskCreate
from backend.scheduler.engine import process_due_reminders, run_startup_recovery
from backend.services.task_service import TaskService

test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def init_db():
    import backend.database
    import backend.scheduler.engine
    # Direct session factories to in-memory test database
    backend.database.async_session_factory = TestSession
    backend.scheduler.engine.async_session_factory = TestSession

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def sample_user() -> User:
    async with TestSession() as session:
        user = User(
            id=uuid.uuid4(),
            name="Scheduler Tenant",
            email="scheduler@example.com",
            password_hash="mock",
            timezone="Asia/Kolkata",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_auto_schedule_reminder_on_task_creation(sample_user: User):
    """Verify creating a task with due_at automatically schedules a Reminder in PostgreSQL."""
    due = datetime.now(timezone.utc) + timedelta(hours=2)

    async with TestSession() as session:
        task = await TaskService.create_task(
            db=session,
            user_id=sample_user.id,
            data=TaskCreate(
                title="Submit Project Pitch",
                due_at=due,
            ),
        )

        stmt = select(Reminder).where(Reminder.task_id == task.id)
        res = await session.execute(stmt)
        reminder = res.scalar_one_or_none()

        assert reminder is not None
        assert reminder.status == ReminderStatus.SCHEDULED
        assert reminder.user_id == sample_user.id
        # Default reminder is 15 minutes before deadline
        scheduled_at = reminder.scheduled_at
        if scheduled_at.tzinfo is None:
            # SQLite (tests only) drops tzinfo; values are stored as UTC.
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        assert scheduled_at == due - timedelta(minutes=15)


@pytest.mark.asyncio
async def test_polling_processes_due_reminders_and_dispatches_inbox(sample_user: User):
    """Verify polling transitions due reminders to SENT and generates in-app notifications."""
    past_due = datetime.now(timezone.utc) - timedelta(minutes=5)

    async with TestSession() as session:
        task = Task(
            user_id=sample_user.id,
            title="Urgent Thesis Review",
            due_at=past_due,
        )
        session.add(task)
        await session.flush()

        # Create reminder that is already due
        reminder = Reminder(
            task_id=task.id,
            user_id=sample_user.id,
            scheduled_at=past_due,
            status=ReminderStatus.SCHEDULED,
        )
        session.add(reminder)
        await session.commit()

    # Trigger polling cycle
    dispatched = await process_due_reminders(is_startup_recovery=False)
    assert dispatched == 1

    # Verify states in database
    async with TestSession() as session:
        rem_res = await session.execute(select(Reminder).where(Reminder.task_id == task.id))
        updated_reminder = rem_res.scalar_one()
        assert updated_reminder.status == ReminderStatus.SENT
        assert updated_reminder.sent_at is not None

        # Verify durable in-app inbox notification was recorded
        notif_res = await session.execute(
            select(InAppNotification).where(InAppNotification.user_id == sample_user.id)
        )
        notif = notif_res.scalar_one()
        assert "Urgent Thesis Review" in notif.title
        assert notif.is_read is False


@pytest.mark.asyncio
async def test_reboot_startup_recovery(sample_user: User):
    """
    Verify that upon application restart, reminders scheduled in the past
    (e.g., during downtime) are recovered and sent as catch-up alerts.
    """
    downtime_due = datetime.now(timezone.utc) - timedelta(hours=3)

    async with TestSession() as session:
        task = Task(
            user_id=sample_user.id,
            title="Downtime Missed Task",
            due_at=downtime_due,
        )
        session.add(task)
        await session.flush()

        reminder = Reminder(
            task_id=task.id,
            user_id=sample_user.id,
            scheduled_at=downtime_due,
            status=ReminderStatus.SCHEDULED,
        )
        session.add(reminder)
        await session.commit()

    # Execute startup recovery routine
    await run_startup_recovery()

    async with TestSession() as session:
        rem_res = await session.execute(select(Reminder).where(Reminder.task_id == task.id))
        recovered_reminder = rem_res.scalar_one()
        assert recovered_reminder.status == ReminderStatus.SENT

        notif_res = await session.execute(
            select(InAppNotification).where(InAppNotification.user_id == sample_user.id)
        )
        notif = notif_res.scalar_one()
        assert "[MISSED / CATCH-UP ALERT]" in notif.title


@pytest.mark.asyncio
async def test_idempotent_delivery_prevents_duplicates(sample_user: User):
    """Ensure running consecutive poll cycles does not double-send reminders or duplicate notifications."""
    due = datetime.now(timezone.utc) - timedelta(minutes=1)

    async with TestSession() as session:
        task = Task(
            user_id=sample_user.id,
            title="Idempotency Test",
            due_at=due,
        )
        session.add(task)
        await session.flush()

        reminder = Reminder(
            task_id=task.id,
            user_id=sample_user.id,
            scheduled_at=due,
            status=ReminderStatus.SCHEDULED,
        )
        session.add(reminder)
        await session.commit()

    # Cycle 1: Dispatches 1 reminder
    first_run = await process_due_reminders()
    assert first_run == 1

    # Cycle 2: Reminder is already SENT; dispatches 0
    second_run = await process_due_reminders()
    assert second_run == 0

    # Ensure only 1 notification exists
    async with TestSession() as session:
        notif_res = await session.execute(
            select(InAppNotification).where(InAppNotification.user_id == sample_user.id)
        )
        notifications = notif_res.scalars().all()
        assert len(notifications) == 1