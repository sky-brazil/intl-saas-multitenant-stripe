"""Pricing and feature policy definitions."""

from __future__ import annotations

from typing import Final

PlanName = str

PLAN_ORDER: Final[dict[PlanName, int]] = {
    "starter": 1,
    "growth": 2,
    "enterprise": 3,
}

FEATURE_MIN_PLAN: Final[dict[str, PlanName]] = {
    "team_management": "starter",
    "basic_analytics": "starter",
    "priority_support": "growth",
    "advanced_analytics": "growth",
    "api_access": "enterprise",
    "sso": "enterprise",
}

PLAN_LIMITS: Final[dict[PlanName, dict[str, int]]] = {
    "starter": {
        "max_users": 5,
        "max_projects": 10,
    },
    "growth": {
        "max_users": 50,
        "max_projects": 100,
    },
    "enterprise": {
        "max_users": 500,
        "max_projects": 1000,
    },
}


def is_valid_plan(plan: str) -> bool:
    return plan in PLAN_ORDER


def is_valid_feature(feature: str) -> bool:
    return feature in FEATURE_MIN_PLAN


def plan_allows_feature(plan: str, feature: str) -> bool:
    if not is_valid_plan(plan) or not is_valid_feature(feature):
        return False
    return PLAN_ORDER[plan] >= PLAN_ORDER[FEATURE_MIN_PLAN[feature]]
