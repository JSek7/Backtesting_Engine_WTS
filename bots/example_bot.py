"""A minimal fixed-size market maker using only public reference prices."""

import math

from bots.base import BaseBot
from models.models import Observation, QuoteAction


class ExampleBot(BaseBot):
    """Quote a fixed number of ticks either side of the latest reference.

    No prediction or inventory skew. The engine clips order sizes at position limits. Missing references fall back to the
    most recent available public price, including the initial public price.
    """

    def __init__(self, tick_sizes=None, quote_size: int = 5, half_spread_ticks: int = 2):
        # Each asset can have its own minimum price increment.
        self.tick_sizes = dict(tick_sizes) if tick_sizes is not None else {"A": 0.01, "B": 0.01}
        if any(not math.isfinite(tick) or tick <= 0 for tick in self.tick_sizes.values()):
            raise ValueError("Tick sizes must be positive and finite")
        if type(quote_size) is not int or quote_size < 1:
            raise ValueError("quote_size must be a positive integer")
        if type(half_spread_ticks) is not int or half_spread_ticks < 1:
            raise ValueError("half_spread_ticks must be a positive integer")
        self.quote_size = quote_size
        self.half_spread_ticks = half_spread_ticks

    def get_quotes(self, observation: Observation, memory: dict) -> tuple[dict[str, QuoteAction], dict]:
        quotes = {}
        for asset_id, market in observation.markets.items():
            # 1. Find the latest usable public price, skipping missing values.
            reference = None
            for price in reversed(market.price_history):
                if price is not None and math.isfinite(price) and price > 0:
                    reference = price
                    break
            if reference is None:
                continue

            # 2. Place a bid below it and an ask above it, on the price grid.
            tick = self.tick_sizes[asset_id]
            bid_ticks = max(1, math.floor(reference / tick - self.half_spread_ticks))
            ask_ticks = max(bid_ticks + 1, math.ceil(reference / tick + self.half_spread_ticks))

            # 3. Quote the same size on both sides. The engine applies limits.
            quotes[asset_id] = QuoteAction(
                bid_price=round(bid_ticks * tick, 12),
                bid_size=self.quote_size,
                ask_price=round(ask_ticks * tick, 12),
                ask_size=self.quote_size,
            )

        # This bot is stateless, so it leaves its memory unchanged.
        return quotes, memory
