"""
Unit tests for John Lucas Pruni Strategy Components.
Covers:
- Market Structure & BOS
- Gann Box 75% calculation
- 3-Candle Pattern Recognition (Body > Wicks)
- Fair Value Gap (FVG) Detection & Lifecycle
- Confluence Zone Synthesizer & Signal generation
"""

import pytest
import pandas as pd
import numpy as np

from src.strategy.market_structure import MarketStructureTracker, SwingPoint
from src.strategy.gann_box import GannBoxAnalyzer
from src.strategy.candle_pattern import ThreeCandlePatternDetector
from src.strategy.fvg_detector import FairValueGapDetector
from src.strategy.confluence import ConfluenceSynthesizer


def test_market_structure_swing_and_bos():
    # Construct a synthetic price series with an obvious swing high at index 3
    # Left=2, Right=2
    highs = [10.0, 12.0, 15.0, 20.0, 16.0, 14.0, 18.0, 22.0]
    lows =  [8.0,  10.0, 13.0, 17.0, 14.0, 12.0, 15.0, 19.0]
    closes = [9.0, 11.0, 14.0, 19.0, 15.0, 13.0, 17.0, 21.0]
    dates = pd.date_range("2026-01-01", periods=len(highs))

    df = pd.DataFrame({
        "OPEN_PRICE": [h - 1.0 for h in highs],
        "HIGH_PRICE": highs,
        "LOW_PRICE": lows,
        "CLOSE_PRICE": closes,
        "TRADE_DATE": dates
    })

    tracker = MarketStructureTracker(swing_left=2, swing_right=2)
    sw_highs, sw_lows = tracker.detect_swings(df)

    # Swing high should be at index 3 (price 20.0), confirmed at index 3+2 = 5
    assert len(sw_highs) >= 1
    sh_at_3 = next((s for s in sw_highs if s.index == 3), None)
    assert sh_at_3 is not None
    assert sh_at_3.price == 20.0
    assert sh_at_3.confirmed_at_index == 5

    # At bar 4: swing high is NOT yet confirmed (lookahead protection!)
    state_at_4 = tracker.analyze_structure_at_bar(df, 4, sw_highs, sw_lows)
    assert state_at_4["active_swing_high"] is None or state_at_4["active_swing_high"] != 20.0

    # At bar 7: Close is 21.0 > 20.0 -> Bullish BOS triggered!
    state_at_7 = tracker.analyze_structure_at_bar(df, 7, sw_highs, sw_lows)
    assert state_at_7["trend"] in ("BULLISH", "NEUTRAL")


def test_gann_box_75_calculation():
    # Range 10.0 to 20.0 -> Span = 10.0
    # 25% = 12.5, 50% = 15.0, 75% = 17.5
    res = GannBoxAnalyzer.calculate_levels(
        range_low=10.0,
        range_high=20.0,
        current_price=16.0,
        trend="BULLISH"
    )

    assert res["valid"] is True
    assert res["level_25"] == 12.5
    assert res["level_50"] == 15.0
    assert res["level_75"] == 17.5
    assert res["relative_position"] == 0.6
    assert res["zone"] == "PREMIUM"
    # In Bullish setup, price 16.0 is <= 17.5 (75% mark), so it is favorable
    assert res["is_favorable"] is True

    # Price at 19.0 > 17.5 (overbought above 75%)
    res_overbought = GannBoxAnalyzer.calculate_levels(
        range_low=10.0,
        range_high=20.0,
        current_price=19.0,
        trend="BULLISH"
    )
    assert res_overbought["is_favorable"] is False


def test_three_candle_pattern_body_dominance():
    dates = pd.date_range("2026-01-01", periods=3)
    # Candle 2 has large body and tiny wicks (body > upper_wick and body > lower_wick)
    # C1: Open 10, High 11, Low 9.5, Close 10.5
    # C2: Open 10.5, High 13.5, Low 10.3, Close 13.2 (Body=2.7, Upper=0.3, Lower=0.2 -> Body dominant!)
    # C3: Open 13.2, High 14.5, Low 13.0, Close 14.0
    df = pd.DataFrame({
        "OPEN_PRICE":  [10.0, 10.5, 13.2],
        "HIGH_PRICE":  [11.0, 13.5, 14.5],
        "LOW_PRICE":   [9.5,  10.3, 13.0],
        "CLOSE_PRICE": [10.5, 13.2, 14.0],
        "TRADE_DATE": dates
    })

    detector = ThreeCandlePatternDetector(validation_mode="middle_candle")
    res = detector.evaluate_pattern_at(df, 2)

    assert res.is_valid is True
    assert res.direction == "BULLISH"
    assert res.candles[1].is_body_dominant is True


