"""
Comprehensive Unit Tests for Modular Architecture (Layer 1 & Layer 2 Separation).
Validates all 11 required test cases from Section 4:

1. Duplicate swings do not create duplicate structures.
2. Unconfirmed swings (confirmed_at > as_of_time) are not used.
3. Chronologically valid swing sequences produce stable, deterministic outputs.
4. Unmet conditions yield FORMING or UNCLEAR, never CONFIRMED.
5. Fewer than two confirmed structures yield INSUFFICIENT_STRUCTURE.
6. Last two confirmed structures must be strictly adjacent (cannot skip UNCLEAR/BROKEN).
7. Re-running on identical data with same rule_version yields 100% identical results.
8. Incremental swing-by-swing feeding produces identical closed structures to batch run.
9. User example verification: S1 DOWN (7->11), S2 UP (11->13), S3 UNCLEAR (13->17), S4 UP (17->20).
10. Round-trip save_swings/load_swings preserves data; Layer 2 runs from file; zero cross-layer imports.
11. Regression: new Layer 1 detector matches legacy detector on 15m October 2026 data.
"""

import sys
import ast
import tempfile
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

from common.models import Swing, MarketStructure
from common.io import save_swings, load_swings
from swing_detector import detect_swings, SwingDetectorConfig
from structure_builder import MarketStructureBuilder, RULE_VERSION


@pytest.fixture
def hpg_15m_candles():
    """Load cached 15-minute HPG candles."""
    csv_path = Path("data/hpg_15m_sample.csv")
    assert csv_path.exists(), "Sample 15m data must exist at data/hpg_15m_sample.csv"
    df = pd.read_csv(csv_path)
    return df


@pytest.fixture
def synthetic_swings_user_example():
    """
    Construct synthetic swings to reproduce the exact user example:
    - S1: 7 -> 11 | DOWN    | LH + LL
    - S2: 11 -> 13 | UP      | HH + HL
    - S3: 13 -> 17 | UNCLEAR | LH + LL xuất hiện sau HL
    - S4: 17 -> 20 | UP      | HH + HL + HH (FORMING)
    """
    swings: list[Swing] = []
    
    # Swings 1 to 6: initial setups
    # Alternating HIGH and LOW
    # Prices designed so that Step A produces:
    # 1: HIGH 100
    # 2: LOW 90
    # 3: HIGH 102 (HH)
    # 4: LOW 92 (HL)
    # 5: HIGH 105 (HH)
    # 6: LOW 95 (HL)
    # 7: HIGH 108 (HH) - S1 Start Anchor
    # 8: LOW 85 (LL)
    # 9: HIGH 98 (LH)
    # 10: LOW 80 (LL)
    # 11: HIGH 95 (LH) - S1 End / S2 Start Anchor
    # 12: LOW 96 (HL)
    # 13: HIGH 110 (HH) - S2 End / S3 Start Anchor
    # 14: LOW 92 (LL)
    # 15: HIGH 105 (LH)
    # 16: LOW 90 (LL)
    # 17: HIGH 102 (LH) - S3 End / S4 Start Anchor
    # 18: LOW 95 (HL)
    # 19: HIGH 115 (HH)
    # 20: LOW 98 (HL) - S4 End (still forming)
    
    # Construct exact sequence matching user example:
    # S1: 7 -> 11 | DOWN    | LH + LL
    # S2: 11 -> 13 | UP      | HH + HL
    # S3: 13 -> 17 | UNCLEAR | LH + LL xuất hiện sau HL
    # S4: 17 -> 20 | UP      | HH + HL + HH (FORMING)
    specs = [
        (6,  "HIGH", 100.0), # Initial High anchor
        (7,  "LOW",   90.0), # Initial Low anchor -> S1 Start Anchor (7)
        (8,  "HIGH",  95.0), # LH (BEAR)
        (9,  "LOW",   80.0), # LL (BEAR)
        (10, "HIGH",  90.0), # LH (BEAR)
        (11, "LOW",   75.0), # LL (BEAR) -> S1 end (11), S2 start
        (12, "HIGH", 105.0), # HH (BULL)
        (13, "LOW",   85.0), # HL (BULL) -> S2 end (13), S3 start
        (14, "HIGH",  98.0), # LH (BEAR)
        (15, "LOW",   78.0), # LL (BEAR)
        (16, "HIGH",  92.0), # LH (BEAR)
        (17, "LOW",   70.0), # LL (BEAR) -> S3 end (17), S4 start
        (18, "HIGH", 110.0), # HH (BULL)
        (19, "LOW",   88.0), # HL (BULL)
        (20, "HIGH", 115.0), # HH (BULL) -> S4 end (20)
    ]

    for stt, s_type, price in specs:
        t_str = f"2026-10-01 {stt:02d}:00:00"
        c_str = f"2026-10-01 {stt:02d}:45:00"
        swings.append(Swing(
            swing_id=stt,
            swing_type=s_type,
            extreme_price=price,
            extreme_time=t_str,
            confirmed_at=c_str,
            atr_at_extreme=1.0,
            threshold=2.0,
            source_timeframe="15m",
            lag_bars=3,
            vol_over_median=1.0,
            index=stt * 4,
            confirmed_at_index=stt * 4 + 3
        ))

    return swings


