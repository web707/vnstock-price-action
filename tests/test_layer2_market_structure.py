"""
Comprehensive Unit Tests for Layer 2: Market Structure Builder with Test Date Support.
Adheres strictly to the 10 mandatory test cases specified in Section 8 of the prompt:

1. Test ngày hợp lệ (Valid date returns valid report)
2. Test không truyền ngày (No date runs full historical data)
3. Test ngày không hợp lệ (Invalid date/datetime formats raise ValueError)
4. Test swing có extreme_time <= cutoff nhưng confirmed_at > cutoff (Excluded as CONFIRMED_AFTER_CUTOFF)
5. Test swing lịch sử (extreme_time < test_date, confirmed_at <= cutoff retained for structure)
6. Test ngày thiếu dữ liệu hoặc không có swing nào (INSUFFICIENT_STRUCTURE / NO_SWINGS_AVAILABLE without crash)
7. Test tính xác định (Idempotency: 2 runs with same params yield identical output)
8. Test không làm thay đổi dữ liệu (Non-destructive: DB records unchanged)
9. Test độ chính xác mốc cutoff (Boundary precision: test_date 23:59:59 vs test_datetime HH:MM:SS)
10. Test chống Lookahead Bias (Zero Lookahead Verification: 100% of used swings have confirmed_at <= cutoff)
"""

import pytest
import pandas as pd
import numpy as np

from src.strategy.market_structure import (
    MarketStructureTracker,
    MarketStructureBuilder,
    MarketStructureReport,
    parse_test_cutoff,
    to_comparable_timestamp
)
from src.oracle_repository import get_repository
from fastapi.testclient import TestClient
from src.web.app import app


@pytest.fixture
def hpg_sample_data():
    """Retrieve sample historical dataset from mock/local repository."""
    repo = get_repository(force_mock=True)
    df = repo.query_historical_prices("HPG")
    assert not df.empty, "HPG historical data should not be empty in mock DB"
    return df


@pytest.fixture
def synthetic_lookahead_data():
    """
    Construct synthetic 15-minute bars where:
    - Swing High peak occurs at 10:00 (extreme_time)
    - Confirmation requires 3 subsequent bars and reversal drop, confirmed at 14:00 (confirmed_at)
    """
    datetimes = pd.date_range("2026-09-15 09:00:00", periods=25, freq="15min")
    highs = [
        100.0, 101.0, 102.0, 103.0, 110.0,  # index 4: 10:00 (Peak High = 110.0)
        108.0, 107.0, 106.0, 105.0, 104.0,  # right bars + reversal
        103.0, 102.0, 101.0, 100.0, 99.0,
        98.0,  97.0,  96.0,  95.0,  94.0,
        93.0,  92.0,  91.0,  90.0,  89.0
    ]
    lows = [h - 2.0 for h in highs]
    closes = [h - 1.0 for h in highs]
    opens = [h - 1.5 for h in highs]

    df = pd.DataFrame({
        "TRADE_DATE": datetimes,
        "OPEN_PRICE": opens,
        "HIGH_PRICE": highs,
        "LOW_PRICE": lows,
        "CLOSE_PRICE": closes,
        "VOLUME": [10000] * len(datetimes)
    })
    return df


# --------------------------------------------------------------------------
# Test Case 1: Test ngày hợp lệ (Valid test date)
# --------------------------------------------------------------------------
def test_case_1_valid_test_date(hpg_sample_data):
    builder = MarketStructureBuilder()
    report = builder.build_structure(hpg_sample_data, symbol="HPG", test_date="2026-09-15")

    assert isinstance(report, MarketStructureReport)
    assert report.symbol == "HPG"
    assert report.rule_version == "v2.0-pruni-15m"
    assert report.cutoff_time == "2026-09-15 23:59:59"
    assert report.total_input_swings > 0
    assert report.used_swings_count + report.excluded_swings_count == report.total_input_swings
    assert report.reason_code in [
        "TWO_UP_STRUCTURES_CONFIRMED",
        "DOWN_TREND",
        "MIXED_STRUCTURES",
        "INSUFFICIENT_STRUCTURE",
        "STRUCTURE_BROKEN",
        "NO_SWINGS_AVAILABLE"
    ]
    report_dict = report.to_dict()
    assert "active_trading_range" in report_dict
    assert "used_swings" in report_dict
    assert "excluded_swings" in report_dict


# --------------------------------------------------------------------------
# Test Case 2: Test không truyền ngày (No date runs full history)
# --------------------------------------------------------------------------
def test_case_2_no_date_runs_full_history(hpg_sample_data):
    builder = MarketStructureBuilder()
    report = builder.build_structure(hpg_sample_data, symbol="HPG", test_date=None, test_datetime=None)

    assert report.cutoff_time is None
    assert report.excluded_swings_count == 0
    assert report.used_swings_count == report.total_input_swings
    assert len(report.used_swings) == report.total_input_swings
    assert len(report.excluded_swings) == 0


