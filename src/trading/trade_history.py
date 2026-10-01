"""Read-only, fee-aware trade rows derived from permanent financial evidence."""

from decimal import Decimal, InvalidOperation
from typing import Any

from trading.execution_profiles import execution, walk_book
from trading.paper_engine import fresh_frame


def number(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def ratio(pnl: Any, cost: Any) -> str | None:
    result, basis = number(pnl), number(cost)
    return str(result / basis) if result is not None and basis and basis > 0 else None


def closed_row(event: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    body = event["body"]
    row = {
        "id": f"closed-{event['id']}",
        "event_id": event["id"],
        "account": event["account"],
        "symbol": body["symbol"],
        "status": "closed",
        "opened_at": body["opened_at"],
        "closed_at": body["closed_at"],
        "version": body.get("version"),
        "reason": body.get("reason"),
        "pnl": body.get("pnl"),
        "return_fraction": ratio(body.get("pnl"), body.get("cost")),
        "cost": body.get("cost"),
        "proceeds": body.get("proceeds"),
        "fees": body.get("fees"),
        "quantity": None,
        "entry_price": None,
        "close_price": None,
        "mark_price": None,
        "mark_at": None,
        "price_reason": "Original fill prices are unavailable in retained evidence",
    }
    if len(entries) != 1:
        return row
    entry = entries[0]["body"]
    qty, gross, entry_fee = (number(entry.get(k)) for k in ("filled_quantity", "gross", "fee"))
    cost, proceeds, fees, pnl = (number(body.get(k)) for k in ("cost", "proceeds", "fees", "pnl"))
    if qty is None or qty <= 0 or gross is None or gross <= 0 or entry_fee is None:
        return row
    # A complete closure receipt accumulates all partial exits. Never use the
    # last exit's price as the price for the entire position.
    row.update(quantity=str(qty), entry_price=str(gross / qty))
    if (
        cost is not None
        and proceeds is not None
        and fees is not None
        and pnl is not None
        and entry_fee >= 0
        and fees >= entry_fee
        and cost == gross + entry_fee
        and pnl == proceeds - cost
        and entry.get("fee_asset", "USD") == "USD"
    ):
        row.update(close_price=str((proceeds + fees - entry_fee) / qty), price_reason=None)
    return row


def open_row(
    name: str,
    symbol: str,
    position: dict[str, Any],
    account: dict[str, Any],
    frame: dict[str, Any] | None,
    now: float,
) -> dict[str, Any]:
    entry_fee, exit_fees = number(position.get("entry_fee")), number(position.get("exit_fees"))
    total_cost, remaining_cost = number(position.get("total_cost")), number(position.get("cost"))
    proceeds = number(position.get("exit_proceeds"))
    realized = (
        proceeds - (total_cost - remaining_cost)
        if proceeds is not None and total_cost is not None and remaining_cost is not None
        else None
    )
    row: dict[str, Any] = {
        "id": f"open-{name}-{symbol}-{position['opened_at']}",
        "event_id": None,
        "account": name,
        "symbol": symbol,
        "status": "open",
        "opened_at": position["opened_at"],
        "closed_at": None,
        "version": position.get("version"),
        "reason": position.get("exit_blocked"),
        "quantity": position["quantity"],
        "entry_price": position["entry"],
        "close_price": None,
        "cost": position.get("total_cost"),
        "proceeds": position.get("exit_proceeds"),
        "fees": str(entry_fee + exit_fees)
        if entry_fee is not None and exit_fees is not None
        else None,
        "pnl": None,
        "return_fraction": None,
        "mark_price": None,
        "mark_at": None,
        "unrealized_pnl": None,
        "partial_realized_pnl": str(realized) if realized is not None else None,
        "price_reason": "A fresh executable liquidation estimate is unavailable",
    }
    if not fresh_frame(frame, now) or frame is None or frame["observed"] < position["opened_at"]:
        return row
    try:
        profile, quantity = execution(account), Decimal(position["quantity"])
        if (
            quantity <= 0
            or total_cost is None
            or remaining_cost is None
            or realized is None
            or total_cost <= 0
            or remaining_cost < 0
        ):
            return row
        filled, gross = walk_book(
            frame["book"], "sell", quantity, Decimal(0), frame["rules"], profile
        )
        if (
            filled < quantity
            or quantity < frame["rules"]["min_qty"]
            or gross < frame["rules"]["min_notional"]
        ):
            row["price_reason"] = "Insufficient executable depth or holding below venue minimum"
            return row
        unrealized = gross * (1 - profile.fee(symbol)) - remaining_cost
        row.update(
            pnl=str(realized + unrealized),
            return_fraction=ratio(realized + unrealized, total_cost),
            mark_price=str(gross / quantity),
            mark_at=frame["observed"],
            unrealized_pnl=str(unrealized),
            partial_realized_pnl=str(realized),
            price_reason=None,
        )
    except (KeyError, ValueError, ArithmeticError):
        pass  # Unknown legacy dependencies stay unavailable; never repair financial state here.
    return row
