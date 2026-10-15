"""
Performance Metrics & Statistical Analysis Module.
Computes Win Rate, Profit Factor, Expected Value, Maximum Drawdown,
and rigorously audits the '30% Win Rate' hypothesis under Vietnam market costs.
"""

from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from src.backtest.execution_models import Trade


class PerformanceMetricsCalculator:
    """Calculates comprehensive trading performance and risk-adjusted return metrics."""

    @staticmethod
    def calculate_metrics(
        trades: List[Trade],
        initial_capital: float = 100_000_000.0
    ) -> Dict[str, Any]:
        """
        Calculate full suite of metrics from closed trades.
        """
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_count": 0,
                "loss_count": 0,
                "breakeven_count": 0,
                "win_rate_pct": 0.0,
                "loss_rate_pct": 0.0,
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
                "total_fees_and_taxes": 0.0,
                "roi_pct": 0.0,
                "avg_trade_net_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "win_loss_pnl_ratio": 0.0,
                "profit_factor": 0.0,
                "expected_value_per_trade": 0.0,
                "max_drawdown_pct": 0.0,
                "max_drawdown_amount": 0.0,
                "max_consecutive_wins": 0,
                "max_consecutive_losses": 0,
                "avg_holding_bars": 0.0,
                "win_rate_30pct_viable": False,
                "evaluation_verdict": "NO_TRADES_EXECUTED"
            }

        net_pnls = [t.net_pnl for t in trades]
        gross_pnls = [t.gross_pnl for t in trades]
        fees = [t.commission_paid + t.tax_paid + t.slippage_cost for t in trades]

        wins = [p for p in net_pnls if p > 0]
        losses = [p for p in net_pnls if p < 0]
        breakevens = [p for p in net_pnls if p == 0]

        win_count = len(wins)
        loss_count = len(losses)
        be_count = len(breakevens)

        win_rate = (win_count / total_trades) * 100.0
        loss_rate = (loss_count / total_trades) * 100.0

        total_gross = sum(gross_pnls)
        total_net = sum(net_pnls)
        total_costs = sum(fees)

        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(abs(np.mean(losses))) if losses else 0.0
        win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        # Expected Value per trade = (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        ev_per_trade = (win_rate / 100.0 * avg_win) - (loss_rate / 100.0 * avg_loss)

        # Maximum Drawdown calculation over cumulative equity curve
        equity_curve = [initial_capital]
        current_eq = initial_capital
        for pnl in net_pnls:
            current_eq += pnl
            equity_curve.append(current_eq)

        peaks = np.maximum.accumulate(equity_curve)
        drawdowns = (peaks - equity_curve) / peaks
        drawdown_amounts = peaks - equity_curve

        max_dd_pct = float(np.max(drawdowns)) * 100.0
        max_dd_amount = float(np.max(drawdown_amounts))

        # Consecutive streaks
        max_consec_wins = 0
        max_consec_losses = 0
        curr_wins = 0
        curr_losses = 0

        for pnl in net_pnls:
            if pnl > 0:
                curr_wins += 1
                curr_losses = 0
                max_consec_wins = max(max_consec_wins, curr_wins)
            elif pnl < 0:
                curr_losses += 1
                curr_wins = 0
                max_consec_losses = max(max_consec_losses, curr_losses)
            else:
                curr_wins = 0
                curr_losses = 0

        avg_bars = float(np.mean([t.holding_bars for t in trades]))
        roi_pct = (total_net / initial_capital) * 100.0

        # Assess 30% winrate viability:
        # A 30% win rate requires Win/Loss Ratio > 2.33 strictly to break even: (0.3 * W - 0.7 * L > 0 => W/L > 2.33)
        # Taking costs into account, Win/Loss Ratio typically needs to be > 2.50.
        is_30pct_viable = (win_loss_ratio >= 2.5 and profit_factor > 1.0)

        if total_net > 0 and profit_factor >= 1.2:
            verdict = "PROFITABLE (Positive Expectancy)"
        elif total_net > 0:
            verdict = "MARGINALLY_PROFITABLE (Sensitive to Fees)"
        else:
            verdict = "UNPROFITABLE (Negative Expectancy / Fee Drag)"

        return {
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "breakeven_count": be_count,
            "win_rate_pct": round(win_rate, 2),
            "loss_rate_pct": round(loss_rate, 2),
            "gross_pnl": round(total_gross, 2),
            "net_pnl": round(total_net, 2),
            "total_fees_and_taxes": round(total_costs, 2),
            "roi_pct": round(roi_pct, 2),
            "avg_trade_net_pnl": round(float(np.mean(net_pnls)), 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "win_loss_pnl_ratio": round(win_loss_ratio, 2),
            "profit_factor": round(profit_factor, 2),
            "expected_value_per_trade": round(ev_per_trade, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "max_drawdown_amount": round(max_dd_amount, 2),
            "max_consecutive_wins": max_consec_wins,
            "max_consecutive_losses": max_consec_losses,
            "avg_holding_bars": round(avg_bars, 1),
            "win_rate_30pct_viable": is_30pct_viable,
            "evaluation_verdict": verdict
        }
