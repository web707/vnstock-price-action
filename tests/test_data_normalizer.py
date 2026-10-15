"""
Unit tests for DataNormalizer.
Covers Mandatory Test Cases:
- Case 4: Normalizing trade dates (timezone stripped, clean date objects).
- Case 5: Handling column differences across yfinance versions (fallback Adj Close).
"""

from datetime import date
import pandas as pd
import pytz
from src.data_normalizer import DataNormalizer


def test_normalize_trade_dates_with_timezone():
    # Simulate yfinance Asia/Bangkok (+07:00) DatetimeIndex
    tz = pytz.timezone("Asia/Bangkok")
    dates = pd.date_range("2026-02-01", periods=3, tz=tz)

    df = pd.DataFrame({
        "Open": [10.12346, 11.0, 12.0],
        "High": [10.5, 11.5, 12.5],
        "Low": [9.5, 10.5, 11.5],
        "Close": [10.2, 11.2, 12.2],
        "Adj Close": [10.0, 11.0, 12.0],
        "Volume": [1000, 2000, 3000],
        "QUALITY_STATUS": ["VALID", "VALID", "VALID"]
    }, index=dates)

    norm_df = DataNormalizer.normalize_prices_dataframe(df, "VNM")

    assert len(norm_df) == 3
    # Verify date is standard python date without timezone distortion
    assert norm_df["TRADE_DATE"].iloc[0] == date(2026, 2, 1)
    assert norm_df["TRADE_DATE"].iloc[1] == date(2026, 2, 2)
    assert norm_df["TRADE_DATE"].iloc[2] == date(2026, 2, 3)

    # Verify rounding to 4 decimals
    assert norm_df["OPEN_PRICE"].iloc[0] == 10.1235
    assert norm_df["VOLUME"].iloc[0] == 1000
    assert norm_df["SYMBOL"].iloc[0] == "VNM"


def test_normalize_missing_adj_close_fallback():
    # If yfinance doesn't provide Adj Close
    dates = pd.date_range("2026-03-01", periods=2)
    df = pd.DataFrame({
        "Open": [20.0, 21.0],
        "High": [22.0, 23.0],
        "Low": [19.0, 20.0],
        "Close": [20.5, 21.5],
        "Volume": [5000, 6000],
        "QUALITY_STATUS": ["VALID", "VALID"]
    }, index=dates)

    norm_df = DataNormalizer.normalize_prices_dataframe(df, "SSI")

    assert "ADJ_CLOSE" in norm_df.columns
    # Falls back to CLOSE_PRICE
    assert (norm_df["ADJ_CLOSE"] == norm_df["CLOSE_PRICE"]).all()


def test_corporate_events_normalization():
    tz = pytz.timezone("Asia/Bangkok")
    div_idx = pd.DatetimeIndex([pd.Timestamp("2026-05-15", tz=tz)])
    split_idx = pd.DatetimeIndex([pd.Timestamp("2026-06-20", tz=tz)])

    events = {
        "dividends": pd.Series([1500.0], index=div_idx),
        "splits": pd.Series([1.2], index=split_idx)
    }

    records = DataNormalizer.normalize_corporate_events(events, "HPG")
    assert len(records) == 2

    div_rec = next(r for r in records if r["EVENT_TYPE"] == "DIVIDEND")
    assert div_rec["SYMBOL"] == "HPG"
    assert div_rec["EVENT_DATE"] == date(2026, 5, 15)
    assert div_rec["EVENT_VALUE"] == 1500.0

    split_rec = next(r for r in records if r["EVENT_TYPE"] == "SPLIT")
    assert split_rec["SYMBOL"] == "HPG"
    assert split_rec["EVENT_DATE"] == date(2026, 6, 20)
    assert split_rec["EVENT_VALUE"] == 1.2
