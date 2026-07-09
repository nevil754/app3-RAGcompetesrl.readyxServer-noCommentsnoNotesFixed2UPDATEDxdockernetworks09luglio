import pytest

@pytest.mark.asyncio
async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "uptime_seconds" in data

@pytest.mark.asyncio
async def test_health_no_auth_required(client):
    response = await client.get("/health")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_ready_has_checks(client):
    response = await client.get("/ready")

    assert response.status_code in (200, 503)
    data = response.json()
    assert "checks" in data
    assert "redis" in data["checks"]
    assert "sqlserver" in data["checks"]
    assert "qdrant" in data["checks"]