# --------------------------------------------------------------------------
# Test 1: Duplicate swings do not create duplicate structures
# --------------------------------------------------------------------------
def test_case_1_duplicate_swings_handled():
    builder = MarketStructureBuilder()
    swings = [
        Swing(1, "HIGH", 100.0, "2026-10-01 09:15:00", "2026-10-01 10:00:00", 1.0, 2.0),
        Swing(1, "HIGH", 100.0, "2026-10-01 09:15:00", "2026-10-01 10:00:00", 1.0, 2.0), # Duplicate ID
        Swing(2, "LOW",   90.0, "2026-10-01 10:15:00", "2026-10-01 11:00:00", 1.0, 2.0),
        Swing(3, "HIGH", 105.0, "2026-10-01 11:15:00", "2026-10-01 12:00:00", 1.0, 2.0),
    ]

    valid = builder.validate_swings(swings)
    assert len(valid) == 3
    assert any(log["reason_code"] == "DUPLICATE_SWING" for log in builder.validation_logs)


# --------------------------------------------------------------------------
# Test 2: Unconfirmed swings (confirmed_at > as_of_time) are not used
# --------------------------------------------------------------------------
def test_case_2_unconfirmed_swings_excluded():
    builder = MarketStructureBuilder()
    swings = [
        Swing(1, "HIGH", 100.0, "2026-10-01 09:15:00", "2026-10-01 10:00:00", 1.0, 2.0),
        Swing(2, "LOW",   90.0, "2026-10-01 10:15:00", "2026-10-01 11:00:00", 1.0, 2.0),
        Swing(3, "HIGH", 105.0, "2026-10-01 11:15:00", "2026-10-01 14:00:00", 1.0, 2.0), # Confirmed at 14:00
    ]

    # As of 11:30, swing 3 is not yet confirmed!
    used_swings, structs = builder.build(swings, as_of_time="2026-10-01 11:30:00")
    assert len(used_swings) == 2
    assert all(str(s.confirmed_at) <= "2026-10-01 11:30:00" for s in used_swings)


# --------------------------------------------------------------------------
# Test 3: Chronologically valid swing sequences produce stable outputs
# --------------------------------------------------------------------------
def test_case_3_stable_chronological_sequence(synthetic_swings_user_example):
    builder = MarketStructureBuilder()
    _, structs = builder.build(synthetic_swings_user_example)
    assert len(structs) > 0
    # Every structure must have start_swing_id < end_swing_id
    for st in structs:
        assert st.start_swing_id < st.end_swing_id