def test_three_candle_pattern_reject_doji_or_large_wicks():
    dates = pd.date_range("2026-01-01", periods=3)
    # C2 has huge upper wick (shooting star / inverted hammer), body is tiny
    # C2: Open 11.0, High 15.0, Low 10.8, Close 11.2 (Body=0.2, Upper=3.8 -> NOT dominant)
    df = pd.DataFrame({
        "OPEN_PRICE":  [10.0, 11.0, 12.0],
        "HIGH_PRICE":  [11.0, 15.0, 13.0],
        "LOW_PRICE":   [9.5,  10.8, 11.5],
        "CLOSE_PRICE": [10.5, 11.2, 12.5],
        "TRADE_DATE": dates
    })

    detector = ThreeCandlePatternDetector(validation_mode="middle_candle")
    res = detector.evaluate_pattern_at(df, 2)

    assert res.is_valid is False
    assert "C2_BODY_NOT_DOMINANT" in (res.rejection_reason or "")


def test_fvg_detection_bullish_and_bearish():
    dates = pd.date_range("2026-01-01", periods=3)
    # Bullish FVG: C3 Low > C1 High
    # C1 High = 11.0
    # C3 Low = 12.5 -> Gap = [11.0, 12.5]
    df_bull = pd.DataFrame({
        "OPEN_PRICE":  [10.0, 11.2, 13.0],
        "HIGH_PRICE":  [11.0, 14.0, 15.0],
        "LOW_PRICE":   [9.5,  11.0, 12.5],
        "CLOSE_PRICE": [10.8, 13.8, 14.5],
        "TRADE_DATE": dates
    })

    fvg_detector = FairValueGapDetector(min_gap_pct=0.01)
    fvg_bull = fvg_detector.detect_fvg_at(df_bull, 2)

    assert fvg_bull is not None
    assert fvg_bull.direction == "BULLISH"
    assert fvg_bull.gap_low == 11.0
    assert fvg_bull.gap_high == 12.5
    assert fvg_bull.status == "UNTESTED"

    # Bearish FVG: C3 High < C1 Low
    # C1 Low = 20.0, C3 High = 18.0 -> Gap = [18.0, 20.0]
    df_bear = pd.DataFrame({
        "OPEN_PRICE":  [22.0, 19.5, 17.5],
        "HIGH_PRICE":  [23.0, 20.0, 18.0],
        "LOW_PRICE":   [20.0, 16.0, 15.0],
        "CLOSE_PRICE": [20.5, 17.0, 16.0],
        "TRADE_DATE": dates
    })
    fvg_bear = fvg_detector.detect_fvg_at(df_bear, 2)

    assert fvg_bear is not None
    assert fvg_bear.direction == "BEARISH"
    assert fvg_bear.gap_low == 18.0
    assert fvg_bear.gap_high == 20.0


def test_confluence_synthesizer_buy_signal():
    synthesizer = ConfluenceSynthesizer(entry_mode="zone_boundary", min_risk_reward=1.5)

    structure_state = {
        "has_two_structures": True,
        "trend": "BULLISH",
        "range_low": 50.0,
        "range_high": 70.0,
        "active_swing_low": 52.0,
        "active_swing_high": 70.0
    }

    dates = pd.date_range("2026-01-01", periods=3)
    df = pd.DataFrame({
        "OPEN_PRICE":  [50.0, 55.0, 59.0],
        "HIGH_PRICE":  [54.0, 65.0, 65.0],
        "LOW_PRICE":   [49.0, 54.0, 58.0],
        "CLOSE_PRICE": [53.0, 64.0, 63.0],
        "TRADE_DATE": dates
    })

    detector = ThreeCandlePatternDetector()
    pattern_res = detector.evaluate_pattern_at(df, 2)

    fvg_detector = FairValueGapDetector()
    fvg = fvg_detector.detect_fvg_at(df, 2)

    sig = synthesizer.evaluate_confluence(
        symbol="HPG",
        bar_idx=2,
        trade_date=dates[2],
        current_close=63.0,
        structure_state=structure_state,
        candle_pattern=pattern_res,
        fvg=fvg
    )

    assert sig is not None
    assert sig.signal_type == "BUY"
    assert sig.confluence_low == 54.0  # C1 High
    assert sig.confluence_high == 58.0 # C3 Low
    assert sig.limit_price == 58.0
    assert sig.stop_loss_price < 54.0
    assert sig.take_profit_price == 70.0
    assert sig.risk_reward_ratio >= 1.5