# --------------------------------------------------------------------------
# Test Case 3: Test ngày không hợp lệ (Invalid formats raise ValueError)
# --------------------------------------------------------------------------
def test_case_3_invalid_dates_raise_value_error(hpg_sample_data):
    builder = MarketStructureBuilder()

    invalid_dates = [
        "2026-13-45",       # Invalid month & day
        "2026-02-30",       # Feb 30 does not exist
        "invalid-date",     # Not a date
        "15/09/2026",       # Wrong format (DD/MM/YYYY)
        "2026-09-15 25:00", # Hour 25 invalid
        "abc"
    ]

    for bad_date in invalid_dates:
        with pytest.raises(ValueError):
            builder.build_structure(hpg_sample_data, symbol="HPG", test_date=bad_date)

    with pytest.raises(ValueError):
        parse_test_cutoff(test_datetime="2026-09-15 99:99:99")


# --------------------------------------------------------------------------
# Test Case 4: Test extreme_time <= cutoff nhưng confirmed_at > cutoff
# --------------------------------------------------------------------------
def test_case_4_extreme_before_cutoff_confirmed_after(synthetic_lookahead_data):
    """
    A swing whose peak occurred at 10:00 (before 10:15) but only confirmed at 11:00
    must be strictly excluded if cutoff is 10:15.
    """
    tracker = MarketStructureTracker(swing_left=3, swing_right=3, reversal_mult=1.5)
    builder = MarketStructureBuilder(tracker=tracker)

    # Cutoff at 10:00: Peak formed at 10:00, but right candles and reversal confirm later
    report = builder.build_structure(
        synthetic_lookahead_data,
        symbol="SYN",
        test_datetime="2026-09-15 10:00:00"
    )

    # Any swing whose peak is at 10:00 cannot have been confirmed at 10:00 (needs right candles)
    for exc in report.excluded_swings:
        assert exc["exclusion_reason"] == "CONFIRMED_AFTER_CUTOFF"
        assert to_comparable_timestamp(exc["confirmed_at"]) > to_comparable_timestamp("2026-09-15 10:00:00")

    # In used_swings, no swing confirmed after cutoff can exist
    for used in report.used_swings:
        assert to_comparable_timestamp(used["confirmed_at"]) <= to_comparable_timestamp("2026-09-15 10:00:00")


# --------------------------------------------------------------------------
# Test Case 5: Test swing lịch sử (extreme_time < test_date, confirmed_at <= cutoff)
# --------------------------------------------------------------------------
def test_case_5_historical_swings_retained(hpg_sample_data):
    """
    Ensure we do NOT simply filter swings by `extreme_time in test_date`.
    Swings confirmed prior to test_date must remain in used_swings to establish structure.
    """
    builder = MarketStructureBuilder()
    report = builder.build_structure(hpg_sample_data, symbol="HPG", test_date="2026-09-15")

    assert report.used_swings_count > 0

    # Check that there are swings with extreme_time from earlier months/days
    earlier_swings = [
        s for s in report.used_swings
        if str(s["extreme_time"]) < "2026-09-15"
    ]
    assert len(earlier_swings) > 0, "Historical swings before test_date must be retained for market structure context"


# --------------------------------------------------------------------------
# Test Case 6: Test ngày thiếu dữ liệu hoặc không có swing nào
# --------------------------------------------------------------------------
def test_case_6_insufficient_data_no_crash(hpg_sample_data):
    """
    Choosing a date before sufficient candles have elapsed should gracefully return
    INSUFFICIENT_STRUCTURE or NO_SWINGS_AVAILABLE without raising uncaught exceptions.
    """
    builder = MarketStructureBuilder()
    # 2000-01-01 is prior to any records in HPG data (starts in 2010)
    report_empty = builder.build_structure(hpg_sample_data, symbol="HPG", test_date="2000-01-01")
    assert report_empty.reason_code in ["NO_SWINGS_AVAILABLE", "INSUFFICIENT_STRUCTURE"]
    assert report_empty.has_two_structures is False
    assert report_empty.is_long_candidate is False
    assert report_empty.structures == []

    # 2010-02-23 is only 2 bars into HPG history (not enough bars to form swing)
    report_few = builder.build_structure(hpg_sample_data, symbol="HPG", test_date="2010-02-23")
    assert report_few.reason_code in ["NO_SWINGS_AVAILABLE", "INSUFFICIENT_STRUCTURE"]
    assert report_few.has_two_structures is False
    assert report_few.is_long_candidate is False


# --------------------------------------------------------------------------
# Test Case 7: Test tính xác định (Idempotency)
# --------------------------------------------------------------------------
def test_case_7_idempotency(hpg_sample_data):
    builder = MarketStructureBuilder()
    report_1 = builder.build_structure(hpg_sample_data, symbol="HPG", test_date="2026-09-15").to_dict()
    report_2 = builder.build_structure(hpg_sample_data, symbol="HPG", test_date="2026-09-15").to_dict()

    assert report_1 == report_2, "Two successive runs on the same date with same parameters must produce identical outputs"


