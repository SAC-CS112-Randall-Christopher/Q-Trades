"""Account purpose separates performance exercises from trading research."""

from typing import Any

PERFORMANCE_DIAGNOSTIC_PURPOSE = "performance_diagnostic"
PERFORMANCE_DIAGNOSTIC_VERSION = "performance-diagnostic-v1"
PERFORMANCE_DIAGNOSTIC_ACCOUNT = "performance-diagnostic"
RESEARCH_PURPOSE = "research"
RESEARCH_EXCLUSION = "Performance diagnostic or unclassified account is excluded from research"


def account_purpose(account: dict[str, Any], name: str | None = None) -> str:
    # The reserved identity/version also protects old or manually supplied records
    # whose explicit diagnostic marker is missing. Existing ordinary accounts keep
    # their historical eligibility; an unknown explicit purpose grants no research.
    if (
        name == PERFORMANCE_DIAGNOSTIC_ACCOUNT
        or account.get("version") == PERFORMANCE_DIAGNOSTIC_VERSION
        or account.get("strategy_version") == PERFORMANCE_DIAGNOSTIC_VERSION
    ):
        return PERFORMANCE_DIAGNOSTIC_PURPOSE
    purpose = account.get("purpose", RESEARCH_PURPOSE)
    return purpose if isinstance(purpose, str) else "unclassified"


def is_performance_diagnostic(account: dict[str, Any], name: str | None = None) -> bool:
    return account_purpose(account, name) == PERFORMANCE_DIAGNOSTIC_PURPOSE


def research_account(account: dict[str, Any], name: str | None = None) -> bool:
    return account_purpose(account, name) == RESEARCH_PURPOSE


def require_research_account(account: dict[str, Any], name: str | None = None) -> None:
    if not research_account(account, name):
        raise ValueError(RESEARCH_EXCLUSION)


def event_research_eligible(event: dict[str, Any]) -> bool:
    body = event.get("body", {})
    if not isinstance(body, dict):
        return False
    name = event.get("account")
    return research_account(event, name) and research_account(body, name)


def require_research_provenance(value: Any) -> None:
    """Reject diagnostic source records at teaching selection and corpus admission.

    This inspects structured provenance, never prose or shared market observations.
    The corpus owners already bound the size/depth of supplied JSON packets.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if (
                item.get("purpose") == PERFORMANCE_DIAGNOSTIC_PURPOSE
                or item.get("version") == PERFORMANCE_DIAGNOSTIC_VERSION
                or item.get("strategy_version") == PERFORMANCE_DIAGNOSTIC_VERSION
                or item.get("account") == PERFORMANCE_DIAGNOSTIC_ACCOUNT
                or item.get("research_eligible") is False
            ):
                raise ValueError(RESEARCH_EXCLUSION)
            # Full decision archives must preserve the whole financial state and
            # every event for exact replay. Their diagnostic neighbors are shared
            # context, not the selected research target. Check selected account,
            # entry/exit/outcome provenance outside that authoritative archive.
            financial_archive = (
                item.get("kind") == "decision"
                and isinstance(item.get("state_before"), dict)
                and isinstance(item["state_before"].get("accounts"), dict)
                and isinstance(item.get("events"), list)
            )
            pending.extend(
                child
                for key, child in item.items()
                if not financial_archive or key not in {"state_before", "state_after", "events"}
            )
        elif isinstance(item, list):
            pending.extend(item)
