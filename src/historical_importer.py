"""
Historical Importer Module.
Orchestrates downloading and storing full available historical price series
from Yahoo Finance into Oracle Database with state persistence, progress tracking,
and strict fault isolation.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import json
import uuid
from pathlib import Path
from src.config import settings
from src.import_logger import logger
from src.yfinance_client import YFinanceClient
from src.data_validator import DataValidator
from src.data_normalizer import DataNormalizer
from src.data_reporter import DataReporter


class HistoricalImporter:
    """Pipelines historical data fetching, validation, normalization, and database upsert."""

    def __init__(
        self,
        repository,
        yf_client: Optional[YFinanceClient] = None,
        batch_id: Optional[str] = None
    ):
        self.repo = repository
        self.yf_client = yf_client or YFinanceClient()
        self.batch_id = batch_id or f"HIST_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.state_file = settings.state_dir / "historical_progress_state.json"

    def _load_state(self) -> Dict[str, Any]:
        """Load resume state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load state file {self.state_file}: {e}")
        return {"processed_symbols": {}, "batch_id": self.batch_id}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """Persist resume state to disk."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save state file: {e}")

    def import_symbols(
        self,
        symbols_meta: List[Dict[str, Any]],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        resume: bool = True
    ) -> DataReporter:
        """
        Run historical import for a list of symbols.
        Fault-isolated: failure in one symbol does NOT stop the pipeline.
        """
        reporter = DataReporter(self.batch_id)
        state = self._load_state() if resume else {"processed_symbols": {}, "batch_id": self.batch_id}
        processed_set = set(state.get("processed_symbols", {}).keys()) if resume else set()

        total = len(symbols_meta)
        logger.info(
            f"Starting historical import batch [{self.batch_id}] for {total} symbols "
            f"(Resume mode: {resume}, Already processed: {len(processed_set)})"
        )

        # 1. Register/Upsert all symbols into repository first
        try:
            self.repo.upsert_symbols(symbols_meta)
        except Exception as e:
            logger.error(f"Failed to register symbols in database: {e}")

        # 2. Iterate each symbol
        for idx, item in enumerate(symbols_meta, 1):
            sym = item["symbol"]
            ticker = item.get("yahoo_ticker", f"{sym}.VN")
            exchange = item.get("exchange", "UNKNOWN")

            if resume and sym in processed_set:
                logger.info(f"[{idx}/{total}] Skipping already processed symbol: {sym}")
                continue

            start_ts = datetime.now(timezone.utc)
            logger.info(f"[{idx}/{total}] Processing {sym} ({ticker}) on {exchange}...")

            try:
                # Fetch data
                raw_df, err = self.yf_client.fetch_historical(
                    ticker,
                    period="max",
                    start=start_date,
                    end=end_date,
                    auto_adjust=False
                )

                if err is not None or raw_df is None or raw_df.empty:
                    end_ts = datetime.now(timezone.utc)
                    status = "NO_DATA" if "NO_DATA" in (err or "") or "NOT_FOUND" in (err or "") else "FAILED"
                    self.repo.log_import(
                        batch_id=self.batch_id,
                        symbol=sym,
                        task_type="HISTORICAL",
                        start_time=start_ts,
                        end_time=end_ts,
                        records_fetched=0,
                        records_inserted=0,
                        records_updated=0,
                        records_rejected=0,
                        status=status,
                        error_message=err
                    )
                    reporter.record_symbol_result(
                        symbol=sym,
                        yahoo_ticker=ticker,
                        exchange=exchange,
                        status=status,
                        records_fetched=0,
                        records_valid=0,
                        records_rejected=0,
                        error_message=err
                    )
                    state.setdefault("processed_symbols", {})[sym] = {"status": status, "records": 0}
                    self._save_state(state)
                    continue

                fetched_count = len(raw_df)

                # Validate
                valid_df, rejected_df, v_metrics = DataValidator.validate_dataframe(raw_df, sym)
                valid_count = len(valid_df)
                rejected_count = len(rejected_df)

                if valid_df.empty:
                    end_ts = datetime.now(timezone.utc)
                    err_msg = f"All {fetched_count} fetched records failed validation checks: {v_metrics['reasons']}"
                    self.repo.log_import(
                        batch_id=self.batch_id,
                        symbol=sym,
                        task_type="HISTORICAL",
                        start_time=start_ts,
                        end_time=end_ts,
                        records_fetched=fetched_count,
                        records_inserted=0,
                        records_updated=0,
                        records_rejected=rejected_count,
                        status="FAILED",
                        error_message=err_msg
                    )
                    reporter.record_symbol_result(
                        symbol=sym,
                        yahoo_ticker=ticker,
                        exchange=exchange,
                        status="FAILED",
                        records_fetched=fetched_count,
                        records_valid=0,
                        records_rejected=rejected_count,
                        error_message=err_msg
                    )
                    state.setdefault("processed_symbols", {})[sym] = {"status": "FAILED", "records": 0}
                    self._save_state(state)
                    continue

                # Normalize prices
                norm_df = DataNormalizer.normalize_prices_dataframe(valid_df, sym)
                price_tuples = DataNormalizer.to_oracle_price_tuples(norm_df)

                # Database Upsert
                affected, _ = self.repo.upsert_prices(price_tuples)

                # Fetch and normalize corporate events
                events_data = self.yf_client.fetch_corporate_events(ticker)
                norm_events = DataNormalizer.normalize_corporate_events(events_data, sym)
                if norm_events:
                    try:
                        self.repo.upsert_events(norm_events)
                    except Exception as e:
                        logger.warning(f"Could not upsert corporate events for {sym}: {e}")

                # Update symbol metadata dates
                earliest_d = norm_df["TRADE_DATE"].min()
                latest_d = norm_df["TRADE_DATE"].max()
                self.repo.update_symbol_sync_stats(sym, earliest_d, latest_d, datetime.now())

                end_ts = datetime.now(timezone.utc)
                status = "SUCCESS" if rejected_count == 0 else "PARTIAL"

                self.repo.log_import(
                    batch_id=self.batch_id,
                    symbol=sym,
                    task_type="HISTORICAL",
                    start_time=start_ts,
                    end_time=end_ts,
                    records_fetched=fetched_count,
                    records_inserted=affected,
                    records_updated=0,
                    records_rejected=rejected_count,
                    status=status,
                    error_message=f"Warnings: {v_metrics['warnings']}" if v_metrics["warnings"] > 0 else None
                )

                reporter.record_symbol_result(
                    symbol=sym,
                    yahoo_ticker=ticker,
                    exchange=exchange,
                    status=status,
                    records_fetched=fetched_count,
                    records_valid=valid_count,
                    records_rejected=rejected_count,
                    earliest_date=str(earliest_d),
                    latest_date=str(latest_d),
                    warnings_count=v_metrics["warnings"]
                )

                logger.info(
                    f"[{idx}/{total}] Successfully saved {sym}: {valid_count} valid records "
                    f"({earliest_d} -> {latest_d})"
                )

                state.setdefault("processed_symbols", {})[sym] = {
                    "status": status,
                    "records": valid_count,
                    "latest_date": str(latest_d)
                }
                self._save_state(state)

            except Exception as e:
                end_ts = datetime.now(timezone.utc)
                err_msg = f"Unexpected error processing {sym}: {e}"
                logger.error(err_msg, exc_info=True)
                self.repo.log_import(
                    batch_id=self.batch_id,
                    symbol=sym,
                    task_type="HISTORICAL",
                    start_time=start_ts,
                    end_time=end_ts,
                    records_fetched=0,
                    records_inserted=0,
                    records_updated=0,
                    records_rejected=0,
                    status="FAILED",
                    error_message=err_msg
                )
                reporter.record_symbol_result(
                    symbol=sym,
                    yahoo_ticker=ticker,
                    exchange=exchange,
                    status="FAILED",
                    records_fetched=0,
                    records_valid=0,
                    records_rejected=0,
                    error_message=err_msg
                )
                state.setdefault("processed_symbols", {})[sym] = {"status": "FAILED", "error": str(e)}
                self._save_state(state)

        # Export report and display summary
        reporter.export_reports()
        reporter.print_terminal_summary()
        return reporter
