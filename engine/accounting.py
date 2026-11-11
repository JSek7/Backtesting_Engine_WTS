
from models.models import BotAccount, Fill


def apply_fills(accounts: dict[str, BotAccount], fills: list[Fill], fee_per_unit: float = 0.0) -> None:
    """Apply executions to participating competitor accounts."""

    for fill in fills:

        asset_id = fill.asset_id

        # Buyer
        if fill.buyer_bot is not None:
            account = accounts[fill.buyer_bot]
            account.positions[asset_id] = account.positions.get(asset_id, 0) + fill.quantity
            account.cash -= fill.quantity * (fill.price + fee_per_unit)
            account.fees_paid += fill.quantity * fee_per_unit

        # Seller
        if fill.seller_bot is not None:
            account = accounts[fill.seller_bot]
            account.positions[asset_id] = account.positions.get(asset_id, 0) - fill.quantity
            account.cash += fill.quantity * (fill.price - fee_per_unit)
            account.fees_paid += fill.quantity * fee_per_unit


def calculate_equity(account: BotAccount, mark_prices: dict[str, float]) -> float:
    """Calculate total marked-to-market portfolio equity."""

    return account.cash + sum(position * mark_prices[asset_id] for asset_id, position in account.positions.items())
