"""Frozen, cash-funded end-of-day options research policies. No live-order authority."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

D = Decimal
NY = ZoneInfo("America/New_York")
MODEL = "options-next-session-bbo-v1"
SOURCE = "marketdata-free-aapl-eod"
FEE = D("0.50")  # Per contract per side; simulation assumption, not a broker quote.
RISK = D("0.025")
REVIEW_SECONDS = 14400
VARIANTS: dict[str, dict[str, Any]] = {
    "options-momentum-v1": {"lookback": 5, "move": "0.01", "spread": "0.15"},
    "options-selective-v1": {"lookback": 10, "move": "0.02", "spread": "0.10"},
}


def dec(value: Any, minimum: str | None = None) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise ValueError("Missing numeric evidence")
    result = D(str(value))
    if not result.is_finite() or (minimum is not None and result < D(minimum)):
        raise ValueError("Invalid numeric evidence")
    return result


def quote_valid(q: dict[str, Any], day: str) -> bool:
    try:
        symbol = q["symbol"]
        if not re.fullmatch(r"AAPL\d{6}[CP]\d{8}", symbol):
            return False
        expiry = datetime.strptime(symbol[4:10], "%y%m%d").date().isoformat()
        return bool(
            q["underlying"] == "AAPL"
            and q["expiration_date"] == expiry
            and q["side"] == ("call" if symbol[10] == "C" else "put")
            and dec(q["strike"]) == D(symbol[11:]) / 1000
            and q["day"] == day
            and q["source"] == SOURCE
            and q["receipt_sha256"]
            and 0 <= dec(q["bid"], "0") <= dec(q["ask"], "0.01")
            and dec(q["bid_size"], "0") >= 0
            and dec(q["ask_size"], "0") >= 0
            and q["multiplier"] == "100"
        )
    except (ValueError, KeyError, ArithmeticError, TypeError):
        return False


def signal(history: list[dict[str, Any]], version: str) -> dict[str, Any]:
    rule = VARIANTS[version]
    length = int(rule["lookback"])
    if len(history) <= length:
        return {"eligible": False, "reason": "Historical underlying warmup incomplete"}
    change = dec(history[-1]["close"], "0.01") / dec(history[-length - 1]["close"], "0.01") - 1
    direction = "call" if change > 0 else "put"
    eligible = abs(change) >= D(str(rule["move"]))
    return {
        "eligible": eligible,
        "reason": "Daily momentum confirmed" if eligible else "Daily momentum threshold not met",
        "direction": direction,
        "change": str(change),
        "day": history[-1]["day"],
        "version": version,
        "greeks": "Unavailable in this historical source; not estimated or used",
    }


def qualify(q: dict[str, Any], day: str, version: str) -> str | None:
    if not quote_valid(q, day):
        return "Incomplete, crossed or mismatched historical quote"
    try:
        days = (datetime.fromisoformat(q["expiration_date"]) - datetime.fromisoformat(day)).days
        if not 7 <= days <= 30:
            return "Outside the 7–30 day expiry window"
        bid, ask = dec(q["bid"]), dec(q["ask"])
        if bid <= 0 or (ask - bid) / ((ask + bid) / 2) > D(str(VARIANTS[version]["spread"])):
            return "Spread/liquidation quote does not qualify"
        if min(dec(q["bid_size"]), dec(q["ask_size"])) < 10:
            return "Less than ten displayed contracts"
        if dec(q["volume"], "0") < 100 or dec(q["open_interest"], "0") < 500:
            return "Volume/open-interest screen not met"
    except (ValueError, KeyError, ArithmeticError, TypeError):
        return "Missing liquidity evidence"
    return None
