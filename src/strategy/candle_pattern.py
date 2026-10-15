"""
3-Candle Pattern Recognition Module (John Lucas Pruni method).
Evaluates body vs wick dominance ('thân nến lớn hơn râu nến ở hai đầu')
and displacement characteristics across sequential 3-bar clusters.
"""

from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class CandleMetrics:
    index: int
    trade_date: Any
    open: float
    high: float
    low: float
    close: float
    body: float
    upper_wick: float
    lower_wick: float
    total_range: float
    is_bull: bool
    is_body_dominant: bool  # body > upper_wick and body > lower_wick


@dataclass
class CandlePatternResult:
    is_valid: bool
    direction: str  # 'BULLISH', 'BEARISH', 'NONE'
    start_index: int
    end_index: int
    dates: List[Any]
    candles: List[CandleMetrics]
    pattern_low: float
    pattern_high: float
    rejection_reason: Optional[str] = None


class ThreeCandlePatternDetector:
    """Detects and validates 3-candle momentum displacement clusters."""

    def __init__(
        self,
        validation_mode: str = "middle_candle",  # 'middle_candle', 'all_candles', 'cumulative'
        require_sequential_direction: bool = True
    ):
        self.validation_mode = validation_mode
        self.require_sequential_direction = require_sequential_direction

    @staticmethod
    def extract_candle_metrics(df: pd.DataFrame, idx: int) -> CandleMetrics:
        """Extract exact body, wick, and direction metrics for a single bar."""
        row = df.iloc[idx]
        o = float(row["OPEN_PRICE"])
        h = float(row["HIGH_PRICE"])
        l = float(row["LOW_PRICE"])
        c = float(row["CLOSE_PRICE"])
        t_date = row["TRADE_DATE"] if "TRADE_DATE" in row else df.index[idx]

        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        total_range = h - l
        is_bull = (c >= o)

        # "Thân nến lớn hơn râu nến ở hai đầu"
        # Body must exceed both the upper wick and the lower wick individually
        is_body_dominant = (body > upper_wick) and (body > lower_wick)

        return CandleMetrics(
            index=idx,
            trade_date=t_date,
            open=o,
            high=h,
            low=l,
            close=c,
            body=round(body, 4),
            upper_wick=round(upper_wick, 4),
            lower_wick=round(lower_wick, 4),
            total_range=round(total_range, 4),
            is_bull=is_bull,
            is_body_dominant=is_body_dominant
        )

    @staticmethod
    def precompute_candles(df: pd.DataFrame) -> List[CandleMetrics]:
        """Vectorized precomputation of CandleMetrics across entire DataFrame."""
        n = len(df)
        if n == 0:
            return []
        o = df["OPEN_PRICE"].to_numpy(dtype=float)
        h = df["HIGH_PRICE"].to_numpy(dtype=float)
        l = df["LOW_PRICE"].to_numpy(dtype=float)
        c = df["CLOSE_PRICE"].to_numpy(dtype=float)
        dates = df["TRADE_DATE"].to_numpy() if "TRADE_DATE" in df.columns else df.index.to_numpy()

        body = np.abs(c - o)
        max_oc = np.maximum(o, c)
        min_oc = np.minimum(o, c)
        upper_wick = h - max_oc
        lower_wick = min_oc - l
        total_range = h - l
        is_bull = (c >= o)
        is_body_dom = (body > upper_wick) & (body > lower_wick)

        metrics = []
        for i in range(n):
            metrics.append(CandleMetrics(
                index=i,
                trade_date=dates[i],
                open=float(o[i]),
                high=float(h[i]),
                low=float(l[i]),
                close=float(c[i]),
                body=round(float(body[i]), 4),
                upper_wick=round(float(upper_wick[i]), 4),
                lower_wick=round(float(lower_wick[i]), 4),
                total_range=round(float(total_range[i]), 4),
                is_bull=bool(is_bull[i]),
                is_body_dominant=bool(is_body_dom[i])
            ))
        return metrics

    def evaluate_pattern_at(
        self,
        df: pd.DataFrame,
        end_idx: int,
        precomputed_candles: Optional[List[CandleMetrics]] = None
    ) -> CandlePatternResult:
        """
        Evaluate the 3-candle sequence ending at end_idx (bars [end_idx - 2, end_idx - 1, end_idx]).
        """
        if end_idx < 2 or len(df) <= end_idx:
            return CandlePatternResult(
                is_valid=False,
                direction="NONE",
                start_index=end_idx - 2,
                end_index=end_idx,
                dates=[],
                candles=[],
                pattern_low=0.0,
                pattern_high=0.0,
                rejection_reason="INSUFFICIENT_BARS"
            )

        if precomputed_candles is not None:
            c1 = precomputed_candles[end_idx - 2]
            c2 = precomputed_candles[end_idx - 1]
            c3 = precomputed_candles[end_idx]
        else:
            c1 = self.extract_candle_metrics(df, end_idx - 2)
            c2 = self.extract_candle_metrics(df, end_idx - 1)
            c3 = self.extract_candle_metrics(df, end_idx)
        candles = [c1, c2, c3]
        dates = [c1.trade_date, c2.trade_date, c3.trade_date]

        p_low = min(c1.low, c2.low, c3.low)
        p_high = max(c1.high, c2.high, c3.high)

        # Check directional alignment
        # Bullish cluster: c2 is bullish impulse, c3 extends higher than c1
        # Bearish cluster: c2 is bearish impulse, c3 extends lower than c1
        if c2.is_bull and c3.close > c1.high:
            direction = "BULLISH"
        elif (not c2.is_bull) and c3.close < c1.low:
            direction = "BEARISH"
        else:
            return CandlePatternResult(
                is_valid=False,
                direction="NONE",
                start_index=end_idx - 2,
                end_index=end_idx,
                dates=dates,
                candles=candles,
                pattern_low=p_low,
                pattern_high=p_high,
                rejection_reason="DIRECTION_MISALIGNMENT: C2/C3 do not display directional expansion past C1"
            )

        # Check Body vs Wick Dominance according to configured mode
        if self.validation_mode == "middle_candle":
            # Candle 2 (displacement bar) must have body > upper wick and body > lower wick
            if not c2.is_body_dominant:
                return CandlePatternResult(
                    is_valid=False,
                    direction=direction,
                    start_index=end_idx - 2,
                    end_index=end_idx,
                    dates=dates,
                    candles=candles,
                    pattern_low=p_low,
                    pattern_high=p_high,
                    rejection_reason=f"C2_BODY_NOT_DOMINANT: C2 body ({c2.body}) <= upper ({c2.upper_wick}) or lower ({c2.lower_wick})"
                )

        elif self.validation_mode == "all_candles":
            # All 3 candles must be body dominant
            non_dominant = [i + 1 for i, c in enumerate(candles) if not c.is_body_dominant]
            if non_dominant:
                return CandlePatternResult(
                    is_valid=False,
                    direction=direction,
                    start_index=end_idx - 2,
                    end_index=end_idx,
                    dates=dates,
                    candles=candles,
                    pattern_low=p_low,
                    pattern_high=p_high,
                    rejection_reason=f"ALL_CANDLES_FAILED: Candle(s) {non_dominant} bodies not dominant over wicks"
                )

        elif self.validation_mode == "cumulative":
            total_body = c1.body + c2.body + c3.body
            total_wicks = (c1.upper_wick + c1.lower_wick + c2.upper_wick + c2.lower_wick + c3.upper_wick + c3.lower_wick)
            if total_body <= total_wicks:
                return CandlePatternResult(
                    is_valid=False,
                    direction=direction,
                    start_index=end_idx - 2,
                    end_index=end_idx,
                    dates=dates,
                    candles=candles,
                    pattern_low=p_low,
                    pattern_high=p_high,
                    rejection_reason=f"CUMULATIVE_BODY_INSUFFICIENT: Total body ({total_body}) <= total wicks ({total_wicks})"
                )

        return CandlePatternResult(
            is_valid=True,
            direction=direction,
            start_index=end_idx - 2,
            end_index=end_idx,
            dates=dates,
            candles=candles,
            pattern_low=p_low,
            pattern_high=p_high,
            rejection_reason=None
        )
