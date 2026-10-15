"""
Yahoo Finance Client Module.
Wraps yfinance with robust rate limiting, exponential backoff, schema normalization,
and comprehensive error classification for Vietnam stock tickers.
"""

import time
import random
from typing import Optional, Tuple, Dict, Any
import pandas as pd
import yfinance as yf
from src.config import settings
from src.import_logger import logger


class YFinanceClient:
    """Client for fetching Vietnam market data from Yahoo Finance."""

    def __init__(
        self,
        request_delay: Optional[float] = None,
        max_retries: Optional[int] = None,
        backoff_factor: Optional[float] = None
    ):
        self.request_delay = request_delay if request_delay is not None else settings.yfinance_request_delay_sec
        self.max_retries = max_retries if max_retries is not None else settings.max_retries
        self.backoff_factor = backoff_factor if backoff_factor is not None else settings.retry_backoff_factor

    def _sleep_with_jitter(self) -> None:
        """Introduce polite delay with random jitter to avoid burst queries."""
        if self.request_delay > 0:
            jitter = random.uniform(0.05, 0.15)
            time.sleep(self.request_delay + jitter)

    def fetch_historical(
        self,
        ticker: str,
        period: str = "max",
        start: Optional[str] = None,
        end: Optional[str] = None,
        auto_adjust: bool = False
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        Fetch historical price data for a ticker with automatic retries and backoff.

        Returns:
            Tuple[Optional[pd.DataFrame], Optional[str]]: (DataFrame, error_message)
            If successful: (df, None)
            If failed/not found: (None, error_reason)
        """
        clean_ticker = ticker.strip().upper()
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                self._sleep_with_jitter()
                yf_ticker = yf.Ticker(clean_ticker)

                # Fetch history
                kwargs: Dict[str, Any] = {"auto_adjust": auto_adjust}
                if start or end:
                    if start:
                        kwargs["start"] = start
                    if end:
                        kwargs["end"] = end
                else:
                    kwargs["period"] = period

                df = yf_ticker.history(**kwargs)

                if df is None or df.empty:
                    return None, f"NO_DATA: Yahoo Finance returned 0 records for {clean_ticker}"

                # Flatten MultiIndex columns if present (e.g. older/newer yf edge-cases)
                if isinstance(df.columns, pd.MultiIndex):
                    # Keep price level if ticker is in column levels
                    if clean_ticker in df.columns.get_level_values(1):
                        df = df.xs(clean_ticker, axis=1, level=1)
                    else:
                        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

                # Check required price columns
                required_cols = {"Open", "High", "Low", "Close", "Volume"}
                missing = required_cols - set(df.columns)
                if missing:
                    return None, f"SCHEMA_ERROR: Missing required columns: {missing}"

                # If Adj Close is missing (rare when auto_adjust=False), fallback to Close
                if "Adj Close" not in df.columns:
                    df["Adj Close"] = df["Close"]

                return df, None

            except Exception as e:
                err_str = str(e)
                last_error = err_str

                # Detect permanent 404 (delisted / invalid ticker)
                if "404" in err_str or "Not Found" in err_str or "No data found" in err_str:
                    logger.warning(f"Ticker {clean_ticker} not found on Yahoo Finance: {err_str}")
                    return None, f"NOT_FOUND: {err_str}"

                # Rate limiting (429 Too Many Requests) or network glitch -> retry with backoff
                wait_time = (self.backoff_factor ** attempt) + random.uniform(0.5, 1.5)
                logger.warning(
                    f"Attempt {attempt}/{self.max_retries} failed for {clean_ticker}: {err_str}. Retrying in {wait_time:.1f}s..."
                )
                time.sleep(wait_time)

        return None, f"MAX_RETRIES_EXCEEDED: Failed after {self.max_retries} attempts. Last error: {last_error}"

    def fetch_corporate_events(self, ticker: str) -> Dict[str, pd.Series]:
        """
        Fetch corporate actions (dividends and stock splits) for a ticker.
        """
        clean_ticker = ticker.strip().upper()
        try:
            self._sleep_with_jitter()
            yf_ticker = yf.Ticker(clean_ticker)
            dividends = getattr(yf_ticker, "dividends", pd.Series(dtype=float))
            splits = getattr(yf_ticker, "splits", pd.Series(dtype=float))
            return {
                "dividends": dividends if dividends is not None else pd.Series(dtype=float),
                "splits": splits if splits is not None else pd.Series(dtype=float)
            }
        except Exception as e:
            logger.warning(f"Failed to fetch corporate events for {clean_ticker}: {e}")
            return {"dividends": pd.Series(dtype=float), "splits": pd.Series(dtype=float)}

    def probe_ticker(self, ticker: str) -> bool:
        """Quickly check if a ticker has any valid recent history on Yahoo Finance."""
        clean_ticker = ticker.strip().upper()
        df, err = self.fetch_historical(clean_ticker, period="5d")
        return df is not None and not df.empty
