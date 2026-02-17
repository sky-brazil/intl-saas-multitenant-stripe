# 01 - Multi-tenant SaaS Billing (Stripe-ready)

Production-style API foundation for B2B SaaS products that need:

- tenant-aware authentication
- organization and user management
- subscription lifecycle management
- webhook idempotency and signature validation
- feature access by plan tier

## Business positioning

This project can be sold as:

1. **Starter** - SaaS billing baseline (tenancy + plans)
2. **Growth** - Billing + advanced feature gating + integrations
3. **Enterprise** - Hardened security, observability, and SLA workflows

## Tech stack

- **Backend:** FastAPI
- **Database:** SQLAlchemy (SQLite by default, PostgreSQL-ready via `DATABASE_URL`)
- **Containerization:** Docker + Docker Compose
- **Tests:** Pytest + FastAPI TestClient

## Project structure

```text
app/
  billing.py
  constants.py
  db.py
  main.py
  models.py
  schemas.py
  security.py
tests/
  test_api.py
```

## API highlights

- `POST /auth/register` - creates organization, owner user, starter subscription, and access token
- `POST /auth/tokens/rotate` - rotates bearer token
- `GET /organizations/me` - returns tenant and subscription context
- `GET /organizations/me/users` - lists users inside current tenant
- `POST /organizations/me/users` - creates tenant user (enforces plan limits)
- `GET /billing/plans` - returns plan catalog (features and limits)
- `PATCH /billing/subscription` - updates current tenant subscription plan/status
- `POST /billing/webhooks/stripe` - processes Stripe-style events with idempotency
- `GET /features/{feature_key}` - checks if current subscription can access feature
- `GET /reports/advanced` - gated endpoint that requires Growth plan or higher

## Local setup

```bash
cd projects/01-saas-multi-tenant-billing
pip3 install -r requirements.txt
uvicorn app.main:app --reload
```

API docs:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Run tests

```bash
cd projects/01-saas-multi-tenant-billing
pytest -q
```

## Docker

```bash
cd projects/01-saas-multi-tenant-billing
docker compose up --build
```

## Stripe webhook verification

When `STRIPE_WEBHOOK_SECRET` is set, the endpoint validates the request body using HMAC SHA-256 and the header:

- `X-Stripe-Signature`

Idempotency is enforced through:

- `X-Stripe-Event-Id` (or payload `id` fallback)
