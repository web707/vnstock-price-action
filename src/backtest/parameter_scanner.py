"""
Parameter Scanner & Sensitivity Analysis Module.
Tests multiple parameter permutations to evaluate robustness and test
the '30% Win Rate' hypothesis under varied structural and candlestick conditions.
"""

from typing import List, Dict, Any, Optional
import itertools
import pandas as pd
from src.strategy.strategy_engine import JohnLucasPruniStrategy
from src.backtest.execution_models import VietnamExecutionEngine
from src.backtest.backtest_engine import BacktestEngine
from src.import_logger import logger


class ParameterScanner:
    """Executes sensitivity grid search across strategic parameters."""

    def __init__(self, repository):
        self.repo = repository

    def run_grid_scan(
        self,
        symbols: List[str],
        swing_params: List[tuple] = [(3, 2), (5, 3)],
        candle_modes: List[str] = ["middle_candle", "all_candles"],
        min_rr_ratios: List[float] = [1.5, 2.0, 3.0],
        entry_modes: List[str] = ["zone_boundary", "zone_midpoint"],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Run backtests over cartesian product of parameters.
        Returns a comparative summary DataFrame.
        """
        combos = list(itertools.product(swing_params, candle_modes, min_rr_ratios, entry_modes))
        logger.info(f"Initiating sensitivity scan across {len(combos)} parameter combinations...")

        results = []
        for idx, ((s_left, s_right), c_mode, min_rr, e_mode) in enumerate(combos, 1):
            param_label = f"S({s_left},{s_right})|{c_mode}|RR>={min_rr}|{e_mode}"
            logger.info(f"[{idx}/{len(combos)}] Testing config: {param_label}...")

            strat = JohnLucasPruniStrategy(
                swing_left=s_left,
                swing_right=s_right,
                candle_validation_mode=c_mode,
                min_risk_reward=min_rr,
                entry_mode=e_mode
            )
            exec_engine = VietnamExecutionEngine()
            engine = BacktestEngine(
                repository=self.repo,
                strategy=strat,
                execution_engine=exec_engine
            )

            res = engine.run_backtest(symbols, start_date=start_date, end_date=end_date)
            m = res["portfolio_metrics"]

            results.append({
                "config_id": idx,
                "parameters": param_label,
                "swing_left": s_left,
                "swing_right": s_right,
                "candle_mode": c_mode,
                "min_rr": min_rr,
                "entry_mode": e_mode,
                "total_trades": m["total_trades"],
                "win_rate_pct": m["win_rate_pct"],
                "win_count": m["win_count"],
                "loss_count": m["loss_count"],
                "win_loss_ratio": m["win_loss_pnl_ratio"],
                "profit_factor": m["profit_factor"],
                "net_pnl": m["net_pnl"],
                "roi_pct": m["roi_pct"],
                "max_drawdown_pct": m["max_drawdown_pct"],
                "ev_per_trade": m["expected_value_per_trade"],
                "verdict": m["evaluation_verdict"]
            })

        return pd.DataFrame(results)