# --------------------------------------------------------------------------
# Test 4: Unmet conditions yield FORMING or UNCLEAR, never CONFIRMED
# --------------------------------------------------------------------------
def test_case_4_unmet_conditions_not_confirmed():
    builder = MarketStructureBuilder()
    # Create segment with only HH without HL
    swings = [
        Swing(1, "HIGH", 100.0, "2026-10-01 09:15:00", "2026-10-01 10:00:00", 1.0, 2.0),
        Swing(2, "LOW",   90.0, "2026-10-01 10:15:00", "2026-10-01 11:00:00", 1.0, 2.0),
        Swing(3, "HIGH", 110.0, "2026-10-01 11:15:00", "2026-10-01 12:00:00", 1.0, 2.0), # HH only
        Swing(4, "LOW",   80.0, "2026-10-01 12:15:00", "2026-10-01 13:00:00", 1.0, 2.0), # LL (BEAR)
        Swing(5, "HIGH",  95.0, "2026-10-01 13:15:00", "2026-10-01 14:00:00", 1.0, 2.0), # LH (BEAR)
    ]

    _, structs = builder.build(swings)
    # The first segment (from 2 to 3) has only HH -> not enough pairs -> UNCLEAR
    s1 = structs[0]
    assert s1.status == "UNCLEAR"
    assert s1.reason_code == "STRUCTURE_RULE_NOT_MET"


# --------------------------------------------------------------------------
# Test 5: Fewer than two confirmed structures yield INSUFFICIENT_STRUCTURE
# --------------------------------------------------------------------------
def test_case_5_insufficient_confirmed_structures():
    builder = MarketStructureBuilder()
    # Only 1 confirmed structure
    structs = [
        MarketStructure("S1", 1, 5, "UP", "CONFIRMED", "HH + HL"),
        MarketStructure("S2", 5, 8, "DOWN", "UNCLEAR", "STRUCTURE_RULE_NOT_MET")
    ]
    status, res = builder.get_last_two_confirmed(structs)
    assert status == "INSUFFICIENT_STRUCTURE"
    assert res is None


# --------------------------------------------------------------------------
# Test 6: Last two confirmed structures must be strictly adjacent
# --------------------------------------------------------------------------
def test_case_6_last_two_confirmed_must_be_adjacent():
    builder = MarketStructureBuilder()
    
    # Case A: An UNCLEAR structure lies between two CONFIRMED structures
    structs_with_gap = [
        MarketStructure("S1", 1, 5, "UP", "CONFIRMED", "HH + HL"),
        MarketStructure("S2", 5, 8, "DOWN", "UNCLEAR", "STRUCTURE_RULE_NOT_MET"),
        MarketStructure("S3", 8, 12, "UP", "CONFIRMED", "HH + HL"),
        MarketStructure("S4", 12, 15, "UP", "FORMING", "HH + HL")
    ]
    status, res = builder.get_last_two_confirmed(structs_with_gap)
    # The two most recent closed structures are S2 (UNCLEAR) and S3 (CONFIRMED) -> Not both CONFIRMED!
    assert status == "INSUFFICIENT_STRUCTURE"
    assert res is None

    # Case B: Two consecutive CONFIRMED structures
    structs_adjacent = [
        MarketStructure("S1", 1, 5, "DOWN", "UNCLEAR", "STRUCTURE_RULE_NOT_MET"),
        MarketStructure("S2", 5, 8, "UP", "CONFIRMED", "HH + HL"),
        MarketStructure("S3", 8, 12, "UP", "CONFIRMED", "HH + HL"),
        MarketStructure("S4", 12, 15, "UP", "FORMING", "HH + HL")
    ]
    status, res = builder.get_last_two_confirmed(structs_adjacent)
    assert status == "OK"
    assert res is not None
    assert res[0].structure_id == "S2"
    assert res[1].structure_id == "S3"


