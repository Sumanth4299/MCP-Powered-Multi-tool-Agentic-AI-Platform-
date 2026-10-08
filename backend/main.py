from contextlib import asynccontextmanager
from fastapi import FastAPI
from backend.api.auth import router as auth_router
from backend.api.conversations import router as conversations_router
from backend.api.tasks import router as tasks_router
from backend.scheduler.engine import run_startup_recovery, start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Run catch-up recovery scan & activate scheduler
    await run_startup_recovery()
    sched = start_scheduler()
    yield
    # Shutdown: Stop scheduler
    stop_scheduler()


app = FastAPI(
    title="MCP Personal Productivity Agent Backend",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(tasks_router)
app.include_router(conversations_router)