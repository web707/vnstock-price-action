"""Regression tests for 1d source being mislabeled as 15m."""
from types import SimpleNamespace
import pandas as pd
import pytest
from src.candle_timeframe import require_15m_candles


def candles(freq="15min"):
    return pd.DataFrame({"TRADE_DATE": pd.date_range("2026-10-01 09:15", periods=12, freq=freq)})


def test_guard_rejects_daily_data_as_15m():
    with pytest.raises(ValueError, match="15m.*trung vị"):
        require_15m_candles(candles("1D"), "15m")


def test_guard_accepts_intraday():
    require_15m_candles(candles(), "15m")


def test_daily_db_not_restricted_by_15m_guard():
    require_15m_candles(candles("1D"), "1d")


def test_inspector_does_not_fallback(monkeypatch):
    pytest.importorskip("yfinance")
    pytest.importorskip("oracledb")
    import inspect_swings
    monkeypatch.setattr(inspect_swings, "YFinanceClient", lambda **kwargs: SimpleNamespace(fetch_intraday=lambda *a, **kw: (None, "timeout")))
    monkeypatch.setattr(inspect_swings, "get_repository", lambda **kwargs: pytest.fail("unexpected DB fallback"))
    with pytest.raises(RuntimeError, match="timeout"):
        inspect_swings.load_price_data("HPG", "15m", "api")
    with pytest.raises(ValueError, match="1d"):
        inspect_swings.load_price_data("HPG", "15m", "db")


def test_main_does_not_fallback(monkeypatch):
    pytest.importorskip("yfinance")
    pytest.importorskip("oracledb")
    import main
    monkeypatch.setattr(main, "YFinanceClient", lambda **kwargs: SimpleNamespace(fetch_intraday=lambda *a, **kw: (None, "timeout")))
    monkeypatch.setattr(main, "get_repository", lambda **kwargs: pytest.fail("unexpected DB fallback"))
    with pytest.raises(RuntimeError, match="timeout"):
        main.cmd_layer2(SimpleNamespace(symbol="HPG", timeframe="15m", source="api"))
    with pytest.raises(ValueError, match="1d"):
        main.cmd_layer2(SimpleNamespace(symbol="HPG", timeframe="15m", source="db"))
