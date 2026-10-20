"""Validate declared candle timeframe at legacy CLI boundaries."""
import pandas as pd


def require_15m_candles(df: pd.DataFrame, timeframe: str) -> None:
    if timeframe != "15m" or df is None or df.empty:
        return
    col = next((c for c in ("TRADE_DATE", "trade_date", "Datetime", "datetime", "Date", "date") if c in df.columns), None)
    times = pd.to_datetime(df[col]) if col else (df.index if isinstance(df.index, pd.DatetimeIndex) else None)
    if times is None or len(times) < 2:
        raise ValueError("Không đủ timestamp để xác minh nến 15m")
    delta = pd.Series(times).sort_values().diff().dropna().dt.total_seconds().div(60)
    actual = float(delta.median())
    if not (14 <= actual <= 16):
        raise ValueError(f"Yêu cầu nến 15m nhưng dữ liệu thực tế có khoảng cách trung vị {actual:g} phút")
