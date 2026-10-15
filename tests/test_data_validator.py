"""
Unit tests for DataValidator.
Covers Mandatory Test Cases:
- Case 3: Handling empty, NaN, and invalid data.
- Case 12: Integrity of price and volume fields (OHLC bounds, non-negative volume).
"""

from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
from src.data_validator import DataValidator


def test_validator_clean_data():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    df = pd.DataFrame({
        "Open": [50.0, 51.0, 52.0, 53.0, 54.0],
        "High": [55.0, 56.0, 57.0, 58.0, 59.0],
        "Low": [49.0, 50.0, 51.0, 52.0, 53.0],
        "Close": [52.0, 53.0, 54.0, 55.0, 56.0],
        "Volume": [1000, 2000, 3000, 4000, 5000]
    }, index=dates)

    valid_df, rejected_df, metrics = DataValidator.validate_dataframe(df, "HPG")
    assert len(valid_df) == 5
    assert len(rejected_df) == 0
    assert metrics["rejected"] == 0
    assert (valid_df["QUALITY_STATUS"] == "VALID").all()


def test_validator_reject_nan_prices():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame({
        "Open": [50.0, np.nan, 52.0],
        "High": [55.0, 56.0, 57.0],
        "Low": [49.0, 50.0, 51.0],
        "Close": [52.0, 53.0, 54.0],
        "Volume": [1000, 2000, 3000]
    }, index=dates)

    valid_df, rejected_df, metrics = DataValidator.validate_dataframe(df, "HPG")
    assert len(valid_df) == 2
    assert len(rejected_df) == 1
    assert "nan_prices" in metrics["reasons"]


def test_validator_reject_negative_and_zero_prices():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame({
        "Open": [50.0, -10.0, 52.0],
        "High": [55.0, 56.0, 57.0],
        "Low": [49.0, 50.0, 51.0],
        "Close": [52.0, 53.0, 0.0],  # 0 price is invalid
        "Volume": [1000, 2000, 3000]
    }, index=dates)

    valid_df, rejected_df, metrics = DataValidator.validate_dataframe(df, "HPG")
    assert len(valid_df) == 1
    assert len(rejected_df) == 2
    assert "non_positive_prices" in metrics["reasons"]


def test_validator_reject_invalid_ohlc_geometry():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame({
        "Open": [50.0, 60.0, 50.0],
        "High": [45.0, 55.0, 65.0],  # Row 0: High < Open! (45 < 50)
        "Low": [40.0, 58.0, 40.0],   # Row 1: Low > High! (58 > 55)
        "Close": [42.0, 52.0, 52.0],
        "Volume": [1000, 2000, 3000]
    }, index=dates)

    valid_df, rejected_df, metrics = DataValidator.validate_dataframe(df, "HPG")
    assert len(valid_df) == 1  # Only row 2 is valid
    assert len(rejected_df) == 2
    assert "invalid_ohlc_geometry" in metrics["reasons"]


def test_validator_reject_future_dates():
    future_date = datetime.now(timezone.utc) + timedelta(days=5)
    past_date = datetime.now(timezone.utc) - timedelta(days=5)
    dates = pd.DatetimeIndex([past_date, future_date])

    df = pd.DataFrame({
        "Open": [50.0, 50.0],
        "High": [55.0, 55.0],
        "Low": [45.0, 45.0],
        "Close": [52.0, 52.0],
        "Volume": [1000, 1000]
    }, index=dates)

    valid_df, rejected_df, metrics = DataValidator.validate_dataframe(df, "HPG")
    assert len(valid_df) == 1
    assert len(rejected_df) == 1
    assert "future_dates" in metrics["reasons"]


def test_validator_zero_volume_warning():
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    df = pd.DataFrame({
        "Open": [50.0, 51.0],
        "High": [55.0, 56.0],
        "Low": [45.0, 46.0],
        "Close": [52.0, 53.0],
        "Volume": [1000, 0]  # Zero volume row
    }, index=dates)

    valid_df, rejected_df, metrics = DataValidator.validate_dataframe(df, "HPG")
    assert len(valid_df) == 2
    assert len(rejected_df) == 0
    assert metrics["warnings"] == 1
    assert valid_df.loc[dates[1], "QUALITY_STATUS"] == "WARNING_ZERO_VOLUME"


def test_validator_empty_dataframe():
    valid_df, rejected_df, metrics = DataValidator.validate_dataframe(pd.DataFrame(), "HPG")
    assert valid_df.empty
    assert rejected_df.empty
    assert metrics["total"] == 0
