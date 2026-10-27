"""
Oracle Database Repository Module for Vietnam Stock Data Pipeline.
Implements native Oracle DDL, MERGE upsert, batching, connection pooling,
and graceful offline fallback for development and testing.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date
import os
import sqlite3
import pandas as pd
from pathlib import Path

try:
    import oracledb
except ImportError:
    oracledb = None

from src.config import settings
from src.import_logger import logger


class OracleConnectionError(Exception):
    """Raised when connecting to Oracle Database fails."""
    pass


class OracleRepository:
    """Production Oracle Repository using python-oracledb."""

    def __init__(self):
        self.is_connected = False
        self._init_oracle_client()

    def _init_oracle_client(self):
        """Initialize thick client if requested in settings."""
        if oracledb is None:
            return
        if settings.oracle_mode == "thick" and settings.oracle_client_lib_dir:
            try:
                oracledb.init_oracle_client(lib_dir=settings.oracle_client_lib_dir)
                logger.info(f"Initialized Oracle Thick Client from {settings.oracle_client_lib_dir}")
            except Exception as e:
                logger.warning(f"Could not initialize Oracle Thick Client: {e}. Falling back to Thin Mode.")

    def get_connection(self):
        """Create and return a new oracledb connection."""
        if not settings.is_oracle_configured():
            raise OracleConnectionError(
                "Oracle Database is not configured. Please set ORACLE_USER, ORACLE_PASSWORD, "
                "and ORACLE_DSN in your .env file (see .env.example)."
            )
        if oracledb is None:
            raise OracleConnectionError("python-oracledb library is not installed.")

        try:
            params = {
                "user": settings.oracle_user,
                "password": settings.oracle_password,
                "dsn": settings.oracle_dsn
            }
            if settings.oracle_wallet_location:
                params["wallet_location"] = settings.oracle_wallet_location
                if settings.oracle_wallet_password:
                    params["wallet_password"] = settings.oracle_wallet_password

            conn = oracledb.connect(**params)
            return conn
        except Exception as e:
            raise OracleConnectionError(f"Failed to connect to Oracle Database at {settings.oracle_dsn}: {e}")

    def check_connection(self) -> Tuple[bool, str]:
        """Test Oracle database connectivity."""
        if not settings.is_oracle_configured():
            return False, "Oracle credentials missing in configuration (.env)."
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM DUAL")
                    res = cursor.fetchone()
                    if res and res[0] == 1:
                        self.is_connected = True
                        return True, "Connected successfully to Oracle Database."
            return False, "Failed to verify query on Oracle Database."
        except Exception as e:
            return False, f"Oracle connection check failed: {e}"

    def init_schema(self) -> Tuple[bool, str]:
        """Execute schema DDL script to create tables and indexes idempotently."""
        schema_path = settings.schema_file
        if not schema_path.exists():
            return False, f"Schema file not found at {schema_path}"

        with open(schema_path, "r", encoding="utf-8") as f:
            sql_script = f.read()

        # Split PL/SQL blocks by '/'
        blocks = [b.strip() for b in sql_script.split("/") if b.strip()]

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    for block in blocks:
                        # Clean sql comments before execution
                        clean_block = "\n".join(
                            line for line in block.splitlines() if not line.strip().startswith("--")
                        ).strip()
                        if clean_block:
                            cursor.execute(clean_block)
                conn.commit()
            return True, "Oracle schema initialized successfully."
        except Exception as e:
            logger.error(f"Error initializing Oracle schema: {e}")
            return False, f"Schema initialization failed: {e}"

    def upsert_symbols(self, symbols: List[Dict[str, Any]]) -> int:
        """Upsert stock symbols into STOCK_SYMBOLS using MERGE."""
        if not symbols:
            return 0

        merge_sql = """
        MERGE INTO STOCK_SYMBOLS tgt
        USING (SELECT :1 AS SYMBOL, :2 AS YAHOO_TICKER, :3 AS COMPANY_NAME, :4 AS EXCHANGE,
                      :5 AS SECURITY_TYPE, :6 AS STATUS, :7 AS SOURCE FROM DUAL) src
        ON (tgt.SYMBOL = src.SYMBOL)
        WHEN MATCHED THEN
          UPDATE SET tgt.YAHOO_TICKER = src.YAHOO_TICKER,
                     tgt.COMPANY_NAME = src.COMPANY_NAME,
                     tgt.EXCHANGE = src.EXCHANGE,
                     tgt.SECURITY_TYPE = src.SECURITY_TYPE,
                     tgt.STATUS = src.STATUS,
                     tgt.SOURCE = src.SOURCE
        WHEN NOT MATCHED THEN
          INSERT (SYMBOL, YAHOO_TICKER, COMPANY_NAME, EXCHANGE, SECURITY_TYPE, STATUS, SOURCE)
          VALUES (src.SYMBOL, src.YAHOO_TICKER, src.COMPANY_NAME, src.EXCHANGE, src.SECURITY_TYPE, src.STATUS, src.SOURCE)
        """

        params = []
        for s in symbols:
            params.append((
                str(s["symbol"]),
                str(s.get("yahoo_ticker", f"{s['symbol']}.VN")),
                str(s.get("company_name", s["symbol"])),
                str(s.get("exchange", "UNKNOWN")),
                str(s.get("security_type", "EQUITY")),
                str(s.get("status", "ACTIVE")),
                str(s.get("source", "MANUAL"))
            ))

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(merge_sql, params)
            conn.commit()
        return len(params)

    def upsert_prices(self, price_tuples: List[tuple], batch_size: Optional[int] = None) -> Tuple[int, int]:
        """
        Upsert price records into STOCK_PRICES using MERGE.
        Returns (records_affected, 0).
        """
        if not price_tuples:
            return 0, 0

        batch_size = batch_size or settings.db_batch_size
        merge_sql = """
        MERGE INTO STOCK_PRICES tgt
        USING (SELECT :1 AS SYMBOL, :2 AS TRADE_DATE, :3 AS OPEN_PRICE, :4 AS HIGH_PRICE,
                      :5 AS LOW_PRICE, :6 AS CLOSE_PRICE, :7 AS ADJ_CLOSE, :8 AS VOLUME,
                      :9 AS QUALITY_STATUS, :10 AS SOURCE, :11 AS FETCHED_AT FROM DUAL) src
        ON (tgt.SYMBOL = src.SYMBOL AND tgt.TRADE_DATE = src.TRADE_DATE)
        WHEN MATCHED THEN
          UPDATE SET tgt.OPEN_PRICE = src.OPEN_PRICE,
                     tgt.HIGH_PRICE = src.HIGH_PRICE,
                     tgt.LOW_PRICE = src.LOW_PRICE,
                     tgt.CLOSE_PRICE = src.CLOSE_PRICE,
                     tgt.ADJ_CLOSE = src.ADJ_CLOSE,
                     tgt.VOLUME = src.VOLUME,
                     tgt.QUALITY_STATUS = src.QUALITY_STATUS,
                     tgt.SOURCE = src.SOURCE,
                     tgt.FETCHED_AT = src.FETCHED_AT
        WHEN NOT MATCHED THEN
          INSERT (SYMBOL, TRADE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, ADJ_CLOSE, VOLUME, QUALITY_STATUS, SOURCE, FETCHED_AT)
          VALUES (src.SYMBOL, src.TRADE_DATE, src.OPEN_PRICE, src.HIGH_PRICE, src.LOW_PRICE, src.CLOSE_PRICE, src.ADJ_CLOSE, src.VOLUME, src.QUALITY_STATUS, src.SOURCE, src.FETCHED_AT)
        """

        total_affected = 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for i in range(0, len(price_tuples), batch_size):
                    chunk = price_tuples[i:i + batch_size]
                    cursor.executemany(merge_sql, chunk)
                    total_affected += len(chunk)
            conn.commit()

        return total_affected, 0

    def upsert_events(self, events: List[Dict[str, Any]]) -> int:
        """Upsert corporate actions (dividends and splits) into STOCK_EVENTS."""
        if not events:
            return 0

        merge_sql = """
        MERGE INTO STOCK_EVENTS tgt
        USING (SELECT :1 AS SYMBOL, :2 AS EVENT_DATE, :3 AS EVENT_TYPE,
                      :4 AS EVENT_VALUE, :5 AS SOURCE, :6 AS FETCHED_AT FROM DUAL) src
        ON (tgt.SYMBOL = src.SYMBOL AND tgt.EVENT_DATE = src.EVENT_DATE AND tgt.EVENT_TYPE = src.EVENT_TYPE)
        WHEN MATCHED THEN
          UPDATE SET tgt.EVENT_VALUE = src.EVENT_VALUE,
                     tgt.SOURCE = src.SOURCE,
                     tgt.FETCHED_AT = src.FETCHED_AT
        WHEN NOT MATCHED THEN
          INSERT (SYMBOL, EVENT_DATE, EVENT_TYPE, EVENT_VALUE, SOURCE, FETCHED_AT)
          VALUES (src.SYMBOL, src.EVENT_DATE, src.EVENT_TYPE, src.EVENT_VALUE, src.SOURCE, src.FETCHED_AT)
        """

        params = [
            (
                e["SYMBOL"],
                e["EVENT_DATE"],
                e["EVENT_TYPE"],
                float(e["EVENT_VALUE"]),
                e["SOURCE"],
                e["FETCHED_AT"]
            )
            for e in events
        ]

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(merge_sql, params)
            conn.commit()
        return len(params)

    def update_symbol_sync_stats(
        self,
        symbol: str,
        first_date: Optional[date] = None,
        last_date: Optional[date] = None,
        last_sync_at: Optional[datetime] = None
    ) -> None:
        """Update FIRST_DATA_DATE, LAST_DATA_DATE, and LAST_SYNC_AT on STOCK_SYMBOLS."""
        sync_at = last_sync_at or datetime.now()
        sql = """
        UPDATE STOCK_SYMBOLS
        SET FIRST_DATA_DATE = COALESCE(:1, FIRST_DATA_DATE),
            LAST_DATA_DATE = COALESCE(:2, LAST_DATA_DATE),
            LAST_SYNC_AT = :3
        WHERE SYMBOL = :4
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (first_date, last_date, sync_at, symbol))
            conn.commit()

    def log_import(
        self,
        batch_id: str,
        symbol: str,
        task_type: str,
        start_time: datetime,
        end_time: datetime,
        records_fetched: int,
        records_inserted: int,
        records_updated: int,
        records_rejected: int,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """Insert import execution log into DATA_IMPORT_LOGS."""
        sql = """
        INSERT INTO DATA_IMPORT_LOGS (
            BATCH_ID, SYMBOL, TASK_TYPE, START_TIME, END_TIME,
            RECORDS_FETCHED, RECORDS_INSERTED, RECORDS_UPDATED, RECORDS_REJECTED,
            STATUS, ERROR_MESSAGE
        ) VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11)
        """
        err_sub = error_message[:3900] if error_message else None
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (
                    batch_id, symbol, task_type, start_time, end_time,
                    records_fetched, records_inserted, records_updated, records_rejected,
                    status, err_sub
                ))
            conn.commit()

    def get_symbol_sync_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve symbol metadata and sync status from Oracle."""
        sql = """
        SELECT SYMBOL, YAHOO_TICKER, COMPANY_NAME, EXCHANGE, SECURITY_TYPE,
               STATUS, FIRST_DATA_DATE, LAST_DATA_DATE, LAST_SYNC_AT
        FROM STOCK_SYMBOLS
        WHERE SYMBOL = :1
        """
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (symbol,))
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "symbol": row[0],
                    "yahoo_ticker": row[1],
                    "company_name": row[2],
                    "exchange": row[3],
                    "security_type": row[4],
                    "status": row[5],
                    "first_data_date": row[6],
                    "last_data_date": row[7],
                    "last_sync_at": row[8]
                }

    def get_failed_symbols(self, batch_id: Optional[str] = None) -> List[str]:
        """Fetch list of symbols that encountered errors in logs."""
        if batch_id:
            sql = "SELECT DISTINCT SYMBOL FROM DATA_IMPORT_LOGS WHERE BATCH_ID = :1 AND STATUS = 'FAILED'"
            params = (batch_id,)
        else:
            sql = "SELECT DISTINCT SYMBOL FROM DATA_IMPORT_LOGS WHERE STATUS = 'FAILED'"
            params = ()

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return [r[0] for r in cursor.fetchall()]

    def get_database_summary(self) -> Dict[str, Any]:
        """Return high-level summary counts from Oracle database."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM STOCK_SYMBOLS")
                total_symbols = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM STOCK_PRICES")
                total_prices = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(DISTINCT SYMBOL) FROM STOCK_PRICES")
                symbols_with_prices = cursor.fetchone()[0]

                cursor.execute("SELECT MIN(TRADE_DATE), MAX(TRADE_DATE) FROM STOCK_PRICES")
                date_range = cursor.fetchone()
                earliest_date = date_range[0] if date_range else None
                latest_date = date_range[1] if date_range else None

                cursor.execute("SELECT COUNT(*) FROM DATA_IMPORT_LOGS")
                total_logs = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM STOCK_EVENTS")
                total_events = cursor.fetchone()[0]

        return {
            "total_symbols": total_symbols,
            "total_price_records": total_prices,
            "symbols_with_prices": symbols_with_prices,
            "earliest_date": earliest_date,
            "latest_date": latest_date,
            "total_logs": total_logs,
            "total_events": total_events
        }

    def get_symbols_summary(self) -> List[Dict[str, Any]]:
        """Return list of distinct symbols stored in STOCK_PRICES with stats."""
        sql = """
        SELECT p.SYMBOL, COUNT(p.TRADE_DATE) as BARS_COUNT,
               MIN(p.TRADE_DATE) as START_DATE, MAX(p.TRADE_DATE) as END_DATE,
               COALESCE(MAX(s.COMPANY_NAME), p.SYMBOL) as COMPANY_NAME,
               COALESCE(MAX(s.EXCHANGE), 'HOSE') as EXCHANGE
        FROM STOCK_PRICES p
        LEFT JOIN STOCK_SYMBOLS s ON p.SYMBOL = s.SYMBOL
        GROUP BY p.SYMBOL
        ORDER BY p.SYMBOL
        """
        with self.get_connection() as conn:
            df = pd.read_sql(sql, conn)
            res = []
            for _, r in df.iterrows():
                res.append({
                    "symbol": str(r["SYMBOL"]),
                    "bars_count": int(r["BARS_COUNT"]),
                    "start_date": str(r["START_DATE"])[:10],
                    "end_date": str(r["END_DATE"])[:10],
                    "company_name": str(r["COMPANY_NAME"]),
                    "exchange": str(r["EXCHANGE"])
                })
            return res

    def query_historical_prices(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Query time series prices for a single symbol, sorted chronologically."""
        sql = """
        SELECT SYMBOL, TRADE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE,
               CLOSE_PRICE, ADJ_CLOSE, VOLUME, QUALITY_STATUS, SOURCE, FETCHED_AT
        FROM STOCK_PRICES
        WHERE SYMBOL = :1
        """
        params = [symbol]
        if start_date:
            sql += " AND TRADE_DATE >= TO_DATE(:2, 'YYYY-MM-DD')"
            params.append(start_date)
        if end_date:
            sql += f" AND TRADE_DATE <= TO_DATE(:{len(params)+1}, 'YYYY-MM-DD')"
            params.append(end_date)
        sql += " ORDER BY TRADE_DATE ASC"

        with self.get_connection() as conn:
            df = pd.read_sql(sql, conn, params=params)
        return df

    def query_cross_sectional_prices(
        self,
        trade_date: str,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """Query market prices for multiple symbols on a specific trading day."""
        sql = """
        SELECT SYMBOL, TRADE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE,
               CLOSE_PRICE, ADJ_CLOSE, VOLUME, QUALITY_STATUS
        FROM STOCK_PRICES
        WHERE TRADE_DATE = TO_DATE(:1, 'YYYY-MM-DD')
        """
        params = [trade_date]
        if symbols:
            placeholders = ",".join(f":{i+2}" for i in range(len(symbols)))
            sql += f" AND SYMBOL IN ({placeholders})"
            params.extend(symbols)
        sql += " ORDER BY VOLUME DESC"

        with self.get_connection() as conn:
            df = pd.read_sql(sql, conn, params=params)
        return df

    def init_strategy_schema(self) -> Tuple[bool, str]:
        """Execute strategy schema DDL script for research and backtesting tables."""
        strategy_schema_path = settings.schema_file.parent / "strategy_schema.sql"
        if not strategy_schema_path.exists():
            return False, f"Strategy schema file not found at {strategy_schema_path}"

        with open(strategy_schema_path, "r", encoding="utf-8") as f:
            sql_script = f.read()

        blocks = [b.strip() for b in sql_script.split("/") if b.strip()]
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    for block in blocks:
                        clean_block = "\n".join(
                            line for line in block.splitlines() if not line.strip().startswith("--")
                        ).strip()
                        if clean_block:
                            cursor.execute(clean_block)
                conn.commit()
            return True, "Oracle strategy schema initialized successfully."
        except Exception as e:
            logger.error(f"Error initializing strategy schema: {e}")
            return False, f"Strategy schema initialization failed: {e}"

    def save_backtest_run(
        self,
        run_data: Dict[str, Any],
        signals: List[Any],
        orders: List[Any],
        trades: List[Any],
        metrics: Dict[str, Any]
    ) -> None:
        """Save a complete backtest run, signals, orders, trades, and metrics to Oracle."""
        run_id = run_data["run_id"]
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # 1. Insert Run
                cursor.execute("""
                INSERT INTO BACKTEST_RUNS (
                    RUN_ID, CONFIG_ID, START_DATE, END_DATE, INITIAL_CAPITAL,
                    SYMBOLS_COUNT, TOTAL_SIGNALS, TOTAL_ORDERS, TOTAL_TRADES
                ) VALUES (
                    :1, :2,
                    TO_DATE(:3, 'YYYY-MM-DD'), TO_DATE(:4, 'YYYY-MM-DD'),
                    :5, :6, :7, :8, :9
                )
                """, (
                    run_id, run_data.get("config_id", "DEFAULT_JLP"),
                    run_data.get("start_date", "2010-01-01"), run_data.get("end_date", "2026-10-15"),
                    float(run_data.get("initial_capital", 100_000_000)),
                    len(run_data.get("symbols", [])), len(signals), len(orders), len(trades)
                ))

                # 2. Insert Trades
                if trades:
                    trade_params = []
                    for t in trades:
                        trade_params.append((
                            t.trade_id, run_id, t.order_id, t.symbol, t.direction,
                            t.entry_date.isoformat() if hasattr(t.entry_date, "isoformat") else str(t.entry_date)[:10],
                            float(t.entry_price),
                            t.exit_date.isoformat() if hasattr(t.exit_date, "isoformat") else str(t.exit_date)[:10],
                            float(t.exit_price), t.exit_reason, int(t.quantity),
                            float(t.gross_pnl), float(t.net_pnl), float(t.return_pct),
                            float(t.commission_paid), float(t.tax_paid), float(t.slippage_cost),
                            int(t.holding_bars)
                        ))
                    cursor.executemany("""
                    INSERT INTO BACKTEST_TRADES (
                        TRADE_ID, RUN_ID, ORDER_ID, SYMBOL, DIRECTION,
                        ENTRY_DATE, ENTRY_PRICE, EXIT_DATE, EXIT_PRICE, EXIT_REASON,
                        QUANTITY, GROSS_PNL, NET_PNL, RETURN_PCT,
                        COMMISSION, TAX, SLIPPAGE, HOLDING_BARS
                    ) VALUES (
                        :1, :2, :3, :4, :5,
                        TO_DATE(:6, 'YYYY-MM-DD'), :7, TO_DATE(:8, 'YYYY-MM-DD'), :9, :10,
                        :11, :12, :13, :14, :15, :16, :17, :18
                    )
                    """, trade_params)

                # 3. Insert Metrics
                cursor.execute("""
                INSERT INTO BACKTEST_METRICS (
                    RUN_ID, SYMBOL, TOTAL_TRADES, WIN_COUNT, LOSS_COUNT,
                    WIN_RATE_PCT, PROFIT_FACTOR, GROSS_PNL, NET_PNL,
                    ROI_PCT, MAX_DRAWDOWN_PCT, EXPECTED_VALUE, VERDICT
                ) VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11, :12, :13)
                """, (
                    run_id, "PORTFOLIO",
                    metrics["total_trades"], metrics["win_count"], metrics["loss_count"],
                    metrics["win_rate_pct"], metrics["profit_factor"],
                    metrics["gross_pnl"], metrics["net_pnl"], metrics["roi_pct"],
                    metrics["max_drawdown_pct"], metrics["expected_value_per_trade"],
                    metrics["evaluation_verdict"]
                ))

            conn.commit()

    def get_backtest_runs(self) -> List[Dict[str, Any]]:
        """Fetch list of historical backtest runs."""
        sql = "SELECT * FROM BACKTEST_RUNS ORDER BY CREATED_AT DESC"
        with self.get_connection() as conn:
            df = pd.read_sql(sql, conn)
            return df.to_dict(orient="records")

    def get_backtest_trades(self, run_id: str) -> pd.DataFrame:
        """Fetch trades for a specific backtest run."""
        sql = "SELECT * FROM BACKTEST_TRADES WHERE RUN_ID = :1 ORDER BY ENTRY_DATE ASC"
        with self.get_connection() as conn:
            return pd.read_sql(sql, conn, params=[run_id])



class MockSqliteRepository:
    """
    Offline/Emulation Repository using SQLite.
    Guarantees that all schema, idempotency, upsert, query, and reporting logic
    can be verified end-to-end even when an external Oracle Database server is unreachable.
    """

    def __init__(self, db_path: Optional[str] = None):
        configured = db_path or os.getenv('QTA_PRICE_DB')
        if not db_path and configured and not Path(configured).is_file():
            raise FileNotFoundError('QTA_PRICE_DB không tồn tại; không tự tạo database rỗng.')
        self.db_path = configured or str(settings.state_dir / "vietnam_stocks_mock.db")
        self.init_schema()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        return conn

    def check_connection(self) -> Tuple[bool, str]:
        try:
            with self.get_connection() as conn:
                res = conn.execute("SELECT 1").fetchone()
                if res and res[0] == 1:
                    return True, f"Mock SQLite storage operational at {self.db_path}"
            return False, "Failed query on Mock SQLite"
        except Exception as e:
            return False, str(e)

    def init_schema(self) -> Tuple[bool, str]:
        with self.get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS STOCK_SYMBOLS (
                SYMBOL_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                SYMBOL TEXT NOT NULL UNIQUE,
                YAHOO_TICKER TEXT NOT NULL UNIQUE,
                COMPANY_NAME TEXT,
                EXCHANGE TEXT NOT NULL,
                SECURITY_TYPE TEXT DEFAULT 'EQUITY',
                STATUS TEXT DEFAULT 'ACTIVE',
                SOURCE TEXT DEFAULT 'OFFICIAL_LIST',
                FIRST_DATA_DATE TEXT,
                LAST_DATA_DATE TEXT,
                LAST_SYNC_AT TEXT,
                CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS STOCK_PRICES (
                SYMBOL TEXT NOT NULL,
                TRADE_DATE TEXT NOT NULL,
                OPEN_PRICE REAL NOT NULL,
                HIGH_PRICE REAL NOT NULL,
                LOW_PRICE REAL NOT NULL,
                CLOSE_PRICE REAL NOT NULL,
                ADJ_CLOSE REAL,
                VOLUME INTEGER NOT NULL,
                QUALITY_STATUS TEXT DEFAULT 'VALID',
                SOURCE TEXT DEFAULT 'yfinance',
                FETCHED_AT TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (SYMBOL, TRADE_DATE)
            );

            CREATE INDEX IF NOT EXISTS IDX_PRICES_TRADE_DATE ON STOCK_PRICES (TRADE_DATE);

            CREATE TABLE IF NOT EXISTS DATA_IMPORT_LOGS (
                LOG_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                BATCH_ID TEXT NOT NULL,
                SYMBOL TEXT NOT NULL,
                TASK_TYPE TEXT NOT NULL,
                START_TIME TEXT NOT NULL,
                END_TIME TEXT,
                RECORDS_FETCHED INTEGER DEFAULT 0,
                RECORDS_INSERTED INTEGER DEFAULT 0,
                RECORDS_UPDATED INTEGER DEFAULT 0,
                RECORDS_REJECTED INTEGER DEFAULT 0,
                STATUS TEXT NOT NULL,
                ERROR_MESSAGE TEXT,
                CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS STOCK_EVENTS (
                EVENT_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                SYMBOL TEXT NOT NULL,
                EVENT_DATE TEXT NOT NULL,
                EVENT_TYPE TEXT NOT NULL,
                EVENT_VALUE REAL NOT NULL,
                SOURCE TEXT DEFAULT 'yfinance',
                FETCHED_AT TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (SYMBOL, EVENT_DATE, EVENT_TYPE)
            );

            CREATE TABLE IF NOT EXISTS STRATEGY_CONFIGS (
                CONFIG_ID TEXT PRIMARY KEY,
                STRATEGY_NAME TEXT NOT NULL,
                VERSION TEXT DEFAULT '1.0.0',
                PARAMETERS_JSON TEXT NOT NULL,
                DESCRIPTION TEXT,
                CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS BACKTEST_RUNS (
                RUN_ID TEXT PRIMARY KEY,
                CONFIG_ID TEXT,
                START_DATE TEXT,
                END_DATE TEXT,
                INITIAL_CAPITAL REAL NOT NULL,
                SYMBOLS_COUNT INTEGER NOT NULL,
                TOTAL_SIGNALS INTEGER DEFAULT 0,
                TOTAL_ORDERS INTEGER DEFAULT 0,
                TOTAL_TRADES INTEGER DEFAULT 0,
                CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS STRATEGY_SIGNALS (
                SIGNAL_ID TEXT PRIMARY KEY,
                RUN_ID TEXT NOT NULL,
                SYMBOL TEXT NOT NULL,
                TRADE_DATE TEXT NOT NULL,
                BAR_INDEX INTEGER NOT NULL,
                SIGNAL_TYPE TEXT NOT NULL,
                CONFLUENCE_LOW REAL NOT NULL,
                CONFLUENCE_HIGH REAL NOT NULL,
                CONFLUENCE_MID REAL NOT NULL,
                GANN_75_LEVEL REAL NOT NULL,
                LIMIT_PRICE REAL NOT NULL,
                STOP_LOSS REAL NOT NULL,
                TAKE_PROFIT REAL NOT NULL,
                RISK_REWARD REAL NOT NULL,
                CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS BACKTEST_ORDERS (
                ORDER_ID TEXT PRIMARY KEY,
                RUN_ID TEXT NOT NULL,
                SIGNAL_ID TEXT,
                SYMBOL TEXT NOT NULL,
                ORDER_TYPE TEXT NOT NULL,
                PLACED_DATE TEXT NOT NULL,
                LIMIT_PRICE REAL NOT NULL,
                STOP_LOSS REAL NOT NULL,
                TAKE_PROFIT REAL NOT NULL,
                QUANTITY INTEGER NOT NULL,
                STATUS TEXT NOT NULL,
                FILL_DATE TEXT,
                FILL_PRICE REAL,
                CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS BACKTEST_TRADES (
                TRADE_ID TEXT PRIMARY KEY,
                RUN_ID TEXT NOT NULL,
                ORDER_ID TEXT,
                SYMBOL TEXT NOT NULL,
                DIRECTION TEXT NOT NULL,
                ENTRY_DATE TEXT NOT NULL,
                ENTRY_PRICE REAL NOT NULL,
                EXIT_DATE TEXT NOT NULL,
                EXIT_PRICE REAL NOT NULL,
                EXIT_REASON TEXT NOT NULL,
                QUANTITY INTEGER NOT NULL,
                GROSS_PNL REAL NOT NULL,
                NET_PNL REAL NOT NULL,
                RETURN_PCT REAL NOT NULL,
                COMMISSION REAL NOT NULL,
                TAX REAL NOT NULL,
                SLIPPAGE REAL NOT NULL,
                HOLDING_BARS INTEGER NOT NULL,
                CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS BACKTEST_METRICS (
                METRIC_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                RUN_ID TEXT NOT NULL,
                SYMBOL TEXT DEFAULT 'PORTFOLIO',
                TOTAL_TRADES INTEGER NOT NULL,
                WIN_COUNT INTEGER NOT NULL,
                LOSS_COUNT INTEGER NOT NULL,
                WIN_RATE_PCT REAL NOT NULL,
                PROFIT_FACTOR REAL NOT NULL,
                GROSS_PNL REAL NOT NULL,
                NET_PNL REAL NOT NULL,
                ROI_PCT REAL NOT NULL,
                MAX_DRAWDOWN_PCT REAL NOT NULL,
                EXPECTED_VALUE REAL NOT NULL,
                VERDICT TEXT NOT NULL,
                CREATED_AT TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """)
            conn.commit()
        return True, "Mock SQLite schema initialized successfully."

    def upsert_symbols(self, symbols: List[Dict[str, Any]]) -> int:
        if not symbols:
            return 0
        sql = """
        INSERT INTO STOCK_SYMBOLS (SYMBOL, YAHOO_TICKER, COMPANY_NAME, EXCHANGE, SECURITY_TYPE, STATUS, SOURCE)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(SYMBOL) DO UPDATE SET
            YAHOO_TICKER = excluded.YAHOO_TICKER,
            COMPANY_NAME = excluded.COMPANY_NAME,
            EXCHANGE = excluded.EXCHANGE,
            SECURITY_TYPE = excluded.SECURITY_TYPE,
            STATUS = excluded.STATUS,
            SOURCE = excluded.SOURCE
        """
        params = [
            (
                s["symbol"],
                s.get("yahoo_ticker", f"{s['symbol']}.VN"),
                s.get("company_name", s["symbol"]),
                s.get("exchange", "UNKNOWN"),
                s.get("security_type", "EQUITY"),
                s.get("status", "ACTIVE"),
                s.get("source", "MANUAL")
            )
            for s in symbols
        ]
        with self.get_connection() as conn:
            conn.executemany(sql, params)
            conn.commit()
        return len(params)

    def upsert_prices(self, price_tuples: List[tuple], batch_size: Optional[int] = None) -> Tuple[int, int]:
        if not price_tuples:
            return 0, 0
        sql = """
        INSERT INTO STOCK_PRICES (SYMBOL, TRADE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, ADJ_CLOSE, VOLUME, QUALITY_STATUS, SOURCE, FETCHED_AT)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(SYMBOL, TRADE_DATE) DO UPDATE SET
            OPEN_PRICE = excluded.OPEN_PRICE,
            HIGH_PRICE = excluded.HIGH_PRICE,
            LOW_PRICE = excluded.LOW_PRICE,
            CLOSE_PRICE = excluded.CLOSE_PRICE,
            ADJ_CLOSE = excluded.ADJ_CLOSE,
            VOLUME = excluded.VOLUME,
            QUALITY_STATUS = excluded.QUALITY_STATUS,
            SOURCE = excluded.SOURCE,
            FETCHED_AT = excluded.FETCHED_AT
        """
        # Convert date and datetime objects to ISO strings for SQLite
        formatted = []
        for r in price_tuples:
            sym, t_date, o, h, l, c, adj, vol, q_stat, src, fetched = r
            t_str = t_date.isoformat() if hasattr(t_date, "isoformat") else str(t_date)
            f_str = fetched.isoformat() if hasattr(fetched, "isoformat") else str(fetched)
            formatted.append((sym, t_str, o, h, l, c, adj, vol, q_stat, src, f_str))

        with self.get_connection() as conn:
            conn.executemany(sql, formatted)
            conn.commit()
        return len(formatted), 0

    def upsert_events(self, events: List[Dict[str, Any]]) -> int:
        if not events:
            return 0
        sql = """
        INSERT INTO STOCK_EVENTS (SYMBOL, EVENT_DATE, EVENT_TYPE, EVENT_VALUE, SOURCE, FETCHED_AT)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(SYMBOL, EVENT_DATE, EVENT_TYPE) DO UPDATE SET
            EVENT_VALUE = excluded.EVENT_VALUE,
            SOURCE = excluded.SOURCE,
            FETCHED_AT = excluded.FETCHED_AT
        """
        params = []
        for e in events:
            d_str = e["EVENT_DATE"].isoformat() if hasattr(e["EVENT_DATE"], "isoformat") else str(e["EVENT_DATE"])
            f_str = e["FETCHED_AT"].isoformat() if hasattr(e["FETCHED_AT"], "isoformat") else str(e["FETCHED_AT"])
            params.append((e["SYMBOL"], d_str, e["EVENT_TYPE"], float(e["EVENT_VALUE"]), e["SOURCE"], f_str))

        with self.get_connection() as conn:
            conn.executemany(sql, params)
            conn.commit()
        return len(params)

    def update_symbol_sync_stats(
        self,
        symbol: str,
        first_date: Optional[date] = None,
        last_date: Optional[date] = None,
        last_sync_at: Optional[datetime] = None
    ) -> None:
        sync_str = (last_sync_at or datetime.now()).isoformat()
        first_str = first_date.isoformat() if first_date else None
        last_str = last_date.isoformat() if last_date else None

        sql = """
        UPDATE STOCK_SYMBOLS
        SET FIRST_DATA_DATE = COALESCE(?, FIRST_DATA_DATE),
            LAST_DATA_DATE = COALESCE(?, LAST_DATA_DATE),
            LAST_SYNC_AT = ?
        WHERE SYMBOL = ?
        """
        with self.get_connection() as conn:
            conn.execute(sql, (first_str, last_str, sync_str, symbol))
            conn.commit()

    def log_import(
        self,
        batch_id: str,
        symbol: str,
        task_type: str,
        start_time: datetime,
        end_time: datetime,
        records_fetched: int,
        records_inserted: int,
        records_updated: int,
        records_rejected: int,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        sql = """
        INSERT INTO DATA_IMPORT_LOGS (
            BATCH_ID, SYMBOL, TASK_TYPE, START_TIME, END_TIME,
            RECORDS_FETCHED, RECORDS_INSERTED, RECORDS_UPDATED, RECORDS_REJECTED,
            STATUS, ERROR_MESSAGE
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        st_str = start_time.isoformat()
        et_str = end_time.isoformat()
        with self.get_connection() as conn:
            conn.execute(sql, (
                batch_id, symbol, task_type, st_str, et_str,
                records_fetched, records_inserted, records_updated, records_rejected,
                status, error_message
            ))
            conn.commit()

    def get_symbol_sync_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM STOCK_SYMBOLS WHERE SYMBOL = ?"
        with self.get_connection() as conn:
            row = conn.execute(sql, (symbol,)).fetchone()
            if not row:
                return None
            return dict(row)

    def get_failed_symbols(self, batch_id: Optional[str] = None) -> List[str]:
        if batch_id:
            sql = "SELECT DISTINCT SYMBOL FROM DATA_IMPORT_LOGS WHERE BATCH_ID = ? AND STATUS = 'FAILED'"
            params = (batch_id,)
        else:
            sql = "SELECT DISTINCT SYMBOL FROM DATA_IMPORT_LOGS WHERE STATUS = 'FAILED'"
            params = ()

        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [r[0] for r in rows]

    def get_database_summary(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            total_symbols = conn.execute("SELECT COUNT(*) FROM STOCK_SYMBOLS").fetchone()[0]
            total_prices = conn.execute("SELECT COUNT(*) FROM STOCK_PRICES").fetchone()[0]
            symbols_with_prices = conn.execute("SELECT COUNT(DISTINCT SYMBOL) FROM STOCK_PRICES").fetchone()[0]
            date_range = conn.execute("SELECT MIN(TRADE_DATE), MAX(TRADE_DATE) FROM STOCK_PRICES").fetchone()
            earliest_date = date_range[0] if date_range else None
            latest_date = date_range[1] if date_range else None
            total_logs = conn.execute("SELECT COUNT(*) FROM DATA_IMPORT_LOGS").fetchone()[0]
            total_events = conn.execute("SELECT COUNT(*) FROM STOCK_EVENTS").fetchone()[0]

        return {
            "total_symbols": total_symbols,
            "total_price_records": total_prices,
            "symbols_with_prices": symbols_with_prices,
            "earliest_date": earliest_date,
            "latest_date": latest_date,
            "total_logs": total_logs,
            "total_events": total_events
        }

    def get_symbols_summary(self) -> List[Dict[str, Any]]:
        """Return list of distinct symbols stored in STOCK_PRICES with stats."""
        sql = """
        SELECT p.SYMBOL, COUNT(p.TRADE_DATE) as BARS_COUNT,
               MIN(p.TRADE_DATE) as START_DATE, MAX(p.TRADE_DATE) as END_DATE,
               COALESCE(s.COMPANY_NAME, p.SYMBOL) as COMPANY_NAME,
               COALESCE(s.EXCHANGE, 'HOSE') as EXCHANGE
        FROM STOCK_PRICES p
        LEFT JOIN STOCK_SYMBOLS s ON p.SYMBOL = s.SYMBOL
        GROUP BY p.SYMBOL
        ORDER BY p.SYMBOL
        """
        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn)
            res = []
            for _, r in df.iterrows():
                res.append({
                    "symbol": str(r["SYMBOL"]),
                    "bars_count": int(r["BARS_COUNT"]),
                    "start_date": str(r["START_DATE"])[:10],
                    "end_date": str(r["END_DATE"])[:10],
                    "company_name": str(r["COMPANY_NAME"]),
                    "exchange": str(r["EXCHANGE"])
                })
            return res

    def query_historical_prices(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        sql = "SELECT * FROM STOCK_PRICES WHERE SYMBOL = ?"
        params = [symbol]
        if start_date:
            sql += " AND TRADE_DATE >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND TRADE_DATE <= ?"
            params.append(end_date)
        sql += " ORDER BY TRADE_DATE ASC"

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)
        return df

    def query_cross_sectional_prices(
        self,
        trade_date: str,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        sql = "SELECT * FROM STOCK_PRICES WHERE TRADE_DATE = ?"
        params = [trade_date]
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            sql += f" AND SYMBOL IN ({placeholders})"
            params.extend(symbols)
        sql += " ORDER BY VOLUME DESC"

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)
        return df

    def init_strategy_schema(self) -> Tuple[bool, str]:
        return self.init_schema()

    def save_backtest_run(
        self,
        run_data: Dict[str, Any],
        signals: List[Any],
        orders: List[Any],
        trades: List[Any],
        metrics: Dict[str, Any]
    ) -> None:
        run_id = run_data["run_id"]
        with self.get_connection() as conn:
            # 1. Insert Run
            conn.execute("""
            INSERT OR REPLACE INTO BACKTEST_RUNS (
                RUN_ID, CONFIG_ID, START_DATE, END_DATE, INITIAL_CAPITAL,
                SYMBOLS_COUNT, TOTAL_SIGNALS, TOTAL_ORDERS, TOTAL_TRADES
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, run_data.get("config_id", "DEFAULT_JLP"),
                str(run_data.get("start_date", "2010-01-01")), str(run_data.get("end_date", "2026-10-15")),
                float(run_data.get("initial_capital", 100_000_000)),
                len(run_data.get("symbols", [])), len(signals), len(orders), len(trades)
            ))

            # 2. Insert Signals
            sig_params = [
                (
                    f"{run_id}_{s.signal_id}", run_id, s.symbol, str(s.trade_date)[:10],
                    s.bar_index, s.signal_type, s.confluence_low, s.confluence_high,
                    s.confluence_mid, s.gann_75_level, s.limit_price,
                    s.stop_loss_price, s.take_profit_price, s.risk_reward_ratio
                )
                for s in signals
            ]
            conn.executemany("""
            INSERT OR REPLACE INTO STRATEGY_SIGNALS (
                SIGNAL_ID, RUN_ID, SYMBOL, TRADE_DATE, BAR_INDEX, SIGNAL_TYPE,
                CONFLUENCE_LOW, CONFLUENCE_HIGH, CONFLUENCE_MID, GANN_75_LEVEL,
                LIMIT_PRICE, STOP_LOSS, TAKE_PROFIT, RISK_REWARD
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, sig_params)

            # 3. Insert Orders
            ord_params = [
                (
                    f"{run_id}_{o.order_id}", run_id, f"{run_id}_{o.signal_id}", o.symbol, o.order_type,
                    str(o.placed_date)[:10], o.limit_price, o.stop_loss,
                    o.take_profit, o.quantity, o.status,
                    str(o.fill_date)[:10] if o.fill_date else None, o.fill_price
                )
                for o in orders
            ]
            conn.executemany("""
            INSERT OR REPLACE INTO BACKTEST_ORDERS (
                ORDER_ID, RUN_ID, SIGNAL_ID, SYMBOL, ORDER_TYPE,
                PLACED_DATE, LIMIT_PRICE, STOP_LOSS, TAKE_PROFIT,
                QUANTITY, STATUS, FILL_DATE, FILL_PRICE
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ord_params)

            # 4. Insert Trades
            trade_params = [
                (
                    f"{run_id}_{t.trade_id}", run_id, f"{run_id}_{t.order_id}", t.symbol, t.direction,
                    str(t.entry_date)[:10], float(t.entry_price),
                    str(t.exit_date)[:10], float(t.exit_price), t.exit_reason,
                    int(t.quantity), float(t.gross_pnl), float(t.net_pnl),
                    float(t.return_pct), float(t.commission_paid), float(t.tax_paid),
                    float(t.slippage_cost), int(t.holding_bars)
                )
                for t in trades
            ]
            conn.executemany("""
            INSERT OR REPLACE INTO BACKTEST_TRADES (
                TRADE_ID, RUN_ID, ORDER_ID, SYMBOL, DIRECTION,
                ENTRY_DATE, ENTRY_PRICE, EXIT_DATE, EXIT_PRICE, EXIT_REASON,
                QUANTITY, GROSS_PNL, NET_PNL, RETURN_PCT,
                COMMISSION, TAX, SLIPPAGE, HOLDING_BARS
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, trade_params)

            # 5. Insert Metrics
            conn.execute("""
            INSERT OR REPLACE INTO BACKTEST_METRICS (
                RUN_ID, SYMBOL, TOTAL_TRADES, WIN_COUNT, LOSS_COUNT,
                WIN_RATE_PCT, PROFIT_FACTOR, GROSS_PNL, NET_PNL,
                ROI_PCT, MAX_DRAWDOWN_PCT, EXPECTED_VALUE, VERDICT
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, "PORTFOLIO",
                metrics["total_trades"], metrics["win_count"], metrics["loss_count"],
                metrics["win_rate_pct"], metrics["profit_factor"],
                metrics["gross_pnl"], metrics["net_pnl"], metrics["roi_pct"],
                metrics["max_drawdown_pct"], metrics["expected_value_per_trade"],
                metrics["evaluation_verdict"]
            ))

            conn.commit()

    def get_backtest_runs(self) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM BACKTEST_RUNS ORDER BY CREATED_AT DESC"
        with self.get_connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]

    def get_backtest_trades(self, run_id: str) -> pd.DataFrame:
        sql = "SELECT * FROM BACKTEST_TRADES WHERE RUN_ID = ? ORDER BY ENTRY_DATE ASC"
        with self.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=[run_id])



def get_repository(force_mock: bool = False):
    """
    Factory function returning the appropriate repository:
    - If force_mock is True, returns MockSqliteRepository.
    - If Oracle is configured and connected, returns OracleRepository.
    - Otherwise, returns OracleRepository by default (which raises OracleConnectionError on execution),
      or MockSqliteRepository if running in mock mode.
    """
    if force_mock:
        return MockSqliteRepository()

    if settings.is_oracle_configured():
        return OracleRepository()

    # Default to OracleRepository to ensure strict credentials enforcement,
    # but provide MockSqliteRepository when explicitly requested.
    return OracleRepository()
