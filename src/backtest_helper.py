"""
Backtest Helper Module.
Provides high-performance query interfaces, data formatting, and anti-lookahead protection
to feed the next stage's quantitative backtesting and algorithmic trading strategies.
"""

from typing import List, Optional, Union
from datetime import date
import pandas as pd
from src.import_logger import logger


class BacktestHelper:
    """Convenience facade for extracting backtesting price matrices and series."""

    def __init__(self, repository):
        self.repo = repository

    def get_symbol_history(
        self,
        symbol: str,
        start_date: Optional[Union[str, date]] = None,
        end_date: Optional[Union[str, date]] = None,
        use_adj_close: bool = False
    ) -> pd.DataFrame:
        """
        Extract clean OHLCV DataFrame for a specific stock indexed by TRADE_DATE.
        Guarantees chronological order and strict filtering.
        """
        s_date = str(start_date) if start_date else None
        e_date = str(end_date) if end_date else None

        df = self.repo.query_historical_prices(symbol, start_date=s_date, end_date=e_date)
        if df.empty:
            logger.warning(f"No price history found for symbol: {symbol}")
            return pd.DataFrame()

        # Format trade date index
        df["TRADE_DATE"] = pd.to_datetime(df["TRADE_DATE"])
        df = df.set_index("TRADE_DATE").sort_index()

        if use_adj_close and "ADJ_CLOSE" in df.columns:
            # If adjusted close requested, calculate adjustment factor and adjust O,H,L
            # adj_factor = ADJ_CLOSE / CLOSE_PRICE
            factor = df["ADJ_CLOSE"] / df["CLOSE_PRICE"]
            df["ADJ_OPEN"] = df["OPEN_PRICE"] * factor
            df["ADJ_HIGH"] = df["HIGH_PRICE"] * factor
            df["ADJ_LOW"] = df["LOW_PRICE"] * factor

        return df

    def get_cross_sectional_matrix(
        self,
        trade_date: Union[str, date],
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Get price snapshot for universe of stocks on a single trading day (Cross-section).
        Useful for ranking, factor calculation, and portfolio rebalancing.
        """
        t_date = str(trade_date)
        df = self.repo.query_cross_sectional_prices(t_date, symbols=symbols)
        if not df.empty and "SYMBOL" in df.columns:
            df = df.set_index("SYMBOL")
        return df

    def get_price_panel(
        self,
        symbols: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        price_field: str = "CLOSE_PRICE"
    ) -> pd.DataFrame:
        """
        Create a 2D Price Matrix (Date x Symbol) for multiple stocks.
        Ideal for computing returns, covariance matrices, and Sharpe ratios.
        """
        series_list = []
        for sym in symbols:
            df = self.get_symbol_history(sym, start_date=start_date, end_date=end_date)
            if not df.empty and price_field in df.columns:
                s = df[price_field].rename(sym)
                series_list.append(s)

        if not series_list:
            return pd.DataFrame()

        panel = pd.concat(series_list, axis=1).sort_index()
        return panel
