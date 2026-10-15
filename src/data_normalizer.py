"""
Data Normalizer Module for Vietnam Stock Data.
Converts raw validated market data into standardized database-ready records
aligned with Oracle schema types and constraints.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, timezone
import pandas as pd
import numpy as np


class DataNormalizer:
    """Normalizes market data and corporate events into standardized Oracle schema structures."""

    @staticmethod
    def normalize_prices_dataframe(
        df: pd.DataFrame,
        symbol: str,
        source: str = "yfinance",
        fetched_at: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Transform a validated yfinance DataFrame into standard Oracle schema columns.

        Returns DataFrame with columns:
        [SYMBOL, TRADE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, ADJ_CLOSE, VOLUME, QUALITY_STATUS, SOURCE, FETCHED_AT]
        """
        if df is None or df.empty:
            return pd.DataFrame(columns=[
                "SYMBOL", "TRADE_DATE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
                "CLOSE_PRICE", "ADJ_CLOSE", "VOLUME", "QUALITY_STATUS", "SOURCE", "FETCHED_AT"
            ])

        data = df.copy()
        now_ts = fetched_at or datetime.now(timezone.utc)

        # 1. Normalize dates to standard date object (YYYY-MM-DD, no timezone)
        if isinstance(data.index, pd.DatetimeIndex):
            # Convert to date objects
            trade_dates = [ts.date() for ts in data.index]
        else:
            trade_dates = [pd.to_datetime(d).date() for d in data.index]

        # 2. Extract values and handle precision
        opens = np.round(data["Open"].astype(float).values, 4)
        highs = np.round(data["High"].astype(float).values, 4)
        lows = np.round(data["Low"].astype(float).values, 4)
        closes = np.round(data["Close"].astype(float).values, 4)

        if "Adj Close" in data.columns and not data["Adj Close"].isna().all():
            adj_closes = np.round(data["Adj Close"].astype(float).values, 4)
        else:
            adj_closes = closes.copy()

        volumes = data["Volume"].fillna(0).astype("int64").values

        quality_statuses = data.get("QUALITY_STATUS", pd.Series(["VALID"] * len(data))).values

        norm_df = pd.DataFrame({
            "SYMBOL": symbol,
            "TRADE_DATE": trade_dates,
            "OPEN_PRICE": opens,
            "HIGH_PRICE": highs,
            "LOW_PRICE": lows,
            "CLOSE_PRICE": closes,
            "ADJ_CLOSE": adj_closes,
            "VOLUME": volumes,
            "QUALITY_STATUS": quality_statuses,
            "SOURCE": source,
            "FETCHED_AT": now_ts
        })

        # Ensure sorted chronologically and drop duplicate dates if any remain
        norm_df = norm_df.sort_values("TRADE_DATE").drop_duplicates(subset=["SYMBOL", "TRADE_DATE"], keep="last")
        return norm_df

    @staticmethod
    def to_oracle_price_tuples(df: pd.DataFrame) -> List[tuple]:
        """Convert normalized DataFrame into list of tuples for oracledb cursor.executemany."""
        if df.empty:
            return []
        records = []
        for _, row in df.iterrows():
            records.append((
                row["SYMBOL"],
                row["TRADE_DATE"],
                float(row["OPEN_PRICE"]),
                float(row["HIGH_PRICE"]),
                float(row["LOW_PRICE"]),
                float(row["CLOSE_PRICE"]),
                float(row["ADJ_CLOSE"]) if pd.notna(row["ADJ_CLOSE"]) else float(row["CLOSE_PRICE"]),
                int(row["VOLUME"]),
                str(row["QUALITY_STATUS"]),
                str(row["SOURCE"]),
                row["FETCHED_AT"]
            ))
        return records

    @staticmethod
    def normalize_corporate_events(
        events_dict: Dict[str, pd.Series],
        symbol: str,
        source: str = "yfinance",
        fetched_at: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Normalize dividends and stock splits into standard event records.
        """
        now_ts = fetched_at or datetime.now(timezone.utc)
        records = []

        # Process dividends
        dividends = events_dict.get("dividends")
        if dividends is not None and not dividends.empty:
            for idx, val in dividends.items():
                if val > 0:
                    event_date = idx.date() if hasattr(idx, "date") else pd.to_datetime(idx).date()
                    records.append({
                        "SYMBOL": symbol,
                        "EVENT_DATE": event_date,
                        "EVENT_TYPE": "DIVIDEND",
                        "EVENT_VALUE": round(float(val), 4),
                        "SOURCE": source,
                        "FETCHED_AT": now_ts
                    })

        # Process splits
        splits = events_dict.get("splits")
        if splits is not None and not splits.empty:
            for idx, val in splits.items():
                if val > 0:
                    event_date = idx.date() if hasattr(idx, "date") else pd.to_datetime(idx).date()
                    records.append({
                        "SYMBOL": symbol,
                        "EVENT_DATE": event_date,
                        "EVENT_TYPE": "SPLIT",
                        "EVENT_VALUE": round(float(val), 4),
                        "SOURCE": source,
                        "FETCHED_AT": now_ts
                    })

        return records
