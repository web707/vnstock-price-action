"""
Strategy Engine Module for John Lucas Pruni Method.
Integrates Structure Tracker, 3-Candle Detector, FVG Detector, Gann Box, and Confluence Synthesizer.
"""

from typing import List, Dict, Any, Optional
import pandas as pd
from src.strategy.market_structure import MarketStructureTracker
from src.strategy.candle_pattern import ThreeCandlePatternDetector
from src.strategy.fvg_detector import FairValueGapDetector, FairValueGap
from src.strategy.confluence import ConfluenceSynthesizer, ConfluenceSignal


class JohnLucasPruniStrategy:
    """End-to-end implementation of '2 Structures & 3 Candles' Price Action Strategy."""

    def __init__(
        self,
        swing_left: int = 3,
        swing_right: int = 2,
        break_type: str = "close",
        candle_validation_mode: str = "middle_candle",
        min_fvg_gap_pct: float = 0.001,
        entry_mode: str = "zone_boundary",
        sl_buffer_pct: float = 0.005,
        min_risk_reward: float = 1.5,
        require_gann_filter: bool = True
    ):
        self.structure_tracker = MarketStructureTracker(
            swing_left=swing_left,
            swing_right=swing_right,
            break_type=break_type
        )
        self.candle_detector = ThreeCandlePatternDetector(
            validation_mode=candle_validation_mode
        )
        self.fvg_detector = FairValueGapDetector(
            min_gap_pct=min_fvg_gap_pct
        )
        self.confluence_synthesizer = ConfluenceSynthesizer(
            entry_mode=entry_mode,
            sl_buffer_pct=sl_buffer_pct,
            min_risk_reward=min_risk_reward,
            require_gann_filter=require_gann_filter
        )

    def scan_dataframe(self, df: pd.DataFrame, symbol: str) -> List[ConfluenceSignal]:
        """
        Scan a historical price DataFrame chronologically bar-by-bar
        without any future lookahead to detect confluence signals.
        """
        if df.empty or len(df) < 10:
            return []

        data = df.copy()
        if "TRADE_DATE" not in data.columns and isinstance(data.index, pd.DatetimeIndex):
            data["TRADE_DATE"] = [d.date() if hasattr(d, "date") else d for d in data.index]

        # 1. Pre-detect all potential swing points (each swing records confirmed_at_index)
        swing_highs, swing_lows = self.structure_tracker.detect_swings(data)
        all_breaks = self.structure_tracker.compute_all_structure_breaks(data, swing_highs, swing_lows)

        # 2. Vectorized precomputation of candle metrics
        precomputed_candles = self.candle_detector.precompute_candles(data)

        # 3. Organize swings and breaks by confirmation index for O(1) incremental tracking
        sh_by_conf = {}
        for s in swing_highs:
            sh_by_conf.setdefault(s.confirmed_at_index, []).append(s)
        sl_by_conf = {}
        for s in swing_lows:
            sl_by_conf.setdefault(s.confirmed_at_index, []).append(s)
        breaks_by_idx = {}
        for b in all_breaks:
            breaks_by_idx.setdefault(b.break_index, []).append(b)

        active_sh = []
        active_sl = []
        active_breaks = []

        signals: List[ConfluenceSignal] = []
        active_fvgs: List[FairValueGap] = []

        n = len(data)
        dates = data["TRADE_DATE"].to_numpy() if "TRADE_DATE" in data.columns else data.index.to_numpy()
        highs = data["HIGH_PRICE"].to_numpy(dtype=float)
        lows = data["LOW_PRICE"].to_numpy(dtype=float)
        closes = data["CLOSE_PRICE"].to_numpy(dtype=float)

        # Walk-forward bar by bar
        for i in range(5, n):
            current_date = dates[i]
            current_close = float(closes[i])
            current_high = float(highs[i])
            current_low = float(lows[i])

            # Incrementally register confirmed swings and structure breaks
            if i in sh_by_conf:
                active_sh.extend(sh_by_conf[i])
            if i in sl_by_conf:
                active_sl.extend(sl_by_conf[i])
            if i in breaks_by_idx:
                active_breaks.extend(breaks_by_idx[i])

            # Update life-cycle of existing active FVGs (prune old/invalidated)
            remaining_fvgs = []
            for fvg in active_fvgs:
                FairValueGapDetector.update_lifecycle_fast(fvg, current_high, current_low, current_close, current_date)
                if fvg.status in ("UNTESTED", "MITIGATED") and (i - fvg.formed_at_index) <= 60:
                    remaining_fvgs.append(fvg)
            active_fvgs = remaining_fvgs

            # Detect new FVG formed at bar i (using [i-2, i-1, i])
            new_fvg = self.fvg_detector.detect_fvg_fast(
                c1_high=highs[i - 2],
                c1_low=lows[i - 2],
                c2_close=closes[i - 1],
                c3_high=highs[i],
                c3_low=lows[i],
                end_idx=i,
                t_date=current_date
            )
            if new_fvg is not None:
                active_fvgs.append(new_fvg)

            # Evaluate 3-Candle Pattern ending at bar i
            pattern_result = self.candle_detector.evaluate_pattern_at(
                data, i, precomputed_candles=precomputed_candles
            )

            # Evaluate Market Structure state visible at bar i in O(1)
            if len(active_breaks) < 2:
                current_b = active_breaks[-1] if active_breaks else None
                structure_state = {
                    "has_two_structures": False,
                    "trend": current_b.direction if current_b else "NEUTRAL",
                    "current_structure": current_b,
                    "previous_structure": None,
                    "range_low": current_b.range_low if current_b else None,
                    "range_high": current_b.range_high if current_b else None,
                    "active_swing_high": active_sh[-1].price if active_sh else None,
                    "active_swing_low": active_sl[-1].price if active_sl else None
                }
            else:
                curr_struct = active_breaks[-1]
                prev_struct = active_breaks[-2]
                has_two = (curr_struct.direction == prev_struct.direction)
                r_low = min(curr_struct.range_low, prev_struct.range_low)
                r_high = max(curr_struct.range_high, prev_struct.range_high)
                structure_state = {
                    "has_two_structures": has_two,
                    "trend": curr_struct.direction if has_two else "NEUTRAL",
                    "current_structure": curr_struct,
                    "previous_structure": prev_struct,
                    "range_low": r_low,
                    "range_high": r_high,
                    "active_swing_high": active_sh[-1].price if active_sh else None,
                    "active_swing_low": active_sl[-1].price if active_sl else None
                }

            # Check confluence with new FVG (or recent untested FVG)
            target_fvg = new_fvg
            if target_fvg is None and active_fvgs:
                recent_untested = [f for f in active_fvgs if f.status in ("UNTESTED", "MITIGATED") and (i - f.formed_at_index) <= 5]
                if recent_untested:
                    target_fvg = recent_untested[-1]

            if target_fvg is not None:
                sig = self.confluence_synthesizer.evaluate_confluence(
                    symbol=symbol,
                    bar_idx=i,
                    trade_date=current_date,
                    current_close=current_close,
                    structure_state=structure_state,
                    candle_pattern=pattern_result,
                    fvg=target_fvg
                )
                if sig is not None:
                    signals.append(sig)

        return signals
