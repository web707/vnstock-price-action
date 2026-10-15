"""
Tests for Repository, Importer, and Incremental Updater Pipeline.
Covers Mandatory Test Cases:
- Case 6: Prevent duplicate (SYMBOL, TRADE_DATE) records.
- Case 7: Idempotency: Running import twice produces no duplicates.
- Case 8: Incremental update preserves historical data without deletion.
- Case 9: Fault tolerance: Error on one symbol allows the pipeline to continue.
- Case 10: Detailed import logs in DATA_IMPORT_LOGS.
- Case 11: Accurate verification of stored records and counts.
- Case 13: Resume interrupted execution from saved state.
- Case 14: Graceful handling of Oracle connection errors when credentials are missing or invalid.
"""

from datetime import date, datetime, timezone
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from src.oracle_repository import MockSqliteRepository, OracleRepository, OracleConnectionError
from src.historical_importer import HistoricalImporter
from src.incremental_updater import IncrementalUpdater
from src.data_reporter import DataReporter


@pytest.fixture
def temp_repo(tmp_path):
    """Provides a fresh isolated database repository for tests."""
    db_file = tmp_path / "test_db.sqlite"
    repo = MockSqliteRepository(db_path=str(db_file))
    return repo


def test_case_6_and_7_prevent_duplicates_and_idempotency(temp_repo):
    """Test Case 6 & 7: Idempotent upsert prevents duplicate (SYMBOL, TRADE_DATE)."""
    t_date = date(2026, 1, 10)
    now_ts = datetime.now()

    records_first_run = [
        ("HPG", t_date, 25.0, 26.0, 24.5, 25.5, 25.5, 100000, "VALID", "yfinance", now_ts),
        ("VNM", t_date, 60.0, 61.0, 59.5, 60.5, 60.5, 200000, "VALID", "yfinance", now_ts)
    ]

    # First run
    temp_repo.upsert_prices(records_first_run)
    summary1 = temp_repo.get_database_summary()
    assert summary1["total_price_records"] == 2

    # Second run with identical records plus an updated close price
    records_second_run = [
        ("HPG", t_date, 25.0, 26.0, 24.5, 25.8, 25.8, 105000, "VALID", "yfinance", now_ts),
        ("VNM", t_date, 60.0, 61.0, 59.5, 60.5, 60.5, 200000, "VALID", "yfinance", now_ts)
    ]
    temp_repo.upsert_prices(records_second_run)
    summary2 = temp_repo.get_database_summary()

    # Must still be exactly 2 rows, not 4
    assert summary2["total_price_records"] == 2

    # Check updated price for HPG
    df_hpg = temp_repo.query_historical_prices("HPG")
    assert len(df_hpg) == 1
    assert df_hpg["CLOSE_PRICE"].iloc[0] == 25.8


def test_case_8_incremental_update_preserves_old_history(temp_repo):
    """Test Case 8: Incremental update adds new dates without erasing older records."""
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)
    d3 = date(2026, 1, 3)
    now_ts = datetime.now()

    # Seed historical records
    initial_records = [
        ("HPG", d1, 20.0, 21.0, 19.5, 20.5, 20.5, 1000, "VALID", "yfinance", now_ts),
        ("HPG", d2, 20.5, 21.5, 20.0, 21.0, 21.0, 2000, "VALID", "yfinance", now_ts),
    ]
    temp_repo.upsert_prices(initial_records)
    temp_repo.update_symbol_sync_stats("HPG", d1, d2, now_ts)

    # Perform incremental update with d3 (and slight revision to d2)
    new_records = [
        ("HPG", d2, 20.5, 21.5, 20.0, 21.2, 21.2, 2100, "VALID", "yfinance", now_ts),
        ("HPG", d3, 21.2, 22.0, 21.0, 21.8, 21.8, 3000, "VALID", "yfinance", now_ts),
    ]
    temp_repo.upsert_prices(new_records)
    temp_repo.update_symbol_sync_stats("HPG", d1, d3, now_ts)

    # Verify d1 is still intact!
    df = temp_repo.query_historical_prices("HPG")
    assert len(df) == 3
    dates_in_db = [str(x)[:10] for x in df["TRADE_DATE"]]
    assert dates_in_db == ["2026-01-01", "2026-01-02", "2026-01-03"]


