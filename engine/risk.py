
import math
from dataclasses import replace
from models.models import BotAccount, QuoteAction


def validate_quote(quote: QuoteAction, account: BotAccount, asset_id: str, config: dict) -> QuoteAction:
    """Validate and clip a quote against the bot's position in this asset."""

    limit = config["max_position"]
    max_size = config["max_order_size"]
    tick_size = config["tick_size"]

    for price, size in [(quote.bid_price, quote.bid_size), (quote.ask_price, quote.ask_size)]:
        if type(size) is not int or size < 0:
            raise ValueError("Invalid order size")

        if size > 0:
            if price is None or not math.isfinite(price) or price <= 0:
                raise ValueError("Invalid order price")

            if not math.isclose(price / tick_size, round(price / tick_size), abs_tol=1e-8):
                raise ValueError("Price must align with tick size")

    if quote.bid_size > 0 and quote.ask_size > 0:
        if quote.bid_price >= quote.ask_price:
            raise ValueError("Bid must be below ask")

    position = account.positions.get(asset_id, 0)
    if not -limit <= position <= limit:
        raise ValueError("Account already outside position limits")

    max_bid = max(0, min(max_size, limit - position))
    max_ask = max(0, min(max_size, limit + position))

    bid_size = min(quote.bid_size, max_bid)
    ask_size = min(quote.ask_size, max_ask)

    return replace(quote, bid_price=quote.bid_price if bid_size else None, bid_size=bid_size, ask_price=quote.ask_price if ask_size else None, ask_size=ask_size)


