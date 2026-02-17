"""Billing lifecycle helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .constants import is_valid_plan
from .models import Organization, Subscription


def normalize_plan(plan_value: str | None) -> str | None:
    if not plan_value:
        return None
    normalized = plan_value.strip().lower()
    if "enterprise" in normalized:
        return "enterprise"
    if "growth" in normalized or "pro" in normalized:
        return "growth"
    if "starter" in normalized or "basic" in normalized:
        return "starter"
    if is_valid_plan(normalized):
        return normalized
    return None


def normalize_status(status_value: str | None) -> str | None:
    if not status_value:
        return None
    normalized = status_value.strip().lower()
    if normalized in {"trialing", "active", "canceled"}:
        return normalized
    if normalized in {"unpaid", "past_due", "incomplete", "incomplete_expired"}:
        return "canceled"
    return None


def get_or_create_subscription(db: Session, organization_id: int) -> Subscription:
    subscription = db.scalar(
        select(Subscription).where(Subscription.organization_id == organization_id)
    )
    if subscription:
        return subscription

    subscription = Subscription(
        organization_id=organization_id,
        plan="starter",
        status="trialing",
    )
    db.add(subscription)
    db.flush()
    return subscription


def process_subscription_event(db: Session, event_payload: dict) -> tuple[bool, int | None]:
    """Process a simplified Stripe subscription event.

    Returns:
      - bool: whether a subscription was updated
      - organization_id: target organization id when resolved
    """
    event_type = event_payload.get("type")
    if event_type not in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        return False, None

    event_object = event_payload.get("data", {}).get("object", {})
    metadata = event_object.get("metadata", {})
    slug = metadata.get("organization_slug")
    if not slug:
        return False, None

    organization = db.scalar(select(Organization).where(Organization.slug == slug))
    if not organization:
        return False, None

    subscription = get_or_create_subscription(db, organization.id)

    normalized_plan = normalize_plan(
        event_object.get("plan", {}).get("nickname")
        or metadata.get("plan")
        or event_object.get("plan_name")
    )
    if normalized_plan:
        subscription.plan = normalized_plan

    normalized_status = normalize_status(event_object.get("status"))
    if normalized_status:
        subscription.status = normalized_status

    customer_id = event_object.get("customer")
    if customer_id:
        subscription.stripe_customer_id = str(customer_id)

    stripe_subscription_id = event_object.get("id")
    if stripe_subscription_id:
        subscription.stripe_subscription_id = str(stripe_subscription_id)

    period_end = event_object.get("current_period_end")
    if isinstance(period_end, int):
        subscription.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)

    return True, organization.id
