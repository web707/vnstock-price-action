"""
Market Structure & Break of Structure (BOS) Module.
Implements the 'Phát hiện điểm Swing (Swing Point Detection)' specification:
1. Data Quality: OHLC geometric validation, chronological ordering, deduplication.
2. ATR(14) with Wilder's Smoothing: TR = max(H-L, |H-C_prev|, |L-C_prev|), ATR_t = (13*ATR_{t-1} + TR_t)/14.
3. 3/3 Pivot Candidate Detection: 3 bars left, 3 bars right confirmation.
4. Dynamic Reversal Threshold: T_i = max(mult * ATR_i, 0.005 * P_i) fixed at candidate appearance.
5. Strict ZigZag Alternation State Machine: Trough -> Peak -> Trough -> Peak with candidate replacement on new extremes.
6. Minimum Swing Distance: Configurable bar distance between consecutive swings.
7. Volume & Market Structure: 20-period median volume ranking and HH/HL/LH/LL classification.
8. Anti-Lookahead Dual Timestamps: Explicit Timestamp of Extreme (index) and Timestamp of Confirmation (confirmed_at_index).
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import date
import pandas as pd
import numpy as np


@dataclass
class SwingPoint:
    index: int
    trade_date: Any
    price: float
    point_type: str  # 'HIGH' or 'LOW'
    confirmed_at_index: int
    confirmed_date: Optional[Any] = None
    atr_at_candidate: Optional[float] = None
    reversal_threshold: Optional[float] = None
    structure_type: Optional[str] = None  # 'HH', 'LH', 'EH', 'HL', 'LL', 'EL'
    volume: Optional[float] = None
    volume_median_20: Optional[float] = None
    volume_ratio: Optional[float] = None
    bars_since_prev_swing: Optional[int] = None


@dataclass
class StructureBreak:
    break_index: int
    break_date: Any
    direction: str  # 'BULLISH' or 'BEARISH'
    broken_swing: SwingPoint
    anchor_swing: SwingPoint
    range_low: float
    range_high: float
    break_price: float


def validate_and_clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validates and cleans input OHLCV data according to Section 1:
    - Sorts chronologically
    - Removes duplicate timestamps
    - Validates OHLC geometry: High >= Low, High >= Open/Close, Low <= Open/Close
    - Ensures Volume >= 0
    - Drops invalid / NaN price records
    """
    if df.empty:
        return df.copy()

    data = df.copy()

    # Determine datetime column or index
    date_col = None
    for candidate in ["TRADE_DATE", "trade_date", "Datetime", "datetime", "Date", "date"]:
        if candidate in data.columns:
            date_col = candidate
            break

    if date_col is not None:
        data[date_col] = pd.to_datetime(data[date_col])
        data = data.sort_values(by=date_col).drop_duplicates(subset=[date_col]).reset_index(drop=True)
    elif isinstance(data.index, pd.DatetimeIndex):
        data = data.sort_index()[~data.index.duplicated(keep="first")]

    # Normalize column names for validation
    h_col = "HIGH_PRICE" if "HIGH_PRICE" in data.columns else ("High" if "High" in data.columns else None)
    l_col = "LOW_PRICE" if "LOW_PRICE" in data.columns else ("Low" if "Low" in data.columns else None)
    o_col = "OPEN_PRICE" if "OPEN_PRICE" in data.columns else ("Open" if "Open" in data.columns else None)
    c_col = "CLOSE_PRICE" if "CLOSE_PRICE" in data.columns else ("Close" if "Close" in data.columns else None)
    v_col = "VOLUME" if "VOLUME" in data.columns else ("Volume" if "Volume" in data.columns else None)

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
    Computes Average True Range (ATR) using J. Welles Wilder's smoothing technique (Section 2):
    TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)
    Initial ATR = SMA(TR, period)
    Subsequent ATR_t = ((period - 1) * ATR_{t-1} + TR_t) / period
    """
    n = len(df)
    if n == 0:
        return np.array([], dtype=float)

    h_col = "HIGH_PRICE" if "HIGH_PRICE" in df.columns else ("High" if "High" in df.columns else None)
    l_col = "LOW_PRICE" if "LOW_PRICE" in df.columns else ("Low" if "Low" in df.columns else None)
    c_col = "CLOSE_PRICE" if "CLOSE_PRICE" in df.columns else ("Close" if "Close" in df.columns else None)

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


class MarketStructureTracker:
    """
    Identifies market structure swings and tracks consecutive structure breaks (BOS).
    Strictly causal: Bar T only observes swings confirmed at or before bar T.
    
    Supports:
    - 'zigzag': Section 1-9 specification with Wilder ATR(14) dynamic threshold,
      3/3 pivot confirmation, and ZigZag candidate replacement state machine.
    - 'pivot': Simple local extrema window (legacy compatibility).
    """

    def __init__(
        self,
        swing_left: int = 3,
        swing_right: int = 3,
        break_type: str = "close",  # 'close' or 'wick'
        atr_period: int = 14,
        reversal_mult: float = 2.0,
        min_reversal_pct: float = 0.005,
        min_swing_distance: int = 0,
        method: str = "zigzag"
    ):
        self.swing_left = swing_left
        self.swing_right = swing_right
        self.break_type = break_type
        self.atr_period = atr_period
        self.reversal_mult = reversal_mult
        self.min_reversal_pct = min_reversal_pct
        self.min_swing_distance = min_swing_distance
        self.method = method

    def detect_swings(
        self,
        df: pd.DataFrame,
        method: Optional[str] = None
    ) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Identify swing highs and swing lows without lookahead bias.
        Dispatches to 'zigzag' or 'pivot' based on configuration.
        """
        active_method = method or self.method
        if active_method == "zigzag":
            return self.detect_swings_zigzag(df)
        else:
            return self.detect_swings_pivot(df)

    def detect_swings_pivot(self, df: pd.DataFrame) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Identify swing highs and swing lows using fixed local extrema window.
        Swing at bar k is confirmed at bar k + swing_right.
        """
        n = len(df)
        h_col = "HIGH_PRICE" if "HIGH_PRICE" in df.columns else ("High" if "High" in df.columns else None)
        l_col = "LOW_PRICE" if "LOW_PRICE" in df.columns else ("Low" if "Low" in df.columns else None)
        dates_col = "TRADE_DATE" if "TRADE_DATE" in df.columns else ("trade_date" if "trade_date" in df.columns else None)

        highs = df[h_col].values
        lows = df[l_col].values
        dates = df[dates_col].values if dates_col else df.index.values

        swing_highs: List[SwingPoint] = []
        swing_lows: List[SwingPoint] = []

        for k in range(self.swing_left, n - self.swing_right):
            # Check swing high at k
            window_high = highs[k - self.swing_left : k + self.swing_right + 1]
            if highs[k] == np.max(window_high) and np.sum(window_high == highs[k]) == 1:
                confirmed_idx = k + self.swing_right
                swing_highs.append(SwingPoint(
                    index=k,
                    trade_date=dates[k],
                    price=float(highs[k]),
                    point_type="HIGH",
                    confirmed_at_index=confirmed_idx,
                    confirmed_date=dates[confirmed_idx]
                ))

            # Check swing low at k
            window_low = lows[k - self.swing_left : k + self.swing_right + 1]
            if lows[k] == np.min(window_low) and np.sum(window_low == lows[k]) == 1:
                confirmed_idx = k + self.swing_right
                swing_lows.append(SwingPoint(
                    index=k,
                    trade_date=dates[k],
                    price=float(lows[k]),
                    point_type="LOW",
                    confirmed_at_index=confirmed_idx,
                    confirmed_date=dates[confirmed_idx]
                ))

        return swing_highs, swing_lows

    def detect_swings_zigzag(self, df: pd.DataFrame) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Identifies Swing Highs and Lows using the dynamic Wilder ATR(14) Reversal Threshold
        and strict ZigZag Alternation State Machine (Sections 1-9).
        
        Guarantees:
        - Strict Alternation: Peak -> Trough -> Peak -> Trough.
        - Dynamic Volatility Adaptation: T_i = max(reversal_mult * ATR_i, min_pct * P_i).
        - Candidate Replacement: Higher highs / lower lows continuously replace trailing candidate.
        - Zero Lookahead Bias: Confirmed only after swing_right bars AND threshold breach.
        - Structure (HH/HL/LH/LL) and Volume (20-median) classification.
        """
        n = len(df)
        if n == 0:
            return [], []

        h_col = "HIGH_PRICE" if "HIGH_PRICE" in df.columns else ("High" if "High" in df.columns else None)
        l_col = "LOW_PRICE" if "LOW_PRICE" in df.columns else ("Low" if "Low" in df.columns else None)
        v_col = "VOLUME" if "VOLUME" in df.columns else ("Volume" if "Volume" in df.columns else None)
        dates_col = "TRADE_DATE" if "TRADE_DATE" in df.columns else ("trade_date" if "trade_date" in df.columns else None)

        highs = df[h_col].values.astype(float)
        lows = df[l_col].values.astype(float)
        volumes = df[v_col].values.astype(float) if v_col else np.ones(n, dtype=float)
        dates = df[dates_col].values if dates_col else df.index.values

        # 1. Compute Wilder ATR(14)
        atr = compute_wilder_atr(df, period=self.atr_period)

        # 2. Compute 20-bar rolling median volume
        if v_col:
            vol_median_20 = pd.Series(volumes).rolling(window=20, min_periods=1).median().values
        else:
            vol_median_20 = np.ones(n, dtype=float)

        swing_highs: List[SwingPoint] = []
        swing_lows: List[SwingPoint] = []
        all_swings: List[SwingPoint] = []

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

                thresh_h = max(self.reversal_mult * atr[cand_h_idx], self.min_reversal_pct * highs[cand_h_idx])
                thresh_l = max(self.reversal_mult * atr[cand_l_idx], self.min_reversal_pct * lows[cand_l_idx])

                can_confirm_h = (t >= cand_h_idx + self.swing_right) and (highs[cand_h_idx] - l_t >= thresh_h)
                can_confirm_l = (t >= cand_l_idx + self.swing_right) and (h_t - lows[cand_l_idx] >= thresh_l)

                if can_confirm_h and not can_confirm_l:
                    sh = self._create_swing_point(
                        index=cand_h_idx,
                        price=highs[cand_h_idx],
                        point_type="HIGH",
                        conf_idx=t,
                        dates=dates,
                        atr_val=atr[cand_h_idx],
                        thresh_val=thresh_h,
                        volume=volumes[cand_h_idx],
                        vol_median=vol_median_20[cand_h_idx],
                        prev_same_type=None,
                        last_swing=None
                    )
                    swing_highs.append(sh)
                    all_swings.append(sh)
                    state = "SEEKING_LOW"
                    # Initialize candidate low as minimum low from peak to current bar t
                    sub_l = lows[cand_h_idx + 1 : t + 1]
                    cand_l_idx = cand_h_idx + 1 + int(np.argmin(sub_l))

                elif can_confirm_l and not can_confirm_h:
                    sl = self._create_swing_point(
                        index=cand_l_idx,
                        price=lows[cand_l_idx],
                        point_type="LOW",
                        conf_idx=t,
                        dates=dates,
                        atr_val=atr[cand_l_idx],
                        thresh_val=thresh_l,
                        volume=volumes[cand_l_idx],
                        vol_median=vol_median_20[cand_l_idx],
                        prev_same_type=None,
                        last_swing=None
                    )
                    swing_lows.append(sl)
                    all_swings.append(sl)
                    state = "SEEKING_HIGH"
                    # Initialize candidate high as maximum high from trough to current bar t
                    sub_h = highs[cand_l_idx + 1 : t + 1]
                    cand_h_idx = cand_l_idx + 1 + int(np.argmax(sub_h))

                elif can_confirm_h and can_confirm_l:
                    # Rare tie-breaker: prioritize the candidate that occurred earlier
                    if cand_h_idx <= cand_l_idx:
                        sh = self._create_swing_point(
                            index=cand_h_idx, price=highs[cand_h_idx], point_type="HIGH",
                            conf_idx=t, dates=dates, atr_val=atr[cand_h_idx], thresh_val=thresh_h,
                            volume=volumes[cand_h_idx], vol_median=vol_median_20[cand_h_idx],
                            prev_same_type=None, last_swing=None
                        )
                        swing_highs.append(sh)
                        all_swings.append(sh)
                        state = "SEEKING_LOW"
                        sub_l = lows[cand_h_idx + 1 : t + 1]
                        cand_l_idx = cand_h_idx + 1 + int(np.argmin(sub_l))
                    else:
                        sl = self._create_swing_point(
                            index=cand_l_idx, price=lows[cand_l_idx], point_type="LOW",
                            conf_idx=t, dates=dates, atr_val=atr[cand_l_idx], thresh_val=thresh_l,
                            volume=volumes[cand_l_idx], vol_median=vol_median_20[cand_l_idx],
                            prev_same_type=None, last_swing=None
                        )
                        swing_lows.append(sl)
                        all_swings.append(sl)
                        state = "SEEKING_HIGH"
                        sub_h = highs[cand_l_idx + 1 : t + 1]
                        cand_h_idx = cand_l_idx + 1 + int(np.argmax(sub_h))

            elif state == "SEEKING_HIGH":
                # Continuous candidate replacement: if higher high found, update peak candidate
                if h_t > highs[cand_h_idx]:
                    cand_h_idx = t

                thresh_h = max(self.reversal_mult * atr[cand_h_idx], self.min_reversal_pct * highs[cand_h_idx])

                # Check confirmation: 3 bars to right have closed AND drop >= threshold
                if (t >= cand_h_idx + self.swing_right) and (highs[cand_h_idx] - l_t >= thresh_h):
                    # Check optional minimum distance
                    prev_swing = all_swings[-1] if all_swings else None
                    if self.min_swing_distance > 0 and prev_swing and (cand_h_idx - prev_swing.index < self.min_swing_distance):
                        continue

                    prev_high = swing_highs[-1] if swing_highs else None
                    sh = self._create_swing_point(
                        index=cand_h_idx,
                        price=highs[cand_h_idx],
                        point_type="HIGH",
                        conf_idx=t,
                        dates=dates,
                        atr_val=atr[cand_h_idx],
                        thresh_val=thresh_h,
                        volume=volumes[cand_h_idx],
                        vol_median=vol_median_20[cand_h_idx],
                        prev_same_type=prev_high,
                        last_swing=prev_swing
                    )
                    swing_highs.append(sh)
                    all_swings.append(sh)
                    state = "SEEKING_LOW"

                    # Initialize candidate low from peak to bar t
                    sub_l = lows[cand_h_idx + 1 : t + 1]
                    cand_l_idx = cand_h_idx + 1 + int(np.argmin(sub_l))

            elif state == "SEEKING_LOW":
                # Continuous candidate replacement: if lower low found, update trough candidate
                if l_t < lows[cand_l_idx]:
                    cand_l_idx = t

                thresh_l = max(self.reversal_mult * atr[cand_l_idx], self.min_reversal_pct * lows[cand_l_idx])

                # Check confirmation: 3 bars to right have closed AND rally >= threshold
                if (t >= cand_l_idx + self.swing_right) and (h_t - lows[cand_l_idx] >= thresh_l):
                    # Check optional minimum distance
                    prev_swing = all_swings[-1] if all_swings else None
                    if self.min_swing_distance > 0 and prev_swing and (cand_l_idx - prev_swing.index < self.min_swing_distance):
                        continue

                    prev_low = swing_lows[-1] if swing_lows else None
                    sl = self._create_swing_point(
                        index=cand_l_idx,
                        price=lows[cand_l_idx],
                        point_type="LOW",
                        conf_idx=t,
                        dates=dates,
                        atr_val=atr[cand_l_idx],
                        thresh_val=thresh_l,
                        volume=volumes[cand_l_idx],
                        vol_median=vol_median_20[cand_l_idx],
                        prev_same_type=prev_low,
                        last_swing=prev_swing
                    )
                    swing_lows.append(sl)
                    all_swings.append(sl)
                    state = "SEEKING_HIGH"

                    # Initialize candidate high from trough to bar t
                    sub_h = highs[cand_l_idx + 1 : t + 1]
                    cand_h_idx = cand_l_idx + 1 + int(np.argmax(sub_h))

        return swing_highs, swing_lows

    def _create_swing_point(
        self,
        index: int,
        price: float,
        point_type: str,
        conf_idx: int,
        dates: np.ndarray,
        atr_val: float,
        thresh_val: float,
        volume: float,
        vol_median: float,
        prev_same_type: Optional[SwingPoint],
        last_swing: Optional[SwingPoint]
    ) -> SwingPoint:
        """Helper to construct a fully enriched SwingPoint."""
        # Classify market structure: HH/LH/EH or HL/LL/EL
        if point_type == "HIGH":
            if prev_same_type is None:
                struct_type = "HIGH"
            elif price > prev_same_type.price * 1.001:
                struct_type = "HH"  # Higher High
            elif price < prev_same_type.price * 0.999:
                struct_type = "LH"  # Lower High
            else:
                struct_type = "EH"  # Equal High
        else:
            if prev_same_type is None:
                struct_type = "LOW"
            elif price > prev_same_type.price * 1.001:
                struct_type = "HL"  # Higher Low
            elif price < prev_same_type.price * 0.999:
                struct_type = "LL"  # Lower Low
            else:
                struct_type = "EL"  # Equal Low

        vol_ratio = (volume / vol_median) if (vol_median and vol_median > 0) else 1.0
        bars_since = (index - last_swing.index) if last_swing else 0

        return SwingPoint(
            index=index,
            trade_date=dates[index],
            price=float(price),
            point_type=point_type,
            confirmed_at_index=conf_idx,
            confirmed_date=dates[conf_idx],
            atr_at_candidate=float(atr_val),
            reversal_threshold=float(thresh_val),
            structure_type=struct_type,
            volume=float(volume),
            volume_median_20=float(vol_median),
            volume_ratio=float(vol_ratio),
            bars_since_prev_swing=int(bars_since)
        )

    def compute_all_structure_breaks(
        self,
        df: pd.DataFrame,
        swing_highs: List[SwingPoint],
        swing_lows: List[SwingPoint]
    ) -> List[StructureBreak]:
        """
        Compute chronological structure breaks across the entire series in O(N) time.
        Strictly causal: Bar i only breaks swings confirmed at or before bar i.
        """
        n = len(df)
        h_col = "HIGH_PRICE" if "HIGH_PRICE" in df.columns else ("High" if "High" in df.columns else None)
        l_col = "LOW_PRICE" if "LOW_PRICE" in df.columns else ("Low" if "Low" in df.columns else None)
        c_col = "CLOSE_PRICE" if "CLOSE_PRICE" in df.columns else ("Close" if "Close" in df.columns else None)
        dates_col = "TRADE_DATE" if "TRADE_DATE" in df.columns else ("trade_date" if "trade_date" in df.columns else None)

        closes = df[c_col].values
        highs = df[h_col].values
        lows = df[l_col].values
        dates = df[dates_col].values if dates_col else df.index.values

        breaks: List[StructureBreak] = []
        broken_sh_indices = set()
        broken_sl_indices = set()

        sh_by_conf = {}
        for s in swing_highs:
            sh_by_conf.setdefault(s.confirmed_at_index, []).append(s)

        sl_by_conf = {}
        for s in swing_lows:
            sl_by_conf.setdefault(s.confirmed_at_index, []).append(s)

        active_sh: List[SwingPoint] = []
        active_sl: List[SwingPoint] = []

        for i in range(n):
            if i in sh_by_conf:
                active_sh.extend(sh_by_conf[i])
            if i in sl_by_conf:
                active_sl.extend(sl_by_conf[i])

            eval_price_high = closes[i] if self.break_type == "close" else highs[i]
            eval_price_low = closes[i] if self.break_type == "close" else lows[i]

            avail_sh = [s for s in active_sh if s.index not in broken_sh_indices]
            avail_sl = [s for s in active_sl if s.index not in broken_sl_indices]

            # Bullish break
            if avail_sh:
                target_sh = avail_sh[-1]
                if eval_price_high > target_sh.price:
                    preceding_sl = [s for s in active_sl if s.index < target_sh.index]
                    anchor = preceding_sl[-1] if preceding_sl else (avail_sl[-1] if avail_sl else target_sh)
                    breaks.append(StructureBreak(
                        break_index=i,
                        break_date=dates[i],
                        direction="BULLISH",
                        broken_swing=target_sh,
                        anchor_swing=anchor,
                        range_low=float(anchor.price),
                        range_high=float(target_sh.price),
                        break_price=float(eval_price_high)
                    ))
                    broken_sh_indices.add(target_sh.index)

            # Bearish break
            if avail_sl:
                target_sl = avail_sl[-1]
                if eval_price_low < target_sl.price:
                    preceding_sh = [s for s in active_sh if s.index < target_sl.index]
                    anchor = preceding_sh[-1] if preceding_sh else (avail_sh[-1] if avail_sh else target_sl)
                    breaks.append(StructureBreak(
                        break_index=i,
                        break_date=dates[i],
                        direction="BEARISH",
                        broken_swing=target_sl,
                        anchor_swing=anchor,
                        range_low=float(target_sl.price),
                        range_high=float(anchor.price),
                        break_price=float(eval_price_low)
                    ))
                    broken_sl_indices.add(target_sl.index)

        return breaks

    def analyze_structure_at_bar(
        self,
        df: pd.DataFrame,
        current_idx: int,
        swing_highs: List[SwingPoint],
        swing_lows: List[SwingPoint],
        precomputed_breaks: Optional[List[StructureBreak]] = None
    ) -> Dict[str, Any]:
        """
        Evaluates the structural state at bar current_idx using only swings
        and prices confirmed at or before current_idx.
        """
        active_sh = [s for s in swing_highs if s.confirmed_at_index <= current_idx]
        active_sl = [s for s in swing_lows if s.confirmed_at_index <= current_idx]

        if precomputed_breaks is not None:
            breaks = [b for b in precomputed_breaks if b.break_index <= current_idx]
        else:
            breaks = self.compute_all_structure_breaks(df.iloc[:current_idx + 1], swing_highs, swing_lows)

        if len(breaks) < 2:
            current_b = breaks[-1] if breaks else None
            return {
                "has_two_structures": False,
                "trend": current_b.direction if current_b else "NEUTRAL",
                "current_structure": current_b,
                "previous_structure": None,
                "range_low": current_b.range_low if current_b else None,
                "range_high": current_b.range_high if current_b else None,
                "active_swing_high": active_sh[-1].price if active_sh else None,
                "active_swing_low": active_sl[-1].price if active_sl else None
            }

        curr_struct = breaks[-1]
        prev_struct = breaks[-2]

        # '2 Structures' condition: both the current and the prior structure breaks are in the same direction
        has_two = (curr_struct.direction == prev_struct.direction)

        # For the active trading range, define low and high bounds
        r_low = min(curr_struct.range_low, prev_struct.range_low)
        r_high = max(curr_struct.range_high, prev_struct.range_high)

        return {
            "has_two_structures": has_two,
            "trend": curr_struct.direction if has_two else "NEUTRAL",
            "current_structure": curr_struct,
            "previous_structure": prev_struct,
            "range_low": r_low,
            "range_high": r_high,
            "active_swing_high": active_sh[-1].price if active_sh else None,
            "active_swing_low": active_sl[-1].price if active_sl else None
        }
