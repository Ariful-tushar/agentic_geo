from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.db.session import get_engine

app = FastAPI(title="AnswerWatch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Health(BaseModel):
    status: str
    db: bool


async def db_is_ok() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


@app.get("/api/health", response_model=Health)
async def health() -> Health:
    db_ok = await db_is_ok()
    return Health(status="ok" if db_ok else "degraded", db=db_ok)
