from models.models import BookOrder, BotSubmission, Fill, QuoteAction


class MatchingEngine:

    def __init__(self, asset_id: str):
        self.asset_id = asset_id
        self.reset()

    def reset(self):
        self.bids = []
        self.asks = []
        self.orders = {}
        self.next_bot_order_id = 0
        self.bot_order_ids = {}
        self.sequence = 0
        self.liquidity_totals = dict(provided=0, consumed=0, withdrawn=0)

    # ---------------------------
    # Input conversion
    # ---------------------------

    def submit_bot_quotes(self, bot_id: str, quote: QuoteAction, time: int):
        """Convert one BotSubmission into GTC orders."""

        bot_id = bot_id
        quote = quote
        fills = []

        sides = [("buy", quote.bid_price, quote.bid_size), ("sell", quote.ask_price, quote.ask_size)]

        for side, price, size in sides:
            if size == 0:
                continue

            self.next_bot_order_id += 1
            order_id = f"BOT:{bot_id}:{self.next_bot_order_id}"

            order = BookOrder(order_id, "bot", bot_id, side, price, size, time, self._next_sequence(), "GTC")

            fills.extend(self.submit_order(order))

            # Track only orders that are still resting
            if order_id in self.orders:
                self.bot_order_ids.setdefault(bot_id, []).append(order_id)

        return fills

    def process_event(self, event) -> list[Fill]:
        """Process one generated MarketEvent."""

        data = event.data

        if event.kind == "dealer_cancel":
            self.cancel_order(data["order_id"])
            return []

        if event.kind == "dealer_limit":
            order = BookOrder(data["order_id"], "dealer", data["dealer_id"], data["side"], data["price"], data["quantity"], event.time, self._next_sequence(), "GTC")
            return self.submit_order(order)

        if event.kind == "customer_order":
            sequence = self._next_sequence()
            order = BookOrder(f"CUSTOMER:{sequence}", "customer", "external", data["side"], data["limit_price"], data["quantity"], event.time, sequence, "IOC")
            order.flow_type = "customer"  # Public tapes have no private customer labels.
            return self.submit_order(order)

        if event.kind == "reference_update":
            return []

        raise ValueError(f"Unknown event type: {event.kind}")

    def process_events(self, events) -> list[Fill]:
        """Process a sequence of MarketEvents in chronological order."""

        fills = []

        for event in sorted(events, key=lambda e: (e.time, e.sequence)):
            fills.extend(self.process_event(event))

        return fills

    # ---------------------------
    # Common order processing
    # ---------------------------

    def submit_order(self, order: BookOrder) -> list[Fill]:
        """Match an incoming order, then rest any remaining GTC quantity."""

        fills = self._match(order)

        if order.remaining > 0 and order.time_in_force == "GTC":
            # Only quantity actually left resting supplies new liquidity.
            self.liquidity_totals["provided"] += order.remaining
            if order.side == "buy":
                self.bids.append(order)
            else:
                self.asks.append(order)

            self.orders[order.order_id] = order

        return fills

        
    def _match(self, order: BookOrder) -> list[Fill]:
        """Execute an incoming order against resting liquidity."""

        fills = []
        opposite = self.asks if order.side == "buy" else self.bids

        while order.remaining > 0 and opposite:

            # Find best opposing order using price-time priority
            if order.side == "buy":
                resting = min(opposite, key=lambda x: (x.price, x.time, x.sequence))
                if order.price < resting.price:
                    break
            else:
                resting = min(opposite, key=lambda x: (-x.price, x.time, x.sequence))
                if order.price > resting.price:
                    break

            # Prevent a bot from trading with itself
            if order.owner_type == "bot" and resting.owner_type == "bot" and order.owner_id == resting.owner_id:
                order.remaining = 0
                break

            # Determine executable quantity
            quantity = min(order.remaining, resting.remaining)
            # One matched unit removes one unit from the resting book, even
            # when the execution produces accounting records for two bots.
            self.liquidity_totals["consumed"] += quantity

            buyer = order if order.side == "buy" else resting
            seller = resting if order.side == "buy" else order

            # Record execution at the resting order's price
            fills.append(Fill(
                asset_id=self.asset_id,
                time=order.time,
                price=resting.price,
                quantity=quantity,
                buyer_bot=buyer.owner_id if buyer.owner_type == "bot" else None,
                seller_bot=seller.owner_id if seller.owner_type == "bot" else None,
                buy_order_id=buyer.order_id,
                sell_order_id=seller.order_id,
                buyer_kind=buyer.flow_type if buyer.flow_type != "unknown" else buyer.owner_type,
                seller_kind=seller.flow_type if seller.flow_type != "unknown" else seller.owner_type,
                taker_side=order.side,
            ))

            # Update outstanding quantities
            order.remaining -= quantity
            resting.remaining -= quantity

            # Remove exhausted resting orders
            if resting.remaining == 0:
                self.cancel_order(resting.order_id)

        return fills


    

    # ---------------------------
    # Book management
    # ---------------------------

    
    def cancel_order(self, order_id):
        """Remove an outstanding order if it exists."""

        order = self.orders.pop(order_id, None)

        if order is None:
            return

        # Exhausted orders also call cancel_order, but contribute zero here.
        self.liquidity_totals["withdrawn"] += order.remaining

        book = self.bids if order.side == "buy" else self.asks
        book.remove(order)

        if order.owner_type == "bot":
            ids = self.bot_order_ids.get(order.owner_id, [])
            if order_id in ids:
                ids.remove(order_id)


    def cancel_bot_quotes(self, bot_id):
        """Cancel all remaining quotes belonging to a bot."""

        for order_id in list(self.bot_order_ids.get(bot_id, [])):
            self.cancel_order(order_id)

        self.bot_order_ids.pop(bot_id, None)


    def get_liquidity_snapshot(self):
        """Full-depth flow counters; independent of displayed depth."""
        return dict(self.liquidity_totals, depth=sum(order.remaining for order in self.orders.values()))

    def get_best_bid(self):
        """Return highest resting bid or None."""
        return max((order.price for order in self.bids), default=None)


    def get_best_ask(self):
        """Return lowest resting ask or None."""
        return min((order.price for order in self.asks), default=None)


    def get_book_snapshot(self, depth=5, owner_type=None):
        """Return aggregated available liquidity at each price level."""

        def levels(book, descending):
            quantities = {}

            for order in book:
                if owner_type is not None and order.owner_type != owner_type:
                    continue

                quantities[order.price] = quantities.get(order.price, 0) + order.remaining

            return [{"price": p, "quantity": quantities[p]} for p in sorted(quantities, reverse=descending)[:depth]]

        bids = levels(self.bids, True)
        asks = levels(self.asks, False)

        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None
        mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None

        return {"bids": bids, "asks": asks, "best_bid": best_bid, "best_ask": best_ask, "mid": mid}

    def _next_sequence(self):
        self.sequence += 1
        return self.sequence
