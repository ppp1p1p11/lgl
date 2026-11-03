"""Per-token prices (USD per million tokens) used for the cost log.

Source: Anthropic pricing as of 2026-10 (input, output, 5-minute cache write, cache read).
Check https://www.anthropic.com/pricing when models or prices change.
"""

from decimal import Decimal

from legalos.gateway.types import Usage

PRICES: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal(4), Decimal(20), Decimal(5), Decimal("0.20")),
    "claude-opus-5": (Decimal(5), Decimal(25), Decimal("6.25"), Decimal("0.50")),
    "claude-opus-4-8": (Decimal(5), Decimal(25), Decimal("6.25"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal(2), Decimal(10), Decimal("2.50"), Decimal("0.20")),
    "demo": (Decimal(0), Decimal(0), Decimal(0), Decimal(0)),
}
# Unknown models (e.g. a new fallback target) are billed at the most expensive known rate,
# so the budget errs on the safe side.
_FALLBACK = max(PRICES.values())


def cost_usd(model: str, usage: Usage) -> Decimal:
    price_in, price_out, price_write, price_read = PRICES.get(model, _FALLBACK)
    million = Decimal(1_000_000)
    return (
        usage.input_tokens * price_in
        + usage.output_tokens * price_out
        + usage.cache_write_tokens * price_write
        + usage.cache_read_tokens * price_read
    ) / million
