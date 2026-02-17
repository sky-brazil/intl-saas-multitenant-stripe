"""FastAPI app for a multi-tenant SaaS billing foundation."""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .billing import get_or_create_subscription, process_subscription_event
from .constants import FEATURE_MIN_PLAN, PLAN_LIMITS, PLAN_ORDER, is_valid_feature, plan_allows_feature
from .db import get_db, init_db
from .models import ApiToken, BillingEvent, Organization, Subscription, User
from .schemas import (
    AuthResponse,
    RegisterRequest,
    SubscriptionPatchRequest,
    SubscriptionOut,
    UserCreateRequest,
    UserOut,
)
from .security import generate_access_token, hash_token, verify_hmac_signature

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class RequestContext:
    user: User
    organization: Organization
    subscription: Subscription
    token: ApiToken


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SaaS Multi-tenant Billing API",
    description="Production-style baseline API for tenant management, billing plans, and Stripe webhook processing.",
    version="0.1.0",
    lifespan=lifespan,
)


def validate_email(email: str) -> None:
    if not EMAIL_REGEX.match(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email format.",
        )


def get_request_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> RequestContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    token_hash = hash_token(credentials.credentials)
    token = db.scalar(
        select(ApiToken).where(
            ApiToken.token_hash == token_hash,
            ApiToken.revoked_at.is_(None),
        )
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    user = db.get(User, token.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token user not found.",
        )

    organization = db.get(Organization, user.organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Organization not found.",
        )

    subscription = get_or_create_subscription(db, organization.id)
    return RequestContext(
        user=user,
        organization=organization,
        subscription=subscription,
        token=token,
    )


def serialize_subscription(subscription: Subscription) -> SubscriptionOut:
    return SubscriptionOut.model_validate(subscription)


def assert_org_user_capacity(db: Session, organization_id: int, plan: str) -> None:
    current_users = db.scalar(
        select(func.count(User.id)).where(User.organization_id == organization_id)
    ) or 0
    max_users = PLAN_LIMITS[plan]["max_users"]
    if current_users >= max_users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Plan user limit reached ({max_users}). Upgrade plan to add more users.",
        )


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    validate_email(payload.email)
    existing_org = db.scalar(
        select(Organization).where(Organization.slug == payload.organization_slug)
    )
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization slug already exists.",
        )

    organization = Organization(
        name=payload.organization_name.strip(),
        slug=payload.organization_slug.strip(),
    )
    user = User(
        organization=organization,
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
    )
    subscription = Subscription(
        organization=organization,
        plan="starter",
        status="trialing",
    )
    access_token = generate_access_token()
    token = ApiToken(
        user=user,
        token_hash=hash_token(access_token),
    )

    db.add_all([organization, user, subscription, token])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to register organization with provided data.",
        ) from None

    db.refresh(organization)
    db.refresh(user)
    db.refresh(subscription)

    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        organization=organization,
        user=user,
        subscription=serialize_subscription(subscription),
    )


@app.post("/auth/tokens/rotate")
def rotate_token(
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    context.token.revoked_at = datetime.now(timezone.utc)
    new_token = generate_access_token()
    db.add(
        ApiToken(
            user_id=context.user.id,
            token_hash=hash_token(new_token),
        )
    )
    db.commit()
    return {
        "access_token": new_token,
        "token_type": "bearer",
    }


@app.get("/organizations/me")
def get_my_organization(context: RequestContext = Depends(get_request_context)) -> dict:
    return {
        "organization": {
            "id": context.organization.id,
            "name": context.organization.name,
            "slug": context.organization.slug,
        },
        "subscription": serialize_subscription(context.subscription).model_dump(),
    }


@app.get("/organizations/me/users", response_model=list[UserOut])
def list_my_users(
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> list[User]:
    return list(
        db.scalars(
            select(User).where(User.organization_id == context.organization.id).order_by(User.id)
        ).all()
    )


@app.post("/organizations/me/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_org_user(
    payload: UserCreateRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> User:
    validate_email(payload.email)
    assert_org_user_capacity(db, context.organization.id, context.subscription.plan)

    existing_user = db.scalar(
        select(User).where(
            User.organization_id == context.organization.id,
            User.email == payload.email.strip().lower(),
        )
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists in this organization.",
        )

    user = User(
        organization_id=context.organization.id,
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/billing/plans")
def get_plan_catalog() -> dict[str, list[dict]]:
    plans: list[dict] = []
    for plan_name, plan_rank in PLAN_ORDER.items():
        features = [
            feature
            for feature, required_plan in FEATURE_MIN_PLAN.items()
            if PLAN_ORDER[plan_name] >= PLAN_ORDER[required_plan]
        ]
        plans.append(
            {
                "name": plan_name,
                "rank": plan_rank,
                "limits": PLAN_LIMITS[plan_name],
                "features": sorted(features),
            }
        )
    return {"plans": plans}


@app.patch("/billing/subscription", response_model=SubscriptionOut)
def update_subscription(
    payload: SubscriptionPatchRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    context.subscription.plan = payload.plan
    context.subscription.status = payload.status
    db.commit()
    db.refresh(context.subscription)
    return serialize_subscription(context.subscription)


@app.post("/billing/webhooks/stripe")
async def process_stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_event_id: str | None = Header(default=None, alias="X-Stripe-Event-Id"),
    stripe_signature: str | None = Header(default=None, alias="X-Stripe-Signature"),
) -> dict:
    raw_payload = await request.body()
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not verify_hmac_signature(raw_payload, stripe_signature, webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload.",
        ) from None

    idempotency_key = stripe_event_id or payload.get("id")
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing event id for idempotency.",
        )

    existing_event = db.scalar(
        select(BillingEvent).where(BillingEvent.idempotency_key == idempotency_key)
    )
    if existing_event:
        return {
            "status": "duplicate",
            "idempotency_key": idempotency_key,
            "event_type": existing_event.event_type,
        }

    updated_subscription, organization_id = process_subscription_event(db, payload)

    billing_event = BillingEvent(
        organization_id=organization_id,
        event_type=payload.get("type", "unknown"),
        idempotency_key=idempotency_key,
        payload=payload,
    )
    db.add(billing_event)
    db.commit()

    return {
        "status": "processed",
        "idempotency_key": idempotency_key,
        "updated_subscription": updated_subscription,
    }


@app.get("/features/{feature_key}")
def check_feature_access(
    feature_key: str,
    context: RequestContext = Depends(get_request_context),
) -> dict:
    if not is_valid_feature(feature_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown feature.",
        )

    allowed = plan_allows_feature(context.subscription.plan, feature_key)
    return {
        "feature": feature_key,
        "plan": context.subscription.plan,
        "required_plan": FEATURE_MIN_PLAN[feature_key],
        "allowed": allowed,
    }


@app.get("/reports/advanced")
def advanced_analytics_report(
    context: RequestContext = Depends(get_request_context),
) -> dict:
    if not plan_allows_feature(context.subscription.plan, "advanced_analytics"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="advanced_analytics requires Growth plan or higher.",
        )
    return {
        "kpis": {
            "mrr": 12800,
            "churn_rate": 0.032,
            "expansion_revenue": 1900,
        }
    }
