"""
Fair Value Gap (FVG) Detection & Lifecycle Tracking Module.
Identifies 3-bar price imbalances and tracks mitigation, retest, and invalidation states.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import pandas as pd


@dataclass
class FairValueGap:
    fvg_id: str
    direction: str  # 'BULLISH' or 'BEARISH'
    formed_at_index: int
    formed_at_date: Any
    c1_index: int
    c2_index: int
    c3_index: int
    gap_low: float
    gap_high: float
    gap_size: float
    status: str  # 'UNTESTED', 'MITIGATED', 'FILLED', 'INVALIDATED'
    mitigated_at_date: Optional[Any] = None
    filled_at_date: Optional[Any] = None


class FairValueGapDetector:
    """Detects and tracks the life cycle of Fair Value Gaps."""

    def __init__(self, min_gap_pct: float = 0.001):
        """
        Args:
            min_gap_pct: Minimum gap size as percentage of price (default 0.1% to avoid noise).
        """
        self.min_gap_pct = min_gap_pct

    def detect_fvg_at(self, df: pd.DataFrame, end_idx: int) -> Optional[FairValueGap]:
        """
        Check if a Fair Value Gap is created by the 3-bar cluster ending at end_idx.
        Bars are [end_idx - 2, end_idx - 1, end_idx].
        """
        if end_idx < 2 or len(df) <= end_idx:
            return None

        c1 = df.iloc[end_idx - 2]
        c2 = df.iloc[end_idx - 1]
        c3 = df.iloc[end_idx]

        c1_high = float(c1["HIGH_PRICE"])
        c1_low = float(c1["LOW_PRICE"])
        c3_high = float(c3["HIGH_PRICE"])
        c3_low = float(c3["LOW_PRICE"])
        c2_close = float(c2["CLOSE_PRICE"])
        t_date = c3["TRADE_DATE"] if "TRADE_DATE" in c3 else df.index[end_idx]

        # 1. Bullish FVG: Low of candle 3 is strictly greater than High of candle 1
        if c3_low > c1_high:
            gap_size = c3_low - c1_high
            if c2_close > 0 and (gap_size / c2_close) >= self.min_gap_pct:
                return FairValueGap(
                    fvg_id=f"FVG_BULL_{end_idx}_{str(t_date)[:10]}",
                    direction="BULLISH",
                    formed_at_index=end_idx,
                    formed_at_date=t_date,
                    c1_index=end_idx - 2,
                    c2_index=end_idx - 1,
                    c3_index=end_idx,
                    gap_low=round(c1_high, 4),
                    gap_high=round(c3_low, 4),
                    gap_size=round(gap_size, 4),
                    status="UNTESTED"
                )

        # 2. Bearish FVG: High of candle 3 is strictly lower than Low of candle 1
        elif c3_high < c1_low:
            gap_size = c1_low - c3_high
            if c2_close > 0 and (gap_size / c2_close) >= self.min_gap_pct:
                return FairValueGap(
                    fvg_id=f"FVG_BEAR_{end_idx}_{str(t_date)[:10]}",
                    direction="BEARISH",
                    formed_at_index=end_idx,
                    formed_at_date=t_date,
                    c1_index=end_idx - 2,
                    c2_index=end_idx - 1,
                    c3_index=end_idx,
                    gap_low=round(c3_high, 4),
                    gap_high=round(c1_low, 4),
                    gap_size=round(gap_size, 4),
                    status="UNTESTED"
                )

        return None

    def detect_fvg_fast(
        self,
        c1_high: float,
        c1_low: float,
        c2_close: float,
        c3_high: float,
        c3_low: float,
        end_idx: int,
        t_date: Any
    ) -> Optional[FairValueGap]:
        """Fast FVG detection without Series slicing."""
        if c3_low > c1_high:
            gap_size = c3_low - c1_high
            if c2_close > 0 and (gap_size / c2_close) >= self.min_gap_pct:
                return FairValueGap(
                    fvg_id=f"FVG_BULL_{end_idx}_{str(t_date)[:10]}",
                    direction="BULLISH",
                    formed_at_index=end_idx,
                    formed_at_date=t_date,
                    c1_index=end_idx - 2,
                    c2_index=end_idx - 1,
                    c3_index=end_idx,
                    gap_low=round(c1_high, 4),
                    gap_high=round(c3_low, 4),
                    gap_size=round(gap_size, 4),
                    status="UNTESTED"
                )
        elif c3_high < c1_low:
            gap_size = c1_low - c3_high
            if c2_close > 0 and (gap_size / c2_close) >= self.min_gap_pct:
                return FairValueGap(
                    fvg_id=f"FVG_BEAR_{end_idx}_{str(t_date)[:10]}",
                    direction="BEARISH",
                    formed_at_index=end_idx,
                    formed_at_date=t_date,
                    c1_index=end_idx - 2,
                    c2_index=end_idx - 1,
                    c3_index=end_idx,
                    gap_low=round(c3_high, 4),
                    gap_high=round(c1_low, 4),
                    gap_size=round(gap_size, 4),
                    status="UNTESTED"
                )
        return None

    @staticmethod
    def update_lifecycle_fast(fvg: FairValueGap, high: float, low: float, close: float, current_date: Any) -> None:
        """Fast lifecycle update using primitive floats."""
        if fvg.status in ("FILLED", "INVALIDATED"):
            return

        if fvg.direction == "BULLISH":
            if close < fvg.gap_low:
                fvg.status = "INVALIDATED"
                fvg.filled_at_date = current_date
            elif low <= fvg.gap_high:
                if fvg.status == "UNTESTED":
                    fvg.status = "MITIGATED"
                    fvg.mitigated_at_date = current_date
        elif fvg.direction == "BEARISH":
            if close > fvg.gap_high:
                fvg.status = "INVALIDATED"
                fvg.filled_at_date = current_date
            elif high >= fvg.gap_low:
                if fvg.status == "UNTESTED":
                    fvg.status = "MITIGATED"
                    fvg.mitigated_at_date = current_date

    @staticmethod
    def update_lifecycle(fvg: FairValueGap, row: pd.Series, current_date: Any) -> None:
        """
        Update the status of an existing FVG using current bar price action.
        """
        if fvg.status in ("FILLED", "INVALIDATED"):
            return

        h = float(row["HIGH_PRICE"])
        l = float(row["LOW_PRICE"])
        c = float(row["CLOSE_PRICE"])

        if fvg.direction == "BULLISH":
            # Invalidated if price breaks cleanly below the gap bottom
            if c < fvg.gap_low:
                fvg.status = "INVALIDATED"
                fvg.filled_at_date = current_date
            # Mitigated if price dips into the gap
            elif l <= fvg.gap_high:
                if fvg.status == "UNTESTED":
                    fvg.status = "MITIGATED"
                    fvg.mitigated_at_date = current_date

        elif fvg.direction == "BEARISH":
            # Invalidated if price closes cleanly above the gap top
            if c > fvg.gap_high:
                fvg.status = "INVALIDATED"
                fvg.filled_at_date = current_date
            # Mitigated if price rallies into the gap
            elif h >= fvg.gap_low:
                if fvg.status == "UNTESTED":
                    fvg.status = "MITIGATED"
                    fvg.mitigated_at_date = current_date
