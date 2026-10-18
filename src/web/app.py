"""
FastAPI Web Application Backend for Vietnam Stock Price Action Dashboard.
Provides interactive APIs for Charts, Signals, Backtesting, Sensitivity, and Data Ingestion.
"""

from typing import List, Dict, Any, Optional
import os
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.oracle_repository import get_repository
from src.symbol_manager import SymbolManager
from src.strategy.strategy_engine import JohnLucasPruniStrategy
from src.backtest.execution_models import VietnamExecutionEngine
from src.backtest.backtest_engine import BacktestEngine
from src.historical_importer import HistoricalImporter
from src.yfinance_client import YFinanceClient
from src.data_validator import DataValidator
from src.data_normalizer import DataNormalizer
from src.config import settings
from src.import_logger import logger


app = FastAPI(
    title="VNStock Price Action Dashboard",
    description="Interactive Web Platform for John Lucas Pruni Price Action Strategy & Vietnam Stock Data",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global repository instance
FORCE_MOCK = True  # Default to mock SQLite unless overridden
HTML_TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"


def get_repo():
    return get_repository(force_mock=FORCE_MOCK)


# ---------------------------------------------------------
# Request Models
# ---------------------------------------------------------

class BacktestRequest(BaseModel):
    symbols: List[str]
    capital: float = 100_000_000.0
    position_size: float = 0.20
    swing_left: int = 3
    swing_right: int = 2
    candle_mode: str = "middle_candle"
    min_rr: float = 1.5
    entry_mode: str = "zone_boundary"
    bidirectional: bool = False


class FetchRequest(BaseModel):
    symbols: str  # Comma-separated tickers, e.g. "TCB, MBB, VIC"


# ---------------------------------------------------------
# Web Page Route
# ---------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the single-page interactive HTML dashboard."""
    if not HTML_TEMPLATE_PATH.exists():
        raise HTTPException(status_code=404, detail="Dashboard template not found.")
    with open(HTML_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------
# REST API Endpoints
# ---------------------------------------------------------

@app.get("/api/summary")
def get_summary():
    """Return high-level database summary and system info."""
    repo = get_repo()
    db_summary = repo.get_database_summary()
    symbols = repo.get_symbols_summary()
    return {
        "status": "online",
        "mock_db": FORCE_MOCK,
        "database": db_summary,
        "symbols_count": len(symbols),
        "available_symbols": [s["symbol"] for s in symbols]
    }


@app.get("/api/symbols")
def get_symbols():
    """Return list of distinct symbols currently available in database with stats."""
    repo = get_repo()
    return repo.get_symbols_summary()


@app.get("/api/history/{symbol}")
def get_history(symbol: str, timeframe: str = "15m", source: str = "api", limit: int = 1000):
    """Return historical OHLCV bars formatted for charts, supporting live 15m API."""
    sym = symbol.upper().strip()
    
    if source == "api" or timeframe != "1d":
        yf_client = YFinanceClient(request_delay=0.1)
        period = "60d" if timeframe in ("1m", "5m", "15m", "30m", "60m", "1h") else "max"
        raw_df, err = yf_client.fetch_intraday(sym, interval=timeframe, period=period)
        if raw_df is not None and not raw_df.empty:
            df = raw_df.reset_index()
            dt_col = "Datetime" if "Datetime" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])
            df["TRADE_DATE"] = df[dt_col]
            df["OPEN_PRICE"] = df["Open"]
            df["HIGH_PRICE"] = df["High"]
            df["LOW_PRICE"] = df["Low"]
            df["CLOSE_PRICE"] = df["Close"]
            df["VOLUME"] = df["Volume"]
        else:
            repo = get_repo()
            df = repo.query_historical_prices(sym)
    else:
        repo = get_repo()
        df = repo.query_historical_prices(sym)

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data found for symbol {sym}")

    if len(df) > limit:
        df = df.iloc[-limit:]

    is_intraday = timeframe != "1d"
    records = []
    for _, row in df.iterrows():
        t_date = str(row["TRADE_DATE"])[:16].replace("T", " ") if is_intraday else str(row["TRADE_DATE"])[:10]
        records.append({
            "time": t_date,
            "open": float(row["OPEN_PRICE"]),
            "high": float(row["HIGH_PRICE"]),
            "low": float(row["LOW_PRICE"]),
            "close": float(row["CLOSE_PRICE"]),
            "volume": int(row.get("VOLUME", 0))
        })
    return {
        "symbol": sym,
        "timeframe": timeframe,
        "source": "api" if (source == "api" or timeframe != "1d") else "db",
        "count": len(records),
        "bars": records
    }


