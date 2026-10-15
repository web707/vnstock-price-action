"""
Confluence Zone Synthesizer & Signal Generator Module.
Finds spatial and directional overlap between:
1. Market Structure (Two consecutive BOS breaks).
2. 75% Gann Box contextual zone.
3. Valid 3-Candle momentum pattern.
4. Active Fair Value Gap (FVG).
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import pandas as pd
from src.strategy.market_structure import StructureBreak
from src.strategy.candle_pattern import CandlePatternResult
from src.strategy.fvg_detector import FairValueGap
from src.strategy.gann_box import GannBoxAnalyzer


@dataclass
class ConfluenceSignal:
    signal_id: str
    symbol: str
    bar_index: int
    trade_date: Any
    signal_type: str  # 'BUY' or 'SELL'
    confluence_low: float
    confluence_high: float
    confluence_mid: float
    gann_75_level: float
    limit_price: float
    stop_loss_price: float
    take_profit_price: float
    risk_reward_ratio: float
    conditions_met: Dict[str, bool]
    rejection_reason: Optional[str] = None


class ConfluenceSynthesizer:
    """Synthesizes structural and price action signals into actionable confluence zones."""

    def __init__(
        self,
        entry_mode: str = "zone_boundary",  # 'zone_boundary' or 'zone_midpoint'
        sl_buffer_pct: float = 0.005,       # 0.5% buffer for Stop Loss
        min_risk_reward: float = 1.5,       # Minimum R:R ratio required to generate a trade signal
        require_gann_filter: bool = True    # Whether 75% Gann filter is mandatory
    ):
        self.entry_mode = entry_mode
        self.sl_buffer_pct = sl_buffer_pct
        self.min_risk_reward = min_risk_reward
        self.require_gann_filter = require_gann_filter

    def evaluate_confluence(
        self,
        symbol: str,
        bar_idx: int,
        trade_date: Any,
        current_close: float,
        structure_state: Dict[str, Any],
        candle_pattern: CandlePatternResult,
        fvg: Optional[FairValueGap]
    ) -> Optional[ConfluenceSignal]:
        """
        Synthesize conditions at bar_idx. Returns ConfluenceSignal if valid, otherwise None.
        """
        conditions = {
            "has_two_structures": bool(structure_state.get("has_two_structures")),
            "valid_3_candle_pattern": bool(candle_pattern.is_valid),
            "valid_fvg": bool(fvg is not None),
            "directional_alignment": False,
            "spatial_overlap": False,
            "gann_75_favorable": False,
            "favorable_risk_reward": False
        }

        # 1. Basic presence check
        if not candle_pattern.is_valid or fvg is None:
            return None

        # 2. Check Directional Alignment
        trend = structure_state.get("trend", "NEUTRAL")
        direction = candle_pattern.direction  # 'BULLISH' or 'BEARISH'

        # Both the structure and the 3-candle pattern and FVG must align
        if trend == "BULLISH" and direction == "BULLISH" and fvg.direction == "BULLISH":
            signal_type = "BUY"
            conditions["directional_alignment"] = True
        elif trend == "BEARISH" and direction == "BEARISH" and fvg.direction == "BEARISH":
            signal_type = "SELL"
            conditions["directional_alignment"] = True
        else:
            return None

        # 3. Spatial Overlap between FVG and 3-Candle Pattern
        conf_low = max(fvg.gap_low, candle_pattern.pattern_low)
        conf_high = min(fvg.gap_high, candle_pattern.pattern_high)

        if conf_low >= conf_high:
            # No genuine geometric overlap
            return None
        conditions["spatial_overlap"] = True
        conf_mid = (conf_low + conf_high) / 2.0

        # 4. Gann Box 75% Contextual Filter
        r_low = structure_state.get("range_low")
        r_high = structure_state.get("range_high")
        gann_info = GannBoxAnalyzer.calculate_levels(
            range_low=r_low if r_low else conf_low,
            range_high=r_high if r_high else conf_high,
            current_price=current_close,
            trend=trend
        )
        conditions["gann_75_favorable"] = gann_info["is_favorable"]

        if self.require_gann_filter and not gann_info["is_favorable"]:
            return None

        # 5. Determine Entry Limit Price
        if signal_type == "BUY":
            limit_price = conf_high if self.entry_mode == "zone_boundary" else conf_mid
            # Stop loss placed below confluence zone and active swing low with buffer
            anchor_low = structure_state.get("active_swing_low") or conf_low
            base_sl = min(conf_low, anchor_low)
            stop_loss = round(base_sl * (1.0 - self.sl_buffer_pct), 4)

            # Target is the active structural swing high
            target_high = structure_state.get("active_swing_high") or structure_state.get("range_high")
            if not target_high or target_high <= limit_price:
                # If target is missing or lower than entry, fallback to 2.5x risk
                risk = limit_price - stop_loss
                take_profit = round(limit_price + 2.5 * risk, 4)
            else:
                take_profit = round(float(target_high), 4)

            risk = limit_price - stop_loss
            reward = take_profit - limit_price

        else:  # SELL
            limit_price = conf_low if self.entry_mode == "zone_boundary" else conf_mid
            anchor_high = structure_state.get("active_swing_high") or conf_high
            base_sl = max(conf_high, anchor_high)
            stop_loss = round(base_sl * (1.0 + self.sl_buffer_pct), 4)

            target_low = structure_state.get("active_swing_low") or structure_state.get("range_low")
            if not target_low or target_low >= limit_price:
                risk = stop_loss - limit_price
                take_profit = round(limit_price - 2.5 * risk, 4)
            else:
                take_profit = round(float(target_low), 4)

            risk = stop_loss - limit_price
            reward = limit_price - take_profit

        # 6. Risk to Reward Validation
        if risk <= 0:
            return None

        rr_ratio = reward / risk
        conditions["favorable_risk_reward"] = (rr_ratio >= self.min_risk_reward)

        if rr_ratio < self.min_risk_reward:
            return None

        sig_id = f"SIG_{symbol}_{signal_type}_{str(trade_date)[:10]}_{bar_idx}"

        return ConfluenceSignal(
            signal_id=sig_id,
            symbol=symbol,
            bar_index=bar_idx,
            trade_date=trade_date,
            signal_type=signal_type,
            confluence_low=round(conf_low, 4),
            confluence_high=round(conf_high, 4),
            confluence_mid=round(conf_mid, 4),
            gann_75_level=gann_info["level_75"],
            limit_price=round(limit_price, 4),
            stop_loss_price=round(stop_loss, 4),
            take_profit_price=round(take_profit, 4),
            risk_reward_ratio=round(rr_ratio, 2),
            conditions_met=conditions
        )