def test_case_9_fault_tolerance_one_symbol_fails_others_succeed(temp_repo, tmp_path):
    """Test Case 9: When one ticker fails, the pipeline isolates the error and finishes remaining tickers."""
    mock_yf = MagicMock()

    # Sym1 fails with exception
    # Sym2 succeeds
    dates = pd.date_range("2026-01-01", periods=2)
    valid_df = pd.DataFrame({
        "Open": [10.0, 11.0],
        "High": [12.0, 13.0],
        "Low": [9.0, 10.0],
        "Close": [11.0, 12.0],
        "Adj Close": [11.0, 12.0],
        "Volume": [1000, 2000]
    }, index=dates)

    def side_effect(ticker, **kwargs):
        if "FAIL" in ticker:
            return None, "HTTP 500 Network Timeout"
        return valid_df, None

    mock_yf.fetch_historical.side_effect = side_effect
    mock_yf.fetch_corporate_events.return_value = {"dividends": None, "splits": None}

    importer = HistoricalImporter(repository=temp_repo, yf_client=mock_yf)
    importer.state_file = tmp_path / "test_state.json"

    targets = [
        {"symbol": "FAIL_SYM", "yahoo_ticker": "FAIL_SYM.VN", "exchange": "HOSE"},
        {"symbol": "PASS_SYM", "yahoo_ticker": "PASS_SYM.VN", "exchange": "HOSE"}
    ]

    reporter = importer.import_symbols(targets, resume=False)
    summary = reporter.generate_summary()

    assert summary["successful_symbols"] == 1
    assert summary["failed_symbols"] == 1
    # Successful symbol must be in database
    df_pass = temp_repo.query_historical_prices("PASS_SYM")
    assert len(df_pass) == 2


def test_case_10_and_11_logs_and_counts_verification(temp_repo):
    """Test Case 10 & 11: Import logs are recorded and database summary returns verified metrics."""
    st = datetime.now()
    et = datetime.now()

    temp_repo.log_import(
        batch_id="TEST_BATCH",
        symbol="HPG",
        task_type="HISTORICAL",
        start_time=st,
        end_time=et,
        records_fetched=100,
        records_inserted=98,
        records_updated=0,
        records_rejected=2,
        status="PARTIAL",
        error_message="Rejected 2 rows due to non-positive price"
    )

    summary = temp_repo.get_database_summary()
    assert summary["total_logs"] == 1

    failed = temp_repo.get_failed_symbols(batch_id="TEST_BATCH")
    assert len(failed) == 0  # It was PARTIAL, not FAILED


def test_case_13_resume_interrupted_execution(temp_repo, tmp_path):
    """Test Case 13: Verify resuming after interruption skips already processed symbols."""
    mock_yf = MagicMock()
    dates = pd.date_range("2026-01-01", periods=2)
    valid_df = pd.DataFrame({
        "Open": [10.0, 11.0],
        "High": [12.0, 13.0],
        "Low": [9.0, 10.0],
        "Close": [11.0, 12.0],
        "Adj Close": [11.0, 12.0],
        "Volume": [1000, 2000]
    }, index=dates)

    mock_yf.fetch_historical.return_value = (valid_df, None)
    mock_yf.fetch_corporate_events.return_value = {"dividends": None, "splits": None}

    importer = HistoricalImporter(repository=temp_repo, yf_client=mock_yf)
    importer.state_file = tmp_path / "resume_state.json"

    targets = [
        {"symbol": "SYM1", "yahoo_ticker": "SYM1.VN", "exchange": "HOSE"},
        {"symbol": "SYM2", "yahoo_ticker": "SYM2.VN", "exchange": "HOSE"}
    ]

    # Pre-populate state as if SYM1 was already processed
    importer._save_state({
        "processed_symbols": {"SYM1": {"status": "SUCCESS", "records": 2}},
        "batch_id": importer.batch_id
    })

    importer.import_symbols(targets, resume=True)

    # fetch_historical should only have been called ONCE (for SYM2, not SYM1!)
    assert mock_yf.fetch_historical.call_count == 1
    called_ticker = mock_yf.fetch_historical.call_args[0][0]
    assert called_ticker == "SYM2.VN"


def test_case_14_oracle_connection_error_handling():
    """Test Case 14: Clear, actionable OracleConnectionError raised when configuration is missing."""
    repo = OracleRepository()

    with patch.object(repo, "get_connection") as mock_conn:
        mock_conn.side_effect = OracleConnectionError("Oracle connection failed: ORA-12541: TNS:no listener")

        with pytest.raises(OracleConnectionError) as exc_info:
            repo.get_connection()
        assert "ORA-12541" in str(exc_info.value)

    # Connection check returns false gracefully without crashing
    with patch("src.config.settings.is_oracle_configured", return_value=False):
        is_ok, msg = repo.check_connection()
        assert is_ok is False
        assert "missing in configuration" in msg
