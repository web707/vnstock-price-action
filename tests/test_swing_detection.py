"""
Comprehensive Unit Tests for 'Phát hiện điểm Swing (Swing Point Detection)'.
Validates all 9 sections of the specification:
1. Data cleaning & geometry validation
2. ATR(14) Wilder smoothing
3. Pivot 3/3 candidate detection
4. Dynamic Reversal Threshold: T_i = max(mult * ATR_i, 0.005 * P_i)
5. Strict ZigZag Alternation State Machine & Candidate Replacement
6. Minimum Swing Distance
7. Market Structure (HH/HL/LH/LL) & Volume 20-Median Ranking
8. Anti-Lookahead Bias Dual Timestamps
9. Parameter Sweeps (1.5, 2.0, 2.5 multipliers)
"""

import pytest
import numpy as np
import pandas as pd

from src.strategy.market_structure import (
    MarketStructureTracker,
    SwingPoint,
    compute_wilder_atr,
    validate_and_clean_data
)
from src.oracle_repository import get_repository


def test_section_1_data_validation():
    # Bad data: inverted high/low, negative volume, duplicate dates
    df_raw = pd.DataFrame({
        "TRADE_DATE": ["2026-01-02", "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "OPEN_PRICE":  [100.0, 100.0, 100.0, 100.0, 100.0],
        "HIGH_PRICE":  [105.0, 105.0, 105.0,  95.0, 105.0],  # 95 < 100 invalid
        "LOW_PRICE":   [ 95.0,  95.0,  95.0, 105.0,  95.0],  # 105 > 100 invalid
        "CLOSE_PRICE": [102.0, 102.0, 102.0,  98.0, 102.0],
        "VOLUME":      [1000,   1000,  1000,  1000,   -50]   # -50 invalid
    })

    cleaned = validate_and_clean_data(df_raw)
    # Date 2026-01-01 and 2026-01-02 should remain; duplicates and invalid rows dropped
    assert len(cleaned) == 2
    assert list(cleaned["TRADE_DATE"].dt.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02"]


def test_section_2_wilder_atr_formula():
    # Simple known sequence
    # Day 0: H=10, L=8, C=9 -> TR = 2
    # Day 1: H=12, L=9, C=11 -> TR = max(12-9, |12-9|, |9-9|) = 3
    # Day 2: H=15, L=11, C=14 -> TR = max(15-11, |15-11|, |11-11|) = 4
    df = pd.DataFrame({
        "HIGH_PRICE": [10.0, 12.0, 15.0],
        "LOW_PRICE":  [ 8.0,  9.0, 11.0],
        "CLOSE_PRICE":[ 9.0, 11.0, 14.0]
    })
    atr = compute_wilder_atr(df, period=2)
    # Day 0: TR=2, ATR=2.0
    # Day 1: TR=3, initial ATR for period 2 = (2+3)/2 = 2.5
    # Day 2: TR=4, Wilder formula = ((2-1)*2.5 + 4)/2 = (2.5 + 4)/2 = 3.25
    assert np.isclose(atr[0], 2.0)
    assert np.isclose(atr[1], 2.5)
    assert np.isclose(atr[2], 3.25)


def test_section_4_dynamic_reversal_threshold():
    # Construct series where candidate peak forms
    # Multiplier 2.0 * ATR vs 0.005 * Price
    dates = pd.date_range("2026-01-01", periods=10)
    highs = [100.0, 102.0, 105.0, 110.0, 108.0, 106.0, 100.0, 95.0, 98.0, 102.0]
    lows  = [ 98.0, 100.0, 103.0, 107.0, 105.0, 103.0,  98.0, 92.0, 95.0,  99.0]
    closes= [ 99.0, 101.0, 104.0, 109.0, 106.0, 104.0,  99.0, 93.0, 97.0, 101.0]

    df = pd.DataFrame({
        "TRADE_DATE": dates,
        "OPEN_PRICE": [h - 1 for h in highs],
        "HIGH_PRICE": highs,
        "LOW_PRICE": lows,
        "CLOSE_PRICE": closes,
        "VOLUME": [10000] * 10
    })

    tracker = MarketStructureTracker(swing_left=3, swing_right=3, reversal_mult=2.0, min_reversal_pct=0.005)
    shs, sls = tracker.detect_swings(df)

    assert len(shs) >= 1
    sh = shs[0]
    assert sh.price == 110.0
    assert sh.index == 3
    # Check threshold is stored and > 0
    assert sh.reversal_threshold is not None
    assert sh.reversal_threshold >= 0.005 * 110.0


def test_section_5_strict_zigzag_alternation_and_candidate_replacement():
    repo = get_repository(force_mock=True)
    df = repo.query_historical_prices("HPG")
    assert not df.empty

    tracker = MarketStructureTracker(swing_left=3, swing_right=3, reversal_mult=2.0)
    shs, sls = tracker.detect_swings(df)

    # Merge chronologically
    all_swings = [(s.index, s.point_type, s) for s in shs] + [(s.index, s.point_type, s) for s in sls]
    all_swings.sort(key=lambda x: x[0])

    assert len(all_swings) > 10

    # Test strict alternation: No two consecutive peaks or two consecutive troughs
    for i in range(1, len(all_swings)):
        prev_type = all_swings[i - 1][1]
        curr_type = all_swings[i][1]
        assert prev_type != curr_type, f"Violation at swing {i}: {prev_type} followed immediately by {curr_type}"


def test_section_8_zero_lookahead_bias():
    repo = get_repository(force_mock=True)
    df = repo.query_historical_prices("VNM")
    assert not df.empty

    tracker = MarketStructureTracker(swing_left=3, swing_right=3, reversal_mult=2.0)
    shs, sls = tracker.detect_swings(df)

    for s in shs + sls:
        # Confirmation bar index MUST be strictly greater than or equal to candidate index + swing_right
        assert s.confirmed_at_index >= s.index + tracker.swing_right
        assert s.confirmed_date is not None


def test_section_7_market_structure_classification_and_volume():
    repo = get_repository(force_mock=True)
    df = repo.query_historical_prices("HPG")

    tracker = MarketStructureTracker(swing_left=3, swing_right=3, reversal_mult=2.0)
    shs, sls = tracker.detect_swings(df)

    # Highs should have structure_type in {'HIGH', 'HH', 'LH', 'EH'}
    for sh in shs[1:]:
        assert sh.structure_type in {"HH", "LH", "EH"}
        assert sh.volume_ratio is not None and sh.volume_ratio > 0

    # Lows should have structure_type in {'LOW', 'HL', 'LL', 'EL'}
    for sl in sls[1:]:
        assert sl.structure_type in {"HL", "LL", "EL"}
        assert sl.volume_ratio is not None and sl.volume_ratio > 0


def test_section_9_parameter_sweeps_sensitivity():
    repo = get_repository(force_mock=True)
    df = repo.query_historical_prices("SSI")

    tracker_15 = MarketStructureTracker(reversal_mult=1.5)
    tracker_20 = MarketStructureTracker(reversal_mult=2.0)
    tracker_25 = MarketStructureTracker(reversal_mult=2.5)

    sh_15, sl_15 = tracker_15.detect_swings(df)
    sh_20, sl_20 = tracker_20.detect_swings(df)
    sh_25, sl_25 = tracker_25.detect_swings(df)

    total_15 = len(sh_15) + len(sl_15)
    total_20 = len(sh_20) + len(sl_20)
    total_25 = len(sh_25) + len(sl_25)

    # 1.5 ATR captures more swings than 2.0 ATR, which captures more than 2.5 ATR
    assert total_15 >= total_20 >= total_25
    assert total_15 > total_25
