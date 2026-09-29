"""Source-dated decision packet. It grants no execution or account authority."""

import copy
import time
from decimal import Decimal as D
from typing import Any

from trading.experiment_registry import fingerprint

VERSION = "live-readiness-2026-09-29-v1"
CHECKED = "2026-09-29"
SOURCES = [
    {"title": "Published fees", "url": "https://www.binance.us/fees"},
    {
        "title": "Supported states",
        "url": "https://support.binance.us/en/articles/9842798-list-of-supported-and-unsupported-states-and-regions",
    },
    {"title": "Terms (June 5, 2026)", "url": "https://www.binance.us/terms-of-use"},
    {
        "title": "Deposit reversals and negative balances",
        "url": "https://support.binance.us/en/articles/10309366-understanding-and-settling-a-negative-balance",
    },
    {
        "title": "Withdrawal holds",
        "url": "https://support.binance.us/en/articles/9842883-why-is-a-portion-of-my-balance-unable-to-be-withdrawn-or-unavailable",
    },
    {
        "title": "API permissions and key safety",
        "url": "https://support.binance.us/en/articles/9842812-binance-us-api-keys-best-practices-safety-tips",
    },
    {"title": "Current Binance.US API", "url": "https://docs.binance.us/"},
    {
        "title": "Self-trade prevention",
        "url": "https://support.binance.us/en/articles/9842907-self-trade-prevention",
    },
    {
        "title": "FDIC uninsured products",
        "url": "https://www.fdic.gov/resources/deposit-insurance/financial-products-not-insured",
    },
]
FACTS = [
    (
        "Colorado appears in the venue's supported-state list; individual eligibility"
        " and verification remain unknown."
    ),
    (
        "Published BTC/USD and ETH/USD scenario: 0% maker, 0.02% taker. Actual "
        "commissions and fee assets remain unverified."
    ),
    (
        "ACH pre-credit can be reversed into a negative balance. A seven-day "
        "withdrawal hold is not proof of irreversible funding."
    ),
    (
        "Terms cover API use and retain intellectual-property rights; a public "
        "endpoint is not a redistribution license."
    ),
    (
        "Crypto custody is not FDIC deposit insurance. Venue failure, transfer "
        "restrictions and any stablecoin quote carry separate risks."
    ),
    (
        "The terms describe automatic soft-staking for some eligible assets; asset "
        "eligibility and account opt-out must be verified."
    ),
    (
        "Client order IDs can be reused after a fill. Unknown submissions require "
        "reconciliation; cancel/replace can partially succeed."
    ),
]
SYMBOLS = [
    {
        "symbol": "BTCUSD",
        "checked_at": 1790720246.6945324,
        "status": "TRADING",
        "price_tick": "0.01",
        "quantity_step": "0.00001",
        "min_notional_usd": "1.00",
        "url": "https://api.binance.us/api/v3/exchangeInfo?symbol=BTCUSD",
        "response_sha256": "c9922cd35faa5676c5d0587d9da833d0cef05eb57da71ac60a01474ffc35e69f",
    },
    {
        "symbol": "ETHUSD",
        "checked_at": 1790720247.475108,
        "status": "TRADING",
        "price_tick": "0.01",
        "quantity_step": "0.0001",
        "min_notional_usd": "1.00",
        "url": "https://api.binance.us/api/v3/exchangeInfo?symbol=ETHUSD",
        "response_sha256": "8786ffa920d44ef279993e8468365802ba1483e6ac4d646d639cc75cb8bde784",
    },
]
BLOCKERS = [
    "No selected live candidate or independently qualified subsequent forward record.",
    (
        "Private eligibility, permissions, commissions, fee currency and transfer "
        "limits are unverified."
    ),
    "Deposit finality, reversals, liabilities, custody, staking and data rights remain unresolved.",
    "No deterministic live adapter or broker reconciliation acceptance has been implemented.",
    (
        "Paper fills, synthetic tests and a finite local soak do not establish live "
        "returns or 24/7 reliability."
    ),
    (
        "Total live capital and operating budget require a separate decision; paper "
        "account funding is not live allocation."
    ),
]
REQUIREMENTS = [
    (
        "One account-wide settled-cash ledger with atomic reservations, fee buffers "
        "and exposure limits; no credit, leverage or automatic deposits."
    ),
    (
        "Persist a unique intent before submission; reconcile unknown outcomes before"
        " retries. Client IDs alone are insufficient."
    ),
    (
        "Apply all current symbol/account filters, permission checks and actual "
        "commission assets; retain partial fills, dust and blocked exits."
    ),
    (
        "Reconcile balances, open orders, fills and fees at startup and after gaps; "
        "freeze new risk on any mismatch."
    ),
    (
        "Use account-wide self-trade prevention and separate strategies without "
        "multiplying capital or cancelling another owner's orders."
    ),
    (
        "Handle cancel/replace partial success, clock/stream gaps and rate limits; "
        "every financial state transition remains journaled."
    ),
    (
        "Keep a separate read-only monitor key and narrowly scoped trading key with "
        "withdrawals disabled, IP restrictions and secret storage outside research."
    ),
    (
        "Pause new risk separately from managing existing positions; unknown or "
        "blocked liquidation stays visible. Restart cannot reset losses."
    ),
    (
        "Approval freezes one candidate hash, source revision, account permissions, "
        "settled total capital, risk limits, fee schedule and monitoring budget."
    ),
    (
        "Rollback pauses new risk and reconciles positions/orders before code "
        "changes; never restore an older financial database or blindly retry an exit."
    ),
]


