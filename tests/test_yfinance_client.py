"""
Tests for YFinanceClient.
Covers Mandatory Test Cases:
- Case 1: Fetching data from a valid ticker.
- Case 2: Handling non-existent / delisted ticker.
"""

from unittest.mock import patch, MagicMock
import pandas as pd
from src.yfinance_client import YFinanceClient


def test_fetch_historical_non_existent_ticker():
    client = YFinanceClient(max_retries=1, request_delay=0.0)
    # yfinance returns empty dataframe or 404 for invalid ticker
    df, err = client.fetch_historical("INVALID_TICKER_XYZ999.VN")
    assert df is None
    assert err is not None
    assert any(term in err for term in ["NO_DATA", "NOT_FOUND", "404"])


def test_fetch_historical_mocked_success():
    client = YFinanceClient(max_retries=1, request_delay=0.0)
    mock_dates = pd.date_range("2026-01-01", periods=3)
    mock_df = pd.DataFrame({
        "Open": [10.0, 11.0, 12.0],
        "High": [12.0, 13.0, 14.0],
        "Low": [9.0, 10.0, 11.0],
        "Close": [11.0, 12.0, 13.0],
        "Adj Close": [11.0, 12.0, 13.0],
        "Volume": [1000, 2000, 3000]
    }, index=mock_dates)

    with patch("yfinance.Ticker") as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = mock_df
        mock_ticker.return_value = mock_instance

        df, err = client.fetch_historical("HPG.VN")
        assert err is None
        assert df is not None
        assert len(df) == 3
        assert "Close" in df.columns


def test_fetch_historical_multiindex_flattening():
    client = YFinanceClient(max_retries=1, request_delay=0.0)
    mock_dates = pd.date_range("2026-01-01", periods=2)
    # Create MultiIndex columns (Price, Ticker)
    cols = pd.MultiIndex.from_tuples([
        ("Open", "HPG.VN"),
        ("High", "HPG.VN"),
        ("Low", "HPG.VN"),
        ("Close", "HPG.VN"),
        ("Adj Close", "HPG.VN"),
        ("Volume", "HPG.VN")
    ])
    mock_df = pd.DataFrame([
        [10.0, 12.0, 9.0, 11.0, 11.0, 1000],
        [11.0, 13.0, 10.0, 12.0, 12.0, 2000]
    ], index=mock_dates, columns=cols)

    with patch("yfinance.Ticker") as mock_ticker:
        mock_instance = MagicMock()
        mock_instance.history.return_value = mock_df
        mock_ticker.return_value = mock_instance

        df, err = client.fetch_historical("HPG.VN")
        assert err is None
        assert not isinstance(df.columns, pd.MultiIndex)
        assert set(df.columns) == {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
