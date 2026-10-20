import httpx
import pytest

from app import main


@pytest.mark.parametrize(("db_ok", "status"), [(True, "ok"), (False, "degraded")])
async def test_health(monkeypatch: pytest.MonkeyPatch, db_ok: bool, status: str) -> None:
    async def fake_db_is_ok() -> bool:
        return db_ok

    monkeypatch.setattr(main, "db_is_ok", fake_db_is_ok)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": status, "db": db_ok}
