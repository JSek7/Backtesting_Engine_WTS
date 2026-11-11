"""Editable, single-file starter: reference-price EWMA and inventory skew.

Use the optional constructor inputs for public instrument rules. The organiser
will publish the actual rules; defaults keep this class callable without args.
"""
import math
from bots.base import BaseBot
from models.models import QuoteAction


class MyBot(BaseBot):
    def __init__(self, tick_sizes=None, position_limits=None, max_order_sizes=None):
        self.tick_sizes = tick_sizes or dict.fromkeys(("A", "B", "C"), 0.01)
        self.position_limits = position_limits or dict.fromkeys(self.tick_sizes, 50)
        self.max_order_sizes = max_order_sizes or dict.fromkeys(self.tick_sizes, 20)

    @staticmethod
    def update_estimate(history, state):
        """Process each new reference once, leaving missing observations missing."""
        processed = state.get("history_length", 0)
        estimate = state.get("ewma")
        for price in history[processed:]:
            if price is not None and math.isfinite(price) and price > 0:
                estimate = price if estimate is None else 0.3 * price + 0.7 * estimate
        state.update(history_length=len(history), ewma=estimate)
        return estimate

    def get_quotes(self, observation, memory):
        quotes = {}
        for asset_id, market in observation.markets.items():
            state = memory.setdefault(asset_id, {})
            estimate = self.update_estimate(market.price_history, state)
            if estimate is None or asset_id not in self.tick_sizes:
                continue
            tick = self.tick_sizes[asset_id]
            position = market.position
            limit = self.position_limits[asset_id]
            half_spread = 3 * tick
            inventory_fraction = position / limit if limit else 0.0
            center = estimate - half_spread * inventory_fraction
            bid_ticks = max(1, math.floor((center - half_spread) / tick))
            ask_ticks = max(bid_ticks + 1, math.ceil((center + half_spread) / tick))
            size = min(5, self.max_order_sizes[asset_id])
            bid_size = max(0, min(size, limit - position))
            ask_size = max(0, min(size, limit + position))
            quotes[asset_id] = QuoteAction(
                round(bid_ticks * tick, 12) if bid_size else None, int(bid_size),
                round(ask_ticks * tick, 12) if ask_size else None, int(ask_size),
            )
        return quotes, memory
