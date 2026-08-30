import pytest

from app.services import health


@pytest.mark.asyncio
async def test_readiness_reports_all_dependencies(monkeypatch) -> None:
    async def ok() -> None:
        return None

    monkeypatch.setattr(health, "_check_database", ok)
    monkeypatch.setattr(health, "_check_redis", ok)

    result = await health.readiness_status()

    assert result == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok"},
    }


@pytest.mark.asyncio
async def test_readiness_degrades_without_leaking_exception(monkeypatch) -> None:
    async def ok() -> None:
        return None

    async def failed() -> None:
        raise RuntimeError("postgresql://user:secret@database/private")

    monkeypatch.setattr(health, "_check_database", failed)
    monkeypatch.setattr(health, "_check_redis", ok)

    result = await health.readiness_status()

    assert result["status"] == "degraded"
    assert result["checks"] == {"database": "unavailable", "redis": "ok"}
    assert "secret" not in str(result)
