"""
Data Validation and Wilder's Smoothing ATR(14) Computation.
Core mathematical primitives for Layer 1 Swing Detection.
"""

import numpy as np
import pandas as pd


def validate_and_clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validates and cleans OHLCV candlestick data:
    - Normalizes datetime column and sorts chronologically.
    - Removes duplicate timestamps.
    - Enforces OHLC geometry integrity: High >= Low, High >= Open, High >= Close, Low <= Open, Low <= Close.
    - Enforces non-negative prices and volume.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    data = df.copy()

    # Detect trade date column
    date_cols = [c for c in ["TRADE_DATE", "trade_date", "Datetime", "datetime", "Date", "date"] if c in data.columns]
    if date_cols:
        primary_date_col = date_cols[0]
        data[primary_date_col] = pd.to_datetime(data[primary_date_col])
        data = data.sort_values(primary_date_col).drop_duplicates(subset=[primary_date_col], keep="first")
    elif isinstance(data.index, pd.DatetimeIndex):
        data = data.sort_index()[~data.index.duplicated(keep="first")]

    # Normalize column names for validation
    h_col = next((c for c in ["HIGH_PRICE", "High", "high"] if c in data.columns), None)
    l_col = next((c for c in ["LOW_PRICE", "Low", "low"] if c in data.columns), None)
    o_col = next((c for c in ["OPEN_PRICE", "Open", "open"] if c in data.columns), None)
    c_col = next((c for c in ["CLOSE_PRICE", "Close", "close"] if c in data.columns), None)
    v_col = next((c for c in ["VOLUME", "Volume", "volume"] if c in data.columns), None)

    if h_col and l_col and o_col and c_col:
        valid_mask = (
            (data[h_col] >= data[l_col]) &
            (data[h_col] >= data[o_col]) &
            (data[h_col] >= data[c_col]) &
            (data[l_col] <= data[o_col]) &
            (data[l_col] <= data[c_col]) &
            (data[h_col] > 0) &
            (data[l_col] > 0)
        )
        if v_col:
            valid_mask &= (data[v_col] >= 0)
        data = data[valid_mask].reset_index(drop=True)

    return data


def compute_wilder_atr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    """
    Computes Average True Range (ATR) using J. Welles Wilder's smoothing technique:
    TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)
    Initial ATR = SMA(TR, period)
    Subsequent ATR_t = ((period - 1) * ATR_{t-1} + TR_t) / period
    """
    n = len(df)
    if n == 0:
        return np.array([], dtype=float)

    h_col = next((c for c in ["HIGH_PRICE", "High", "high"] if c in df.columns), None)
    l_col = next((c for c in ["LOW_PRICE", "Low", "low"] if c in df.columns), None)
    c_col = next((c for c in ["CLOSE_PRICE", "Close", "close"] if c in df.columns), None)

    if not (h_col and l_col and c_col):
        raise ValueError("DataFrame must contain High, Low, and Close columns to compute ATR.")

    h = df[h_col].values.astype(float)
    l = df[l_col].values.astype(float)
    c = df[c_col].values.astype(float)

    tr = np.zeros(n, dtype=float)
    tr[0] = h[0] - l[0]
    for t in range(1, n):
        tr[t] = max(
            h[t] - l[t],
            abs(h[t] - c[t - 1]),
            abs(l[t] - c[t - 1])
        )

    atr = np.zeros(n, dtype=float)
    for i in range(min(period, n)):
        atr[i] = np.mean(tr[:i + 1])

    for t in range(period, n):
        atr[t] = ((period - 1) * atr[t - 1] + tr[t]) / float(period)

    return atr
