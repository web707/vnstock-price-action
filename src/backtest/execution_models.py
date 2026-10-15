"""
Execution Models, Orders, Trades, and Vietnam Transaction Cost Engine.
Simulates Limit orders, Stop Loss, Take Profit, same-bar collisions, and realistic Vietnam exchange fees.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import pandas as pd


@dataclass
class Order:
    order_id: str
    signal_id: str
    symbol: str
    order_type: str  # 'BUY_LIMIT' or 'SELL_LIMIT'
    placed_bar_idx: int
    placed_date: Any
    limit_price: float
    stop_loss: float
    take_profit: float
    quantity: int
    status: str  # 'PENDING', 'FILLED', 'EXPIRED', 'CANCELLED'
    fill_bar_idx: Optional[int] = None
    fill_date: Optional[Any] = None
    fill_price: Optional[float] = None


@dataclass
class Trade:
    trade_id: str
    order_id: str
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    entry_bar_idx: int
    entry_date: Any
    entry_price: float
    exit_bar_idx: int
    exit_date: Any
    exit_price: float
    exit_reason: str  # 'TAKE_PROFIT', 'STOP_LOSS', 'END_OF_DATA'
    quantity: int
    gross_pnl: float
    net_pnl: float
    return_pct: float
    commission_paid: float
    tax_paid: float
    slippage_cost: float
    holding_bars: int


class VietnamExecutionEngine:
    """Simulates realistic order execution with Vietnam stock market fee & tax structure."""

    def __init__(
        self,
        brokerage_fee_pct: float = 0.0015,  # 0.15% per trade
        tax_sell_pct: float = 0.0010,       # 0.10% tax on sales value (Vietnam regulation)
        slippage_pct: float = 0.0005,       # 0.05% slippage
        same_bar_collision: str = "sl_first", # 'sl_first' (conservative) or 'tp_first'
        max_pending_bars: int = 5,          # Pending limit order expires after N bars
        round_lot_size: int = 100           # Vietnam round lot size (100 shares)
    ):
        self.brokerage_fee_pct = brokerage_fee_pct
        self.tax_sell_pct = tax_sell_pct
        self.slippage_pct = slippage_pct
        self.same_bar_collision = same_bar_collision
        self.max_pending_bars = max_pending_bars
        self.round_lot_size = round_lot_size

    def calculate_trade_pnl(
        self,
        direction: str,
        entry_price: float,
        exit_price: float,
        quantity: int
    ) -> Dict[str, float]:
        """
        Calculate gross PnL, commissions, tax, slippage, and net PnL.
        """
        entry_value = entry_price * quantity
        exit_value = exit_price * quantity

        # Commission on entry and exit
        comm_entry = entry_value * self.brokerage_fee_pct
        comm_exit = exit_value * self.brokerage_fee_pct
        total_commission = comm_entry + comm_exit

        # Tax: 0.1% on total selling value (Long sell or Short buyback value)
        tax = (exit_value if direction == "LONG" else entry_value) * self.tax_sell_pct

        # Slippage cost
        slippage = (entry_value + exit_value) * self.slippage_pct

        total_costs = total_commission + tax + slippage

        if direction == "LONG":
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price) * quantity

        net_pnl = gross_pnl - total_costs
        return_pct = (net_pnl / entry_value) * 100.0 if entry_value > 0 else 0.0

        return {
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "return_pct": round(return_pct, 4),
            "commission_paid": round(total_commission, 2),
            "tax_paid": round(tax, 2),
            "slippage_cost": round(slippage, 2),
            "total_costs": round(total_costs, 2)
        }

    def evaluate_pending_order(self, order: Order, bar_idx: int, row: pd.Series, t_date: Any) -> bool:
        """
        Check if pending Limit order is filled at bar_idx (bar_idx > placed_bar_idx).
        Returns True if filled.
        """
        if order.status != "PENDING":
            return False

        # Expiry check
        if (bar_idx - order.placed_bar_idx) > self.max_pending_bars:
            order.status = "EXPIRED"
            return False

        h = float(row["HIGH_PRICE"])
        l = float(row["LOW_PRICE"])
        o = float(row["OPEN_PRICE"])

        if order.order_type == "BUY_LIMIT":
            # Buy limit fills if market low reaches or dips below limit price
            if l <= order.limit_price:
                order.status = "FILLED"
                order.fill_bar_idx = bar_idx
                order.fill_date = t_date
                # Realistic fill: if market gapped down below limit at open, fill at open; otherwise at limit
                order.fill_price = min(order.limit_price, o) if o < order.limit_price else order.limit_price
                return True

        elif order.order_type == "SELL_LIMIT":
            if h >= order.limit_price:
                order.status = "FILLED"
                order.fill_bar_idx = bar_idx
                order.fill_date = t_date
                order.fill_price = max(order.limit_price, o) if o > order.limit_price else order.limit_price
                return True

        return False

    def evaluate_open_position(
        self,
        order: Order,
        bar_idx: int,
        row: pd.Series,
        t_date: Any
    ) -> Optional[Trade]:
        """
        Check if active position hits Stop Loss or Take Profit at bar_idx.
        Handles same-bar collision with conservative priority.
        """
        h = float(row["HIGH_PRICE"])
        l = float(row["LOW_PRICE"])

        direction = "LONG" if order.order_type == "BUY_LIMIT" else "SHORT"
        entry_price = order.fill_price or order.limit_price
        sl = order.stop_loss
        tp = order.take_profit

        exit_triggered = False
        exit_price = 0.0
        exit_reason = ""

        if direction == "LONG":
            sl_hit = (l <= sl)
            tp_hit = (h >= tp)

            if sl_hit and tp_hit:
                # Same-bar collision
                if self.same_bar_collision == "sl_first":
                    exit_triggered = True
                    exit_price = sl
                    exit_reason = "STOP_LOSS (SAME_BAR_COLLISION)"
                else:
                    exit_triggered = True
                    exit_price = tp
                    exit_reason = "TAKE_PROFIT"
            elif sl_hit:
                exit_triggered = True
                exit_price = sl
                exit_reason = "STOP_LOSS"
            elif tp_hit:
                exit_triggered = True
                exit_price = tp
                exit_reason = "TAKE_PROFIT"

        else:  # SHORT
            sl_hit = (h >= sl)
            tp_hit = (l <= tp)

            if sl_hit and tp_hit:
                if self.same_bar_collision == "sl_first":
                    exit_triggered = True
                    exit_price = sl
                    exit_reason = "STOP_LOSS (SAME_BAR_COLLISION)"
                else:
                    exit_triggered = True
                    exit_price = tp
                    exit_reason = "TAKE_PROFIT"
            elif sl_hit:
                exit_triggered = True
                exit_price = sl
                exit_reason = "STOP_LOSS"
            elif tp_hit:
                exit_triggered = True
                exit_price = tp
                exit_reason = "TAKE_PROFIT"

        if exit_triggered:
            pnl_stats = self.calculate_trade_pnl(
                direction=direction,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=order.quantity
            )
            holding_bars = bar_idx - (order.fill_bar_idx or order.placed_bar_idx)

            return Trade(
                trade_id=f"TRD_{order.order_id}_{bar_idx}",
                order_id=order.order_id,
                symbol=order.symbol,
                direction=direction,
                entry_bar_idx=order.fill_bar_idx or order.placed_bar_idx,
                entry_date=order.fill_date or order.placed_date,
                entry_price=entry_price,
                exit_bar_idx=bar_idx,
                exit_date=t_date,
                exit_price=exit_price,
                exit_reason=exit_reason,
                quantity=order.quantity,
                gross_pnl=pnl_stats["gross_pnl"],
                net_pnl=pnl_stats["net_pnl"],
                return_pct=pnl_stats["return_pct"],
                commission_paid=pnl_stats["commission_paid"],
                tax_paid=pnl_stats["tax_paid"],
                slippage_cost=pnl_stats["slippage_cost"],
                holding_bars=holding_bars
            )

        return None
