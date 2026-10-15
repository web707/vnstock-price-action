"""
Incremental Updater Module.
Performs periodic data updates by querying recent days from LAST_DATA_DATE,
applying retro-active corrections safely with MERGE, and preserving full prior history.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta, timezone
import uuid
import pandas as pd
from src.config import settings
from src.import_logger import logger
from src.yfinance_client import YFinanceClient
from src.data_validator import DataValidator
from src.data_normalizer import DataNormalizer
from src.data_reporter import DataReporter


class IncrementalUpdater:
    """Synchronizes latest market prices without deleting old historical records."""

    def __init__(
        self,
        repository,
        yf_client: Optional[YFinanceClient] = None,
        batch_id: Optional[str] = None,
        lookback_buffer_days: int = 7
    ):
        self.repo = repository
        self.yf_client = yf_client or YFinanceClient()
        self.batch_id = batch_id or f"INC_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.lookback_buffer_days = lookback_buffer_days

    def update_symbols(
        self,
        symbols_meta: List[Dict[str, Any]],
        force_days_back: Optional[int] = None
    ) -> DataReporter:
        """
        Synchronize latest price data for specified symbols.
        Uses MERGE to update overlapping recent records and insert new records.
        """
        reporter = DataReporter(self.batch_id)
        total = len(symbols_meta)
        logger.info(f"Starting incremental update batch [{self.batch_id}] for {total} symbols...")

        for idx, item in enumerate(symbols_meta, 1):
            sym = item["symbol"]
            ticker = item.get("yahoo_ticker", f"{sym}.VN")
            exchange = item.get("exchange", "UNKNOWN")
            start_ts = datetime.now(timezone.utc)

            # 1. Determine start date from database metadata
            info = self.repo.get_symbol_sync_info(sym)
            last_date_val = info.get("last_data_date") if info else None

            if force_days_back:
                calc_start = (datetime.now().date() - timedelta(days=force_days_back)).isoformat()
            elif last_date_val:
                if isinstance(last_date_val, str):
                    last_d = datetime.strptime(last_date_val[:10], "%Y-%m-%d").date()
                elif hasattr(last_date_val, "date"):
                    last_d = last_date_val.date()
                else:
                    last_d = last_date_val
                # Subtract buffer days to capture retrospective adjustments
                calc_start = (last_d - timedelta(days=self.lookback_buffer_days)).isoformat()
            else:
                # No previous data, fetch max history
                calc_start = None

            logger.info(f"[{idx}/{total}] Updating {sym} from start date: {calc_start or 'MAX_HISTORY'}...")

            try:
                # 2. Fetch recent prices
                raw_df, err = self.yf_client.fetch_historical(
                    ticker,
                    period="1mo" if calc_start else "max",
                    start=calc_start,
                    auto_adjust=False
                )

                if err is not None or raw_df is None or raw_df.empty:
                    end_ts = datetime.now(timezone.utc)
                    status = "NO_DATA" if "NO_DATA" in (err or "") or "NOT_FOUND" in (err or "") else "FAILED"
                    self.repo.log_import(
                        batch_id=self.batch_id,
                        symbol=sym,
                        task_type="INCREMENTAL",
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
                    continue

                fetched_count = len(raw_df)

                # 3. Validate
                valid_df, rejected_df, v_metrics = DataValidator.validate_dataframe(raw_df, sym)
                valid_count = len(valid_df)
                rejected_count = len(rejected_df)

                if valid_df.empty:
                    end_ts = datetime.now(timezone.utc)
                    err_msg = f"All {fetched_count} incremental records failed validation: {v_metrics['reasons']}"
                    self.repo.log_import(
                        batch_id=self.batch_id,
                        symbol=sym,
                        task_type="INCREMENTAL",
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
                    continue

                # 4. Normalize and upsert
                norm_df = DataNormalizer.normalize_prices_dataframe(valid_df, sym)
                price_tuples = DataNormalizer.to_oracle_price_tuples(norm_df)
                affected, _ = self.repo.upsert_prices(price_tuples)

                # 5. Check events
                events_data = self.yf_client.fetch_corporate_events(ticker)
                norm_events = DataNormalizer.normalize_corporate_events(events_data, sym)
                if norm_events:
                    try:
                        self.repo.upsert_events(norm_events)
                    except Exception as e:
                        logger.warning(f"Could not upsert corporate events for {sym}: {e}")

                # Update metadata
                earliest_d = norm_df["TRADE_DATE"].min()
                latest_d = norm_df["TRADE_DATE"].max()
                self.repo.update_symbol_sync_stats(sym, earliest_d, latest_d, datetime.now())

                end_ts = datetime.now(timezone.utc)
                status = "SUCCESS" if rejected_count == 0 else "PARTIAL"

                self.repo.log_import(
                    batch_id=self.batch_id,
                    symbol=sym,
                    task_type="INCREMENTAL",
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

                logger.info(f"[{idx}/{total}] Incremental update complete for {sym}: {valid_count} records upserted.")

            except Exception as e:
                end_ts = datetime.now(timezone.utc)
                err_msg = f"Unexpected error in incremental update of {sym}: {e}"
                logger.error(err_msg, exc_info=True)
                self.repo.log_import(
                    batch_id=self.batch_id,
                    symbol=sym,
                    task_type="INCREMENTAL",
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

        reporter.export_reports()
        reporter.print_terminal_summary()
        return reporter
