"""
Gann Box & 75% Relative Position Module.
Calculates quadrant levels within structural price ranges and evaluates
whether market price is in favorable discount/premium context.
"""

from typing import Dict, Any, Optional


class GannBoxAnalyzer:
    """Computes Gann Box relative levels and 75% zone filter."""

    @staticmethod
    def calculate_levels(
        range_low: float,
        range_high: float,
        current_price: float,
        trend: str = "BULLISH",
        mode: str = "gann_75"  # 'gann_75' (upper 75% mark) or 'discount_75' (75% pullback)
    ) -> Dict[str, Any]:
        """
        Calculate relative position in structure range:
        - 0.0: Range Low
        - 0.25: 25% Level
        - 0.50: Equilibrium (50%)
        - 0.75: 75% Level
        - 1.0: Range High
        """
        if range_high <= range_low or range_low <= 0:
            return {
                "valid": False,
                "range_low": range_low,
                "range_high": range_high,
                "level_25": range_low,
                "level_50": range_low,
                "level_75": range_high,
                "relative_position": 0.5,
                "is_favorable": True,
                "zone": "UNKNOWN"
            }

        span = range_high - range_low
        level_25 = range_low + 0.25 * span
        level_50 = range_low + 0.50 * span
        level_75 = range_low + 0.75 * span

        # Relative position (0.0 to 1.0)
        rel_pos = (current_price - range_low) / span

        # Categorize Zone
        if current_price < level_50:
            zone = "DISCOUNT"
        elif current_price > level_50:
            zone = "PREMIUM"
        else:
            zone = "EQUILIBRIUM"

        # Evaluate favorability for trading
        # In Price Action theory:
        # - Bullish setups prefer entering in DISCOUNT or after healthy pullback (<= 75% level).
        # - Bearish setups prefer entering in PREMIUM (>= 25% or >= 50% level).
        if trend == "BULLISH":
            # For buying: price should not be overbought above the 75% level of the range
            is_favorable = (current_price <= level_75)
        elif trend == "BEARISH":
            # For selling: price should not be oversold below the 25% level of the range
            is_favorable = (current_price >= level_25)
        else:
            is_favorable = True

        return {
            "valid": True,
            "range_low": round(range_low, 4),
            "range_high": round(range_high, 4),
            "level_25": round(level_25, 4),
            "level_50": round(level_50, 4),
            "level_75": round(level_75, 4),
            "relative_position": round(rel_pos, 4),
            "is_favorable": is_favorable,
            "zone": zone,
            "current_price": round(current_price, 4)
        }
