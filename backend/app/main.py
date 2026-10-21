import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import routes_admin, routes_public
from app.config import get_settings
from app.db.session import get_engine
from app.schemas.api import Health

log = logging.getLogger(__name__)

app = FastAPI(title="AnswerWatch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],  # includes X-Admin-Token
)

if get_settings().admin_password in ("", "change-me"):
    log.warning("ADMIN_PASSWORD is empty or still 'change-me': set a real one before deploying")


async def db_is_ok() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


@app.get("/api/health", response_model=Health, tags=["health"])
async def health() -> Health:
    db_ok = await db_is_ok()
    return Health(status="ok" if db_ok else "degraded", db=db_ok)


app.include_router(routes_public.router)
app.include_router(routes_admin.router)