def economics(capital: str) -> dict[str, str]:
    """Illustrative same-price full-cash round trip with an entry-fee reserve."""
    amount = D(capital)
    return {
        "capital_usd": capital,
        "published_fee_only_round_trip_usd": str(amount * 2 * D("0.0002") / D("1.0002")),
        "legacy_fee_only_round_trip_usd": str(amount * 2 * D("0.001") / D("1.001")),
        "two_bp_each_side_price_proxy_usd": str(amount * D("0.0004")),
        "illustrative_one_usd_monthly_operating_percent": str(100 / amount),
    }


def packet(state: dict[str, Any] | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "version": VERSION,
        "sources_checked_on": CHECKED,
        "decision": "not_ready",
        "live_execution": False,
        "facts": FACTS,
        "sources": SOURCES,
        "public_symbols": SYMBOLS,
        "blockers": BLOCKERS,
        "remaining_engineering": REQUIREMENTS,
        "economics": [economics("50"), economics("100")],
        "economics_limits": (
            "Fee-only and price proxies omit spread, depth, latency, dust, transfer "
            "costs and taxes. $1/month is an example, not a measured bill. Minimum "
            "executable size depends on price, quantity steps and every live filter."
        ),
        "risk_envelope": {
            "live_candidate": None,
            "live_capital_allocated_usd": "0",
            "proposed_total_capital_options_usd": ["50", "100"],
            "paper_policy": "cash-spot-hard-stop-v1",
            "paper_planned_risk_per_order_fraction": "0.025",
            "paper_planned_total_risk_fraction": "0.05",
            "paper_order_cash_fraction": "0.5",
            "paper_gross_exposure_fraction": "0.9",
            "paper_drawdown_latch_fraction": "0.35",
            "limits": (
                "Planned stop risk is not a guaranteed loss cap; gaps, custody and "
                "blocked exits can lose the allocation. Funding reversals and terms "
                "prevent a promise of zero external liability. These paper limits "
                "grant no live permission."
            ),
        },
    }
    result = copy.deepcopy(facts)
    result["facts_sha256"] = fingerprint(facts)
    learning = (state or {}).get("learning", {})
    result["current_paper_evidence"] = {
        "evidence_kind": (state or {}).get("evidence_kind", "unavailable"),
        "research_incumbent": learning.get("incumbent", "primary"),
        "paper_role_version": learning.get("role_version", 0),
        "retained_report_count": len(learning.get("reports", {})),
        "candidates": [
            {
                "account": n,
                "version": a["version"],
                "artifact_sha256": a["numerical_artifact"].get("sha256"),
            }
            for n, a in (state or {}).get("accounts", {}).items()
            if a.get("numerical_artifact")
        ],
        "meaning": (
            "A paper role or report never grants live authority. Review full "
            "protected reports and subsequent results separately."
        ),
    }
    result["generated_at"] = time.time()
    return result
