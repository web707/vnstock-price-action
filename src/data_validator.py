"""
Data Quality Validator Module for Vietnam Stock Data.
Performs thorough domain-specific sanity checks on OHLCV market data to ensure
clean, reliable data for backtesting without future look-ahead bias or synthetic distortions.
"""

from typing import Dict, Tuple, Any
from datetime import datetime, timezone
import pandas as pd
import numpy as np


class DataValidator:
    """Validates raw OHLCV market data against financial domain rules."""

    @staticmethod
    def validate_dataframe(df: pd.DataFrame, symbol: str) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
        """
        Validate a raw price DataFrame from yfinance.

        Returns:
            Tuple[valid_df, rejected_df, summary_metrics]:
            - valid_df: records that passed core integrity checks with assigned QUALITY_STATUS.
            - rejected_df: records discarded due to fundamental invalidity (NaN prices, negative prices, future dates).
            - summary_metrics: dict containing counts of passed, rejected, and warned records.
        """
        if df is None or df.empty:
            return (
                pd.DataFrame(),
                pd.DataFrame(),
                {"total": 0, "valid": 0, "rejected": 0, "warnings": 0, "reasons": {}}
            )

        data = df.copy()
        rejection_reasons = {}

        # 1. Ensure index is DatetimeIndex
        if not isinstance(data.index, pd.DatetimeIndex):
            try:
                data.index = pd.to_datetime(data.index)
            except Exception as e:
                return (
                    pd.DataFrame(),
                    data,
                    {"total": len(data), "valid": 0, "rejected": len(data), "warnings": 0, "reasons": {"invalid_date_index": len(data)}}
                )

        # 2. Check for duplicate dates in index
        dup_mask = data.index.duplicated(keep="last")
        if dup_mask.any():
            dup_count = int(dup_mask.sum())
            rejection_reasons["duplicate_trade_dates"] = dup_count
            data = data[~dup_mask].copy()

        # 3. Check for future dates
        now_utc = datetime.now(timezone.utc)
        # Convert index to UTC for safe comparison if timezone-aware
        if data.index.tz is not None:
            future_mask = data.index > now_utc
        else:
            future_mask = data.index > now_utc.replace(tzinfo=None)

        if future_mask.any():
            future_count = int(future_mask.sum())
            rejection_reasons["future_dates"] = future_count

        # 4. Check for missing / NaN / non-numeric prices
        price_cols = ["Open", "High", "Low", "Close"]
        nan_price_mask = data[price_cols].isna().any(axis=1)
        if nan_price_mask.any():
            nan_count = int(nan_price_mask.sum())
            rejection_reasons["nan_prices"] = nan_count

        # 5. Check for non-positive prices (Price <= 0 is strictly invalid in active trading)
        non_positive_mask = (data[price_cols] <= 0).any(axis=1)
        if non_positive_mask.any():
            np_count = int(non_positive_mask.sum())
            rejection_reasons["non_positive_prices"] = np_count

        # 6. Check OHLC relative geometry:
        # High must be >= Low, High >= Open, High >= Close
        # Low must be <= Open, Low <= Close
        geom_invalid_mask = (
            (data["High"] < data["Low"]) |
            (data["High"] < data["Open"]) |
            (data["High"] < data["Close"]) |
            (data["Low"] > data["Open"]) |
            (data["Low"] > data["Close"])
        )
        if geom_invalid_mask.any():
            geom_count = int(geom_invalid_mask.sum())
            rejection_reasons["invalid_ohlc_geometry"] = geom_count

        # 7. Check Volume: Volume must be non-negative
        neg_volume_mask = data["Volume"].isna() | (data["Volume"] < 0)
        if neg_volume_mask.any():
            nv_count = int(neg_volume_mask.sum())
            rejection_reasons["invalid_volume"] = nv_count

        # Combine rejection criteria:
        # We reject rows with future dates, NaN prices, non-positive prices, or invalid OHLC geometry
        total_reject_mask = future_mask | nan_price_mask | non_positive_mask | geom_invalid_mask | neg_volume_mask

        rejected_df = data[total_reject_mask].copy()
        valid_df = data[~total_reject_mask].copy()

        # 8. Check for warnings on valid records (e.g. Zero volume, or abnormal daily price spike)
        warnings_count = 0
        if not valid_df.empty:
            valid_df["QUALITY_STATUS"] = "VALID"

            # Check zero volume warning (trading day with zero recorded volume)
            zero_vol_mask = valid_df["Volume"] == 0
            if zero_vol_mask.any():
                valid_df.loc[zero_vol_mask, "QUALITY_STATUS"] = "WARNING_ZERO_VOLUME"
                warnings_count += int(zero_vol_mask.sum())

            # Check abnormal return spike (> 100% intraday or vs previous close, common in split adjustments)
            intraday_return = (valid_df["High"] - valid_df["Low"]) / valid_df["Low"]
            spike_mask = intraday_return > 1.0  # > 100% intraday swing
            if spike_mask.any():
                valid_df.loc[spike_mask & (valid_df["QUALITY_STATUS"] == "VALID"), "QUALITY_STATUS"] = "WARNING_PRICE_SPIKE"
                warnings_count += int(spike_mask.sum())

        metrics = {
            "total": len(df),
            "valid": len(valid_df),
            "rejected": len(rejected_df),
            "warnings": warnings_count,
            "reasons": rejection_reasons
        }

        return valid_df, rejected_df, metrics