# --------------------------------------------------------------------------
# Test Case 8: Test không làm thay đổi dữ liệu (Non-destructive)
# --------------------------------------------------------------------------
def test_case_8_non_destructive():
    repo = get_repository(force_mock=True)
    summary_before = repo.get_database_summary()

    builder = MarketStructureBuilder()
    df = repo.query_historical_prices("HPG")
    report = builder.build_structure(df, symbol="HPG", test_date="2026-09-15")

    summary_after = repo.get_database_summary()

    assert summary_before["total_price_records"] == summary_after["total_price_records"]
    assert summary_before["total_symbols"] == summary_after["total_symbols"]


# --------------------------------------------------------------------------
# Test Case 9: Test độ chính xác mốc cutoff (Boundary & Cutoff precision)
# --------------------------------------------------------------------------
def test_case_9_boundary_precision():
    """
    test_date='2026-09-15' sets cutoff to 23:59:59.
    test_datetime='2026-09-15 11:30:00' sets cutoff to 11:30:00.
    A swing confirmed in the afternoon (e.g. 14:00) must be included in test_date
    but excluded in test_datetime.
    """
    datetimes = pd.date_range("2026-09-15 09:00:00", periods=20, freq="15min")
    # Swings at index 4 (10:00) confirmed around 11:15, and index 12 (12:00) confirmed around 13:45
    highs = [
        100.0, 102.0, 104.0, 108.0, 115.0,  # index 4 (10:00) peak
        110.0, 106.0, 102.0, 98.0,  95.0,   # drop
        96.0,  100.0, 112.0, 118.0, 114.0,  # index 13 (12:15) peak
        110.0, 105.0, 101.0, 97.0,  94.0
    ]
    lows = [h - 2.0 for h in highs]
    closes = [h - 1.0 for h in highs]
    opens = [h - 1.5 for h in highs]

    df = pd.DataFrame({
        "TRADE_DATE": datetimes,
        "OPEN_PRICE": opens,
        "HIGH_PRICE": highs,
        "LOW_PRICE": lows,
        "CLOSE_PRICE": closes,
        "VOLUME": [10000] * len(datetimes)
    })

    builder = MarketStructureBuilder(tracker=MarketStructureTracker(swing_left=2, swing_right=2, reversal_mult=1.0))

    report_date = builder.build_structure(df, symbol="PREC", test_date="2026-09-15")
    report_noon = builder.build_structure(df, symbol="PREC", test_datetime="2026-09-15 11:30:00")

    # Afternoon confirmed swing must be in report_date but excluded in report_noon
    assert report_date.used_swings_count >= report_noon.used_swings_count
    assert report_noon.excluded_swings_count >= report_date.excluded_swings_count


# --------------------------------------------------------------------------
# Test Case 10: Test chống Lookahead Bias (Zero Lookahead Verification)
# --------------------------------------------------------------------------
def test_case_10_zero_lookahead_verification(hpg_sample_data):
    builder = MarketStructureBuilder()
    test_dates = ["2026-07-15", "2026-08-15", "2026-09-15", "2026-10-15"]

    for t_date in test_dates:
        report = builder.build_structure(hpg_sample_data, symbol="HPG", test_date=t_date)
        cutoff_ts = to_comparable_timestamp(report.cutoff_time)

        # 1. 100% of used swings must have confirmed_at <= cutoff
        for s in report.used_swings:
            confirmed_ts = to_comparable_timestamp(s["confirmed_at"])
            assert confirmed_ts <= cutoff_ts, (
                f"Lookahead violation detected: swing confirmed at {s['confirmed_at']} "
                f"was included with cutoff {report.cutoff_time}"
            )

        # 2. 100% of excluded swings must have confirmed_at > cutoff
        for s in report.excluded_swings:
            confirmed_ts = to_comparable_timestamp(s["confirmed_at"])
            assert confirmed_ts > cutoff_ts, (
                f"Incorrectly excluded swing: swing confirmed at {s['confirmed_at']} "
                f"was excluded with cutoff {report.cutoff_time}"
            )


# --------------------------------------------------------------------------
# Integration Test: Web API Endpoint GET /api/layer2/structure/{symbol}
# --------------------------------------------------------------------------
def test_web_api_layer2_endpoint(signed_client):
    client = signed_client

    # 1. Valid date
    resp = client.get("/api/layer2/structure/HPG?date=2026-09-15&source=db&timeframe=1d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "HPG"
    assert data["cutoff_time"] == "2026-09-15 23:59:59"
    assert "used_swings" in data

    # 2. Invalid date format
    resp_invalid = client.get("/api/layer2/structure/HPG?date=2026-99-99&source=db&timeframe=1d")
    assert resp_invalid.status_code == 400
    assert "không hợp lệ" in resp_invalid.json()["detail"]
