"""Money is integer cents everywhere. Formatting happens only for display."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def format_cents(cents: int | None) -> str:
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    dollars, rem = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{rem:02d}"


def dollars_to_cents(text: str | int | float) -> int:
    """Parse a dollar amount typed by a person ("1,200.50") into integer cents."""
    try:
        value = Decimal(str(text).replace(",", "").replace("$", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"'{text}' is not an amount in dollars.") from exc
    if value != value.quantize(Decimal("0.01")):
        raise ValueError("Amounts can have at most two decimal places.")
    return int(value * 100)