# --------------------------------------------------------------------------
# Test 7: Idempotency (Same data + same rule_version yields identical results)
# --------------------------------------------------------------------------
def test_case_7_idempotency(synthetic_swings_user_example):
    builder = MarketStructureBuilder()
    _, structs_1 = builder.build(synthetic_swings_user_example)
    _, structs_2 = builder.build(synthetic_swings_user_example)

    assert [s.to_dict() for s in structs_1] == [s.to_dict() for s in structs_2]


# --------------------------------------------------------------------------
# Test 8: Incremental swing feeding yields identical closed structures to batch run
# --------------------------------------------------------------------------
def test_case_8_incremental_consistency(synthetic_swings_user_example):
    builder = MarketStructureBuilder()
    # Batch run
    _, batch_structs = builder.build(synthetic_swings_user_example)
    batch_closed = [st.to_dict() for st in batch_structs if st.status != "FORMING"]

    # Incremental run
    incremental_closed = []
    for k in range(5, len(synthetic_swings_user_example) + 1):
        _, cur_structs = builder.build(synthetic_swings_user_example[:k])
        cur_closed = [st for st in cur_structs if st.status != "FORMING"]
        if cur_closed:
            latest = cur_closed[-1]
            if not any(x["structure_id"] == latest.structure_id for x in incremental_closed):
                incremental_closed.append(latest.to_dict())

    # Verify that all closed structures match in sequence and properties
    assert len(batch_closed) == len(incremental_closed)
    for b_st, i_st in zip(batch_closed, incremental_closed):
        assert b_st["structure_id"] == i_st["structure_id"]
        assert b_st["start_swing_id"] == i_st["start_swing_id"]
        assert b_st["end_swing_id"] == i_st["end_swing_id"]
        assert b_st["structure_type"] == i_st["structure_type"]
        assert b_st["main_evidence"] == i_st["main_evidence"]


# --------------------------------------------------------------------------
# Test 9: Exact user example verification
# S1 (7->11 DOWN LH+LL) / S2 (11->13 UP HH+HL) / S3 (13->17 UNCLEAR) / S4 (17->20 UP)
# --------------------------------------------------------------------------
def test_case_9_user_example_exact_match(synthetic_swings_user_example):
    builder = MarketStructureBuilder(bear_after_up_is_unclear=True)
    labelled_swings, structs = builder.build(synthetic_swings_user_example)

    # Find structures matching range 7 onwards
    s_map = {st.structure_id: st for st in structs}
    
    # We should have S1, S2, S3, S4
    assert len(structs) >= 4
    s1, s2, s3, s4 = structs[-4], structs[-3], structs[-2], structs[-1]

    # S1: 7 -> 11 | DOWN | LH + LL
    assert s1.start_swing_id == 7
    assert s1.end_swing_id == 11
    assert s1.structure_type == "DOWN"
    assert "LH + LL" in s1.main_evidence

    # S2: 11 -> 13 | UP | HH + HL
    assert s2.start_swing_id == 11
    assert s2.end_swing_id == 13
    assert s2.structure_type == "UP"
    assert "HH + HL" in s2.main_evidence

    # S3: 13 -> 17 | UNCLEAR | LH + LL xuất hiện sau HL
    assert s3.start_swing_id == 13
    assert s3.end_swing_id == 17
    assert s3.structure_type == "UNCLEAR"
    assert "LH + LL xuất hiện sau" in s3.main_evidence

    # S4: 17 -> 20 | UP | HH + HL + HH | FORMING
    assert s4.start_swing_id == 17
    assert s4.end_swing_id == 20
    assert s4.structure_type == "UP"
    assert s4.status == "FORMING"
    assert "HH + HL" in s4.main_evidence


