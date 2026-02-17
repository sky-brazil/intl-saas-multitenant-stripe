"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    organization_slug: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    email: str = Field(min_length=5, max_length=255)
    full_name: str = Field(min_length=2, max_length=200)


class UserCreateRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    full_name: str = Field(min_length=2, max_length=200)


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    created_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    created_at: datetime


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan: str
    status: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    current_period_end: datetime | None
    updated_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    organization: OrganizationOut
    user: UserOut
    subscription: SubscriptionOut


class SubscriptionPatchRequest(BaseModel):
    plan: Literal["starter", "growth", "enterprise"]
    status: Literal["trialing", "active", "canceled"] = "active"


class StripeWebhookIn(BaseModel):
    id: str | None = None
    type: str
    data: dict
