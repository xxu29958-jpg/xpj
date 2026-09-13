"""Read-only eligibility from the provider factory and existing consent/role rules."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.errors import AppError
from app.services.budget_advisor_service._provider_names import canonical_provider_name, is_known_provider
from app.services.budget_advisor_service._providers import get_budget_advisor


@dataclass(frozen=True)
class AdvisorReadiness:
    provider: str
    is_live: bool
    owner_confirmed: bool
    configuration_valid: bool

    def blocked_reason(self, actor_role: str) -> str | None:
        if self.is_live and not self.owner_confirmed:
            return "ai_advisor_not_confirmed"
        if self.is_live and actor_role != "owner":
            return "ai_advisor_owner_required"
        if not self.configuration_valid:
            return "ai_advisor_configuration_invalid"
        if self.provider == "empty":
            return "ai_advisor_provider_empty"
        return None


def get_advisor_readiness() -> AdvisorReadiness:
    cfg = get_settings()
    provider = canonical_provider_name(cfg.budget_advisor_provider)
    known = is_known_provider(provider)
    try:
        get_budget_advisor()
    except AppError:
        valid = False
    else:
        valid = True
    return AdvisorReadiness(
        provider=provider if known else "unsupported",
        is_live=provider == "openai_compat",
        owner_confirmed=cfg.budget_advisor_owner_confirmed,
        configuration_valid=valid,
    )