# --------------------------------------------------------------------------
# Test 10: Round-trip save_swings/load_swings and zero cross-imports
# --------------------------------------------------------------------------
def test_case_10_round_trip_io_and_zero_cross_imports(synthetic_swings_user_example):
    # 1. Round-trip I/O
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp_csv = Path(tmp.name)
    try:
        save_swings(synthetic_swings_user_example, tmp_csv)
        loaded = load_swings(tmp_csv)
        assert len(loaded) == len(synthetic_swings_user_example)
        for orig, lod in zip(synthetic_swings_user_example, loaded):
            assert orig.swing_id == lod.swing_id
            assert orig.swing_type == lod.swing_type
            assert np.isclose(orig.extreme_price, lod.extreme_price)
            assert str(orig.extreme_time) == str(lod.extreme_time)
            assert str(orig.confirmed_at) == str(lod.confirmed_at)
            
        # Layer 2 can run directly from this file
        builder = MarketStructureBuilder()
        sw_file, st_file = builder.build_from_file(tmp_csv)
        assert len(sw_file) == len(synthetic_swings_user_example)
        assert len(st_file) > 0
    finally:
        if tmp_csv.exists():
            tmp_csv.unlink()

    # 2. Check zero cross-layer imports
    # Inspect AST of swing_detector and structure_builder files
    sd_files = list(Path("swing_detector").glob("*.py"))
    sb_files = list(Path("structure_builder").glob("*.py"))

    for f in sd_files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    assert "structure_builder" not in name.name, f"{f} imports from structure_builder!"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "structure_builder" not in node.module, f"{f} imports from structure_builder!"

    for f in sb_files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    assert "swing_detector" not in name.name, f"{f} imports from swing_detector!"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "swing_detector" not in node.module, f"{f} imports from swing_detector!"


# --------------------------------------------------------------------------
# Test 11: Regression: New Layer 1 detector matches legacy detector on 15m data
# --------------------------------------------------------------------------
def test_case_11_regression_vs_legacy_15m(hpg_15m_candles):
    from legacy.market_structure_legacy import MarketStructureTracker as LegacyTracker
    from legacy.market_structure_legacy import validate_and_clean_data as legacy_clean
    df = hpg_15m_candles.copy()
    if "Datetime" in df.columns and "TRADE_DATE" not in df.columns:
        df["TRADE_DATE"] = df["Datetime"]
    df_clean = legacy_clean(df)
    
    # Run legacy detector
    leg_tracker = LegacyTracker(swing_left=3, swing_right=3, reversal_mult=2.0, method="zigzag")
    leg_highs, leg_lows = leg_tracker.detect_swings(df_clean)
    leg_all = sorted(leg_highs + leg_lows, key=lambda s: s.index)

    # Run new modular detector
    cfg = SwingDetectorConfig(swing_left=3, swing_right=3, reversal_mult=2.0, timeframe="15m")
    new_swings = detect_swings(hpg_15m_candles, config=cfg)

    # Compare count
    assert len(new_swings) == len(leg_all), f"Count mismatch: new={len(new_swings)} vs legacy={len(leg_all)}"

    # Compare element by element
    for idx, (leg_s, new_s) in enumerate(zip(leg_all, new_swings), 1):
        assert leg_s.point_type == new_s.swing_type, f"Mismatch at #{idx}: type {leg_s.point_type} vs {new_s.swing_type}"
        assert np.isclose(leg_s.price, new_s.extreme_price), f"Mismatch at #{idx}: price {leg_s.price} vs {new_s.extreme_price}"
        assert leg_s.index == new_s.index, f"Mismatch at #{idx}: index {leg_s.index} vs {new_s.index}"
        assert leg_s.confirmed_at_index == new_s.confirmed_at_index, f"Mismatch at #{idx}: conf_index {leg_s.confirmed_at_index} vs {new_s.confirmed_at_index}"
        legacy_time = pd.Timestamp(leg_s.trade_date)
        # Legacy clean_data converts +07 source timestamps to UTC-naive numpy datetimes.
        if legacy_time.tzinfo is None:
            legacy_time = legacy_time.tz_localize("UTC")
        legacy_time = legacy_time.tz_convert("Asia/Ho_Chi_Minh").tz_localize(None)
        assert legacy_time == pd.Timestamp(new_s.extreme_time), f"Mismatch at #{idx}: time {legacy_time} vs {new_s.extreme_time}"
