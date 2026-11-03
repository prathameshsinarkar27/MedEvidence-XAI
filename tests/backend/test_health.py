import pytest

from app.core.config import RESEARCH_DISCLAIMER


def test_health_without_database_is_degraded_but_200(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"]["status"] == "not_configured"
    assert body["database"]["target"] is None
    assert body["app_name"] == "MedEvidence-XAI"
    assert body["disclaimer"] == RESEARCH_DISCLAIMER


def test_ready_returns_503_without_database(client):
    assert client.get("/api/health/ready").status_code == 503


def test_unreachable_database_reported_without_leaking_credentials(client, set_database_url):
    # Port 1 is reserved/closed, so the connection is refused quickly.
    set_database_url("postgresql+psycopg://someuser:s3cretpw@127.0.0.1:1/nodb")  # allowlist-secret: fake value for leak test
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"]["status"] == "unreachable"
    assert body["database"]["target"] == "127.0.0.1:1/nodb"
    assert "s3cretpw" not in response.text
    assert "someuser" not in response.text
    assert client.get("/api/health/ready").status_code == 503


def test_unknown_route_404(client):
    assert client.get("/api/does-not-exist").status_code == 404


@pytest.mark.integration
def test_health_with_real_postgres(client, set_database_url, test_database_url):
    set_database_url(test_database_url)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["status"] == "connected"
    assert body["database"]["server_version"]
    assert client.get("/api/health/ready").status_code == 200
