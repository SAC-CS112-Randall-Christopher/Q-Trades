"""Frozen paper execution assumptions, not verified venue/account permissions."""

from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, ROUND_UP
from decimal import Decimal as D
from typing import Any

from trading.market import Book

LEGACY_EXECUTION = "paper-rest-ioc-v1"
PUBLIC_EXECUTION = "binance-us-public-2026-09-29-v1"


@dataclass(frozen=True)
class ExecutionProfile:
    id: str
    label: str
    taker_fee: str
    maker_fee: str | None
    slippage: str = "0.0002"
    participation: str = "0.10"
    latency_seconds: int = 1
    expiry_seconds: int = 15
    fee_asset: str = "USD"
    checked_at: str | None = None

    def fee(self, symbol: str) -> D:
        if not symbol.endswith("USD") or self.fee_asset != "USD":
            raise ValueError("Only USD-quote fee simulation is supported; no asset substitution")
        if self.id == PUBLIC_EXECUTION and symbol == "BNBUSD":
            return D("0.0001")
        return D(self.taker_fee)

    def describe(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "venue": "Binance.US public market data",
            "account_verified": False,
            "role": "taker",
            "fill_policy": "Later-book capped IOC; partial fills cancel the remainder",
            "precision": "Observed symbol LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL",
            "settlement": "Paper proceeds only after committed fills; no deposit credit",
            "source": "https://www.binance.us/fees" if self.checked_at else None,
            "limitations": (
                "USD fee asset is a research assumption, not account evidence. Base/BNB fee "
                "payment and resting maker orders are unsupported. Visible depth is incomplete; "
                "queue position, hidden liquidity and own market impact are not modeled. "
                "Exchange timeouts/cancel acknowledgments are not simulated broker fills."
            ),
        }


PROFILES = {
    LEGACY_EXECUTION: ExecutionProfile(
        LEGACY_EXECUTION, "Original / fee stress: 0.10% taker", "0.001", None
    ),
    PUBLIC_EXECUTION: ExecutionProfile(
        PUBLIC_EXECUTION,
        "Published fee scenario: 0.02% taker (BNB/USD 0.01%)",
        "0.0002",
        "0",
        checked_at="2026-09-29",
    ),
}


def execution(a: dict[str, Any]) -> ExecutionProfile:
    key = a.get("execution_profile", LEGACY_EXECUTION)
    if not isinstance(key, str) or key not in PROFILES:
        raise ValueError("Unknown execution profile; no fees or fills were guessed")
    return PROFILES[key]


def floor_step(value: D, step: D) -> D:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def walk_book(
    book: Book,
    side: str,
    quantity: D,
    limit: D,
    rules: dict[str, D],
    profile: ExecutionProfile = PROFILES[LEGACY_EXECUTION],
) -> tuple[D, D]:
    """Shared strategy/benchmark execution; spread and adverse prices are embedded once."""
    if side not in {"buy", "sell"} or profile.fee_asset != "USD":
        raise ValueError("Unsupported execution side or fee asset")
    filled, gross = D(0), D(0)
    for price, available in book.asks if side == "buy" else book.bids:
        adjusted = price * (1 + D(profile.slippage) if side == "buy" else 1 - D(profile.slippage))
        rounding = ROUND_UP if side == "buy" else ROUND_DOWN
        adjusted = (adjusted / rules["tick"]).to_integral_value(rounding=rounding) * rules["tick"]
        if (side == "buy" and adjusted > limit) or (side == "sell" and adjusted < limit):
            break
        amount = floor_step(
            min(quantity - filled, available * D(profile.participation)), rules["step"]
        )
        filled += amount
        gross += amount * adjusted
        if filled >= quantity:
            break
    return filled, gross
