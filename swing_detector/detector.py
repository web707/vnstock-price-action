"""
Layer 1 — Swing Point Detection Engine (Strict ZigZag Alternation & Wilder ATR).
Identifies meaningful Swing High and Swing Low extrema.
Does NOT assign market structure labels (HH, HL, LH, LL) and does NOT import Layer 2.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

from common.models import Swing
from swing_detector.atr import compute_wilder_atr, validate_and_clean_data


@dataclass
class SwingDetectorConfig:
    """Configuration parameters for Layer 1 Swing Detection."""
    swing_left: int = 3
    swing_right: int = 3
    reversal_mult: float = 2.0
    min_reversal_pct: float = 0.005
    atr_period: int = 14
    timeframe: str = "15m"


def detect_swings(
    ohlcv_15m: pd.DataFrame,
    config: Optional[SwingDetectorConfig] = None
) -> List[Swing]:
    """
    Main entry point for Layer 1: Detects swing points on 15m candlestick data.
    
    Guarantees:
    - Zero Lookahead Bias: Confirmed at bar t >= cand_idx + swing_right.
    - Strict Alternation: Peak -> Trough -> Peak -> Trough (100% ZigZag).
    - Dynamic Volatility Adaptation: T_i = max(reversal_mult * ATR_i, 0.5% Price).
    - Candidate Replacement: Higher peaks / lower troughs continuously replace trailing candidates.
    - Structure labels remain None (responsibility of Layer 2 Step A).
    """
    if config is None:
        config = SwingDetectorConfig()

    df = validate_and_clean_data(ohlcv_15m)
    n = len(df)
    if n == 0:
        return []

    h_col = next((c for c in ["HIGH_PRICE", "High", "high"] if c in df.columns), None)
    l_col = next((c for c in ["LOW_PRICE", "Low", "low"] if c in df.columns), None)
    v_col = next((c for c in ["VOLUME", "Volume", "volume"] if c in df.columns), None)
    d_col = next((c for c in ["TRADE_DATE", "trade_date", "Datetime", "datetime", "Date", "date"] if c in df.columns), None)

    highs = df[h_col].values.astype(float)
    lows = df[l_col].values.astype(float)
    volumes = df[v_col].values.astype(float) if v_col else np.ones(n, dtype=float)
    dates = df[d_col].values if d_col else df.index.values

    # 1. Compute Wilder ATR(14)
    atr = compute_wilder_atr(df, period=config.atr_period)

    # 2. Compute 20-bar rolling median volume
    if v_col:
        vol_median_20 = pd.Series(volumes).rolling(window=20, min_periods=1).median().values
    else:
        vol_median_20 = np.ones(n, dtype=float)

    swings: List[Swing] = []
    state = "INIT"
    cand_h_idx = 0
    cand_l_idx = 0

    for t in range(1, n):
        h_t = highs[t]
        l_t = lows[t]

        if state == "INIT":
            if h_t > highs[cand_h_idx]:
                cand_h_idx = t
            if l_t < lows[cand_l_idx]:
                cand_l_idx = t

            thresh_h = max(config.reversal_mult * atr[cand_h_idx], config.min_reversal_pct * highs[cand_h_idx])
            thresh_l = max(config.reversal_mult * atr[cand_l_idx], config.min_reversal_pct * lows[cand_l_idx])

            can_confirm_h = (t >= cand_h_idx + config.swing_right) and (highs[cand_h_idx] - l_t >= thresh_h)
            can_confirm_l = (t >= cand_l_idx + config.swing_right) and (h_t - lows[cand_l_idx] >= thresh_l)

            if can_confirm_h and not can_confirm_l:
                swings.append(_create_swing(
                    stt=len(swings) + 1,
                    index=cand_h_idx,
                    price=highs[cand_h_idx],
                    point_type="HIGH",
                    conf_idx=t,
                    dates=dates,
                    atr_val=atr[cand_h_idx],
                    thresh_val=thresh_h,
                    vol_ratio=volumes[cand_h_idx] / vol_median_20[cand_h_idx] if vol_median_20[cand_h_idx] > 0 else 1.0,
                    timeframe=config.timeframe,
                    prev_swing=None
                ))
                state = "SEEKING_LOW"
                sub_l = lows[cand_h_idx + 1 : t + 1]
                cand_l_idx = cand_h_idx + 1 + int(np.argmin(sub_l))

            elif can_confirm_l and not can_confirm_h:
                swings.append(_create_swing(
                    stt=len(swings) + 1,
                    index=cand_l_idx,
                    price=lows[cand_l_idx],
                    point_type="LOW",
                    conf_idx=t,
                    dates=dates,
                    atr_val=atr[cand_l_idx],
                    thresh_val=thresh_l,
                    vol_ratio=volumes[cand_l_idx] / vol_median_20[cand_l_idx] if vol_median_20[cand_l_idx] > 0 else 1.0,
                    timeframe=config.timeframe,
                    prev_swing=None
                ))
                state = "SEEKING_HIGH"
                sub_h = highs[cand_l_idx + 1 : t + 1]
                cand_h_idx = cand_l_idx + 1 + int(np.argmax(sub_h))

            elif can_confirm_h and can_confirm_l:
                if cand_h_idx <= cand_l_idx:
                    swings.append(_create_swing(
                        stt=len(swings) + 1,
                        index=cand_h_idx,
                        price=highs[cand_h_idx],
                        point_type="HIGH",
                        conf_idx=t,
                        dates=dates,
                        atr_val=atr[cand_h_idx],
                        thresh_val=thresh_h,
                        vol_ratio=volumes[cand_h_idx] / vol_median_20[cand_h_idx] if vol_median_20[cand_h_idx] > 0 else 1.0,
                        timeframe=config.timeframe,
                        prev_swing=None
                    ))
                    state = "SEEKING_LOW"
                    sub_l = lows[cand_h_idx + 1 : t + 1]
                    cand_l_idx = cand_h_idx + 1 + int(np.argmin(sub_l))
                else:
                    swings.append(_create_swing(
                        stt=len(swings) + 1,
                        index=cand_l_idx,
                        price=lows[cand_l_idx],
                        point_type="LOW",
                        conf_idx=t,
                        dates=dates,
                        atr_val=atr[cand_l_idx],
                        thresh_val=thresh_l,
                        vol_ratio=volumes[cand_l_idx] / vol_median_20[cand_l_idx] if vol_median_20[cand_l_idx] > 0 else 1.0,
                        timeframe=config.timeframe,
                        prev_swing=None
                    ))
                    state = "SEEKING_HIGH"
                    sub_h = highs[cand_l_idx + 1 : t + 1]
                    cand_h_idx = cand_l_idx + 1 + int(np.argmax(sub_h))

        elif state == "SEEKING_HIGH":
            # Candidate replacement: higher high updates peak candidate
            if h_t > highs[cand_h_idx]:
                cand_h_idx = t

            thresh_h = max(config.reversal_mult * atr[cand_h_idx], config.min_reversal_pct * highs[cand_h_idx])

            if (t >= cand_h_idx + config.swing_right) and (highs[cand_h_idx] - l_t >= thresh_h):
                prev_swing = swings[-1] if swings else None
                swings.append(_create_swing(
                    stt=len(swings) + 1,
                    index=cand_h_idx,
                    price=highs[cand_h_idx],
                    point_type="HIGH",
                    conf_idx=t,
                    dates=dates,
                    atr_val=atr[cand_h_idx],
                    thresh_val=thresh_h,
                    vol_ratio=volumes[cand_h_idx] / vol_median_20[cand_h_idx] if vol_median_20[cand_h_idx] > 0 else 1.0,
                    timeframe=config.timeframe,
                    prev_swing=prev_swing
                ))
                state = "SEEKING_LOW"
                sub_l = lows[cand_h_idx + 1 : t + 1]
                cand_l_idx = cand_h_idx + 1 + int(np.argmin(sub_l))

        elif state == "SEEKING_LOW":
            # Candidate replacement: lower low updates trough candidate
            if l_t < lows[cand_l_idx]:
                cand_l_idx = t

            thresh_l = max(config.reversal_mult * atr[cand_l_idx], config.min_reversal_pct * lows[cand_l_idx])

            if (t >= cand_l_idx + config.swing_right) and (h_t - lows[cand_l_idx] >= thresh_l):
                prev_swing = swings[-1] if swings else None
                swings.append(_create_swing(
                    stt=len(swings) + 1,
                    index=cand_l_idx,
                    price=lows[cand_l_idx],
                    point_type="LOW",
                    conf_idx=t,
                    dates=dates,
                    atr_val=atr[cand_l_idx],
                    thresh_val=thresh_l,
                    vol_ratio=volumes[cand_l_idx] / vol_median_20[cand_l_idx] if vol_median_20[cand_l_idx] > 0 else 1.0,
                    timeframe=config.timeframe,
                    prev_swing=prev_swing
                ))
                state = "SEEKING_HIGH"
                sub_h = highs[cand_l_idx + 1 : t + 1]
                cand_h_idx = cand_l_idx + 1 + int(np.argmax(sub_h))

    return swings


def _create_swing(
    stt: int,
    index: int,
    price: float,
    point_type: str,
    conf_idx: int,
    dates: np.ndarray,
    atr_val: float,
    thresh_val: float,
    vol_ratio: float,
    timeframe: str,
    prev_swing: Optional[Swing]
) -> Swing:
    """Helper to build a clean Swing object (Layer 1)."""
    pct = ((price - prev_swing.extreme_price) / prev_swing.extreme_price * 100.0) if prev_swing else None
    ext_time_str = str(dates[index])[:19].replace("T", " ")
    conf_time_str = str(dates[conf_idx])[:19].replace("T", " ")

    return Swing(
        swing_id=stt,
        swing_type=point_type,
        extreme_price=float(price),
        extreme_time=ext_time_str,
        confirmed_at=conf_time_str,
        atr_at_extreme=float(atr_val),
        threshold=float(thresh_val),
        source_timeframe=timeframe,
        lag_bars=int(conf_idx - index),
        vol_over_median=round(float(vol_ratio), 2),
        pct_change=round(float(pct), 2) if pct is not None else None,
        index=index,
        confirmed_at_index=conf_idx,
        structure_label=None  # Explicitly None in Layer 1
    )