@app.get("/api/signals/{symbol}")
def get_signals(
    symbol: str,
    swing_left: int = 3,
    swing_right: int = 2,
    candle_mode: str = "middle_candle",
    min_rr: float = 1.5
):
    """Detect and return Price Action Confluence Signals for a specific symbol."""
    repo = get_repo()
    sym = symbol.upper().strip()
    df = repo.query_historical_prices(sym)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data found for symbol {sym}")

    strat = JohnLucasPruniStrategy(
        swing_left=swing_left,
        swing_right=swing_right,
        candle_validation_mode=candle_mode,
        min_risk_reward=min_rr
    )

    signals = strat.scan_dataframe(df, sym)

    results = []
    for s in signals:
        results.append({
            "signal_id": s.signal_id,
            "symbol": s.symbol,
            "trade_date": str(s.trade_date)[:10],
            "bar_index": s.bar_index,
            "signal_type": s.signal_type,
            "confluence_low": float(s.confluence_low),
            "confluence_high": float(s.confluence_high),
            "confluence_mid": float(s.confluence_mid),
            "gann_75_level": float(s.gann_75_level),
            "limit_price": float(s.limit_price),
            "stop_loss": float(s.stop_loss_price),
            "take_profit": float(s.take_profit_price),
            "risk_reward": float(s.risk_reward_ratio),
            "candle_dominant": s.conditions_met.get("candle_pattern_valid", True),
            "fvg_size": round(abs(s.confluence_high - s.confluence_low), 2),
            "structure_trend": "BULLISH" if s.signal_type == "BUY" else "BEARISH"
        })

    return {
        "symbol": sym,
        "total_signals": len(results),
        "signals": results
    }


@app.get("/api/swings/{symbol}")
def get_swings(
    symbol: str,
    timeframe: str = "15m",
    source: str = "api",
    mult: float = 2.0,
    swing_left: int = 3,
    swing_right: int = 3,
    limit: int = 100
):
    """Detect and return swing points adhering strictly to the 'Phát hiện điểm Swing' specification."""
    sym = symbol.upper().strip()

    if source == "api" or timeframe != "1d":
        yf_client = YFinanceClient(request_delay=0.1)
        period = "60d" if timeframe in ("1m", "5m", "15m", "30m", "60m", "1h") else "max"
        raw_df, err = yf_client.fetch_intraday(sym, interval=timeframe, period=period)
        if raw_df is not None and not raw_df.empty:
            df_raw = raw_df.reset_index()
            dt_col = "Datetime" if "Datetime" in df_raw.columns else ("Date" if "Date" in df_raw.columns else df_raw.columns[0])
            df_raw["TRADE_DATE"] = df_raw[dt_col]
            df_raw["OPEN_PRICE"] = df_raw["Open"]
            df_raw["HIGH_PRICE"] = df_raw["High"]
            df_raw["LOW_PRICE"] = df_raw["Low"]
            df_raw["CLOSE_PRICE"] = df_raw["Close"]
            df_raw["VOLUME"] = df_raw["Volume"]
        else:
            repo = get_repo()
            df_raw = repo.query_historical_prices(sym)
    else:
        repo = get_repo()
        df_raw = repo.query_historical_prices(sym)

    if df_raw.empty:
        raise HTTPException(status_code=404, detail=f"No data found for symbol {sym}")

    from src.strategy.market_structure import MarketStructureTracker, validate_and_clean_data
    df = validate_and_clean_data(df_raw)

    tracker = MarketStructureTracker(
        swing_left=swing_left,
        swing_right=swing_right,
        reversal_mult=mult,
        method="zigzag"
    )
    shs, sls = tracker.detect_swings(df)
    breaks = tracker.compute_all_structure_breaks(df, shs, sls)

    all_swings = [(s.index, s) for s in shs] + [(s.index, s) for s in sls]
    all_swings.sort(key=lambda x: x[0])

    records = []
    prev_price = None
    date_len = 16 if timeframe != "1d" else 10
    for _, s in all_swings[-limit:]:
        pct_change = ((s.price - prev_price) / prev_price * 100.0) if prev_price is not None else None
        prev_price = s.price
        records.append({
            "index": s.index,
            "trade_date": str(s.trade_date)[:date_len].replace("T", " "),
            "price": float(s.price),
            "point_type": s.point_type,
            "structure_type": s.structure_type,
            "confirmed_at_index": s.confirmed_at_index,
            "confirmed_date": str(s.confirmed_date)[:date_len].replace("T", " ") if s.confirmed_date else None,
            "confirmation_delay": s.confirmed_at_index - s.index,
            "atr": float(s.atr_at_candidate) if s.atr_at_candidate else None,
            "reversal_threshold": float(s.reversal_threshold) if s.reversal_threshold else None,
            "volume_ratio": float(s.volume_ratio) if s.volume_ratio else None,
            "pct_change": round(pct_change, 2) if pct_change is not None else None
        })

    return {
        "symbol": sym,
        "timeframe": timeframe,
        "source": "api" if (source == "api" or timeframe != "1d") else "db",
        "total_swings": len(all_swings),
        "swing_highs_count": len(shs),
        "swing_lows_count": len(sls),
        "breaks_count": len(breaks),
        "reversal_mult": mult,
        "swings": records
    }


