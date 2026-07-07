import contextlib
from collections.abc import AsyncIterator
from typing import cast

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from api.chat import router as chat_router
from api.conversations import router as conversations_router
from api.routers.admin import router as admin_router
from api.routers.dashboard import router as dashboard_router
from api.routers.employees import router as employees_router
from api.upload import router as upload_router
from db.models import Employee
from db.session import AsyncSessionLocal
from services.rollover import start_rollover_scheduler
from settings import settings


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Schedule the annual vacation-balance rollover (T46), shutting it down
    # cleanly when the server stops.
    scheduler: AsyncIOScheduler = start_rollover_scheduler()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="MyPerks API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
    allow_origins=settings.allowed_origins,
)

app.include_router(admin_router)
app.include_router(dashboard_router)
app.include_router(employees_router)
app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(conversations_router)


@app.get("/")
async def welcome() -> dict[str, str]:
    return {"message": "Welcome to MyPerks API"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "clerk_issuer": settings.clerk_issuer or "(not set)",
        "clerk_jwks_url": settings.clerk_jwks_url or "(not set)",
    }


# ── TEMP: remove before production ───────────────────────────────────────────
@app.get("/test/employees")
async def test_employees() -> list[dict[str, str | int | None]]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Employee))
        employees = result.scalars().all()
        return [
            {
                "id": cast(int, e.id),
                "name": cast(str, e.name),
                "email": cast(str, e.email),
                "department": cast(str | None, e.department),
                "clerk_user_id": cast(str, e.clerk_user_id),
            }
            for e in employees
        ]


# ── END TEMP ──────────────────────────────────────────────────────────────────
