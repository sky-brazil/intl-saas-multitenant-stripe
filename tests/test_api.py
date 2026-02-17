from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def client(tmp_path):
    database_url = f"sqlite:///{tmp_path}/test.db"
    db.reset_engine(database_url)
    db.init_db()

    with TestClient(app) as test_client:
        yield test_client


def register_org(client: TestClient, slug: str = "acme-inc") -> str:
    response = client.post(
        "/auth/register",
        json={
            "organization_name": "Acme Inc",
            "organization_slug": slug,
            "email": f"owner@{slug}.com",
            "full_name": "Owner User",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_and_tenant_user_management(client: TestClient) -> None:
    token = register_org(client)

    organization = client.get("/organizations/me", headers=auth_headers(token))
    assert organization.status_code == 200
    assert organization.json()["organization"]["slug"] == "acme-inc"

    users = client.get("/organizations/me/users", headers=auth_headers(token))
    assert users.status_code == 200
    assert len(users.json()) == 1

    created_user = client.post(
        "/organizations/me/users",
        headers=auth_headers(token),
        json={
            "email": "new.user@acme-inc.com",
            "full_name": "New User",
        },
    )
    assert created_user.status_code == 201, created_user.text

    users = client.get("/organizations/me/users", headers=auth_headers(token))
    assert len(users.json()) == 2


def test_feature_gate_changes_after_plan_upgrade(client: TestClient) -> None:
    token = register_org(client, slug="beta-co")

    starter_feature = client.get(
        "/features/advanced_analytics",
        headers=auth_headers(token),
    )
    assert starter_feature.status_code == 200
    assert starter_feature.json()["allowed"] is False

    denied_report = client.get("/reports/advanced", headers=auth_headers(token))
    assert denied_report.status_code == 402

    upgraded = client.patch(
        "/billing/subscription",
        headers=auth_headers(token),
        json={
            "plan": "growth",
            "status": "active",
        },
    )
    assert upgraded.status_code == 200
    assert upgraded.json()["plan"] == "growth"

    allowed_report = client.get("/reports/advanced", headers=auth_headers(token))
    assert allowed_report.status_code == 200
    assert "kpis" in allowed_report.json()


def test_stripe_webhook_idempotency_and_subscription_update(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = register_org(client, slug="gamma-labs")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "test-secret")

    payload = {
        "id": "evt_001",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_001",
                "customer": "cus_001",
                "status": "active",
                "plan": {"nickname": "Enterprise"},
                "metadata": {"organization_slug": "gamma-labs"},
            }
        },
    }
    raw_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        b"test-secret",
        raw_payload,
        hashlib.sha256,
    ).hexdigest()

    first = client.post(
        "/billing/webhooks/stripe",
        content=raw_payload,
        headers={
            "Content-Type": "application/json",
            "X-Stripe-Event-Id": "evt_001",
            "X-Stripe-Signature": signature,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "processed"
    assert first.json()["updated_subscription"] is True

    second = client.post(
        "/billing/webhooks/stripe",
        content=raw_payload,
        headers={
            "Content-Type": "application/json",
            "X-Stripe-Event-Id": "evt_001",
            "X-Stripe-Signature": signature,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "duplicate"

    organization = client.get("/organizations/me", headers=auth_headers(token))
    assert organization.status_code == 200
    assert organization.json()["subscription"]["plan"] == "enterprise"
    assert organization.json()["subscription"]["status"] == "active"