@app.get("/api/layer2/structure/{symbol}")
def get_layer2_structure(
    symbol: str,
    date: Optional[str] = Query(None, description="Test date in YYYY-MM-DD"),
    datetime: Optional[str] = Query(None, description="Test datetime in YYYY-MM-DD HH:MM[:SS]"),
    timeframe: str = "15m",
    source: str = "api",
    mult: float = 2.0,
    swing_left: int = 3,
    swing_right: int = 3
):
    """
    Layer 2: Market Structure Builder endpoint.
    Builds market structures with optional cutoff date/datetime (Zero Lookahead Bias).
    """
    sym = symbol.upper().strip()
    if source == "api" or timeframe != "1d":
        yf_client = YFinanceClient(request_delay=0.1)
        period = "60d" if timeframe in ("1m", "5m", "15m", "30m", "60m", "1h") else "max"
        raw_df, err = yf_client.fetch_intraday(sym, interval=timeframe, period=period)
        if raw_df is not None and not raw_df.empty:
            df_raw = raw_df.reset_index()
            dt_col = "Datetime" if "Datetime" in df_raw.columns else ("Date" if "Date" in df_raw.columns else df_raw.columns[0])
            df_raw["TRADE_DATE"] = df_raw[dt_col]
            df_raw["OPEN_PRICE"] = df_raw["Open"]
            df_raw["HIGH_PRICE"] = df_raw["High"]
            df_raw["LOW_PRICE"] = df_raw["Low"]
            df_raw["CLOSE_PRICE"] = df_raw["Close"]
            df_raw["VOLUME"] = df_raw["Volume"]
        else:
            repo = get_repo()
            df_raw = repo.query_historical_prices(sym)
    else:
        repo = get_repo()
        df_raw = repo.query_historical_prices(sym)

    if df_raw.empty:
        raise HTTPException(status_code=404, detail=f"No data found for symbol {sym}")

    from src.strategy.market_structure import MarketStructureTracker, MarketStructureBuilder
    tracker = MarketStructureTracker(
        swing_left=swing_left,
        swing_right=swing_right,
        reversal_mult=mult,
        method="zigzag"
    )
    builder = MarketStructureBuilder(tracker=tracker)
    try:
        report = builder.build_structure(
            df=df_raw,
            symbol=sym,
            timeframe=timeframe,
            test_date=date,
            test_datetime=datetime
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error building market structure: {str(e)}")

    return report.to_dict()


def to_native_types(obj):
    if isinstance(obj, dict):
        return {k: to_native_types(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_native_types(v) for v in obj]
    elif hasattr(obj, "item"):
        return obj.item()
    return obj


@app.post("/api/backtest")
def run_backtest_api(req: BacktestRequest):
    """Execute dynamic backtest over selected symbols and return equity curve & trade metrics."""
    repo = get_repo()
    symbols = [s.strip().upper() for s in req.symbols if s.strip()]
    if not symbols:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất 1 mã cổ phiếu.")

    strat = JohnLucasPruniStrategy(
        swing_left=req.swing_left,
        swing_right=req.swing_right,
        candle_validation_mode=req.candle_mode,
        min_risk_reward=req.min_rr,
        entry_mode=req.entry_mode
    )

    exec_engine = VietnamExecutionEngine(
        brokerage_fee_pct=0.0015,
        tax_sell_pct=0.0010,
        slippage_pct=0.0005,
        round_lot_size=100
    )

    engine = BacktestEngine(
        repository=repo,
        strategy=strat,
        execution_engine=exec_engine,
        initial_capital=req.capital,
        position_size_pct=req.position_size,
        long_only=not req.bidirectional
    )

    backtest_res = engine.run_backtest(symbols)
    metrics = to_native_types(backtest_res["portfolio_metrics"])
    trades = backtest_res["trades"]

    # Serialize trades
    trades_list = []
    for t in trades:
        trades_list.append({
            "trade_id": t.trade_id,
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_date": str(t.entry_date)[:10],
            "entry_price": float(t.entry_price),
            "exit_date": str(t.exit_date)[:10],
            "exit_price": float(t.exit_price),
            "exit_reason": t.exit_reason,
            "quantity": int(t.quantity),
            "gross_pnl": float(t.gross_pnl),
            "net_pnl": float(t.net_pnl),
            "return_pct": float(t.return_pct),
            "fees_paid": float(t.commission_paid + t.tax_paid + t.slippage_cost),
            "holding_bars": int(t.holding_bars)
        })

    # Build Chronological Equity Curve
    equity = req.capital
    equity_curve = [{"date": "Start", "equity": equity, "trade_id": "INIT"}]
    for t in trades:
        equity += t.net_pnl
        equity_curve.append({
            "date": str(t.exit_date)[:10],
            "equity": round(equity, 2),
            "symbol": t.symbol,
            "net_pnl": float(t.net_pnl)
        })

    return {
        "run_id": backtest_res["run_id"],
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades_list
    }


@app.get("/api/sensitivity")
def get_sensitivity():
    """Return precomputed or saved parameter sensitivity scan results."""
    csv_path = settings.reports_dir / "parameter_scan_4syms.csv"
    if not csv_path.exists():
        # Look for any parameter_scan*.csv
        scans = list(settings.reports_dir.glob("parameter_scan*.csv"))
        if scans:
            csv_path = scans[-1]
        else:
            return {"status": "no_data", "items": []}

    df = pd.read_csv(csv_path)
    return {
        "status": "ok",
        "file": csv_path.name,
        "items": df.to_dict(orient="records")
    }


@app.post("/api/fetch")
def fetch_symbols_api(req: FetchRequest):
    """Download historical data for new tickers on demand."""
    raw_symbols = [s.strip().upper() for s in req.symbols.split(",") if s.strip()]
    if not raw_symbols:
        raise HTTPException(status_code=400, detail="Chưa nhập mã cổ phiếu.")

    repo = get_repo()
    mgr = SymbolManager(seed_file=settings.vietnam_stocks_csv)
    mgr.load_from_csv(settings.vietnam_stocks_csv)

    client = YFinanceClient(request_delay=0.3)
    validator = DataValidator()
    normalizer = DataNormalizer()
    importer = HistoricalImporter(repo, client, validator, normalizer, mgr)

    # Build targets
    targets = []
    for sym in raw_symbols:
        targets.append({
            "symbol": sym,
            "yahoo_ticker": f"{sym}.VN",
            "company_name": sym,
            "exchange": "HOSE",
            "security_type": "EQUITY",
            "status": "ACTIVE",
            "source": "MANUAL_WEB"
        })

    batch_id = importer.import_symbols(targets, resume=False)
    updated_symbols = repo.get_symbols_summary()

    return {
        "batch_id": batch_id,
        "fetched_count": len(targets),
        "available_symbols": [s["symbol"] for s in updated_symbols]
    }
