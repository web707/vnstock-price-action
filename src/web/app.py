"""
FastAPI Web Application Backend for Vietnam Stock Price Action Dashboard.
Provides interactive APIs for Charts, Signals, Backtesting, Sensitivity, and Data Ingestion.
"""

from typing import List, Dict, Any, Optional
import os
import sqlite3
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
from src.web.market_data import load_market_data


app = FastAPI(
    title="VNStock Price Action Dashboard",
    description="Interactive Web Platform for John Lucas Pruni Price Action Strategy & Vietnam Stock Data",
    version="2.0.0"
)

from src.web.auth import router as auth_router, guard
app.middleware('http')(guard)
app.include_router(auth_router)

@app.get('/login', response_class=HTMLResponse)
def login_page():
    return (Path(__file__).parent / 'templates' / 'login.html').read_text(encoding='utf-8')

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
        "database_file": Path(repo.db_path).name if FORCE_MOCK else None,
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
    """Return validated candles; no source/timeframe fallback."""
    if not 1 <= limit <= 10000:
        raise HTTPException(422, detail="limit must be between 1 and 10000")
    df, metadata = load_market_data(symbol, timeframe, source, get_repo, YFinanceClient)
    sym = metadata['symbol']

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
        "source": source,
        "metadata": metadata,
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
    df, metadata = load_market_data(symbol, '1d', 'db', get_repo, YFinanceClient)
    sym = metadata['symbol']

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
        "timeframe": "1d",
        "source": "db",
        "metadata": metadata,
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
    df_raw, metadata = load_market_data(symbol, timeframe, source, get_repo, YFinanceClient)
    sym = metadata['symbol']

    if not 1 <= limit <= 10000 or swing_left < 1 or swing_right < 1 or mult <= 0:
        raise HTTPException(422, detail="Invalid swing parameters")

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
        "source": source,
        "metadata": metadata,
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
    df_raw, metadata = load_market_data(symbol, timeframe, source, get_repo, YFinanceClient)
    sym = metadata['symbol']

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

    result = report.to_dict()
    result['metadata'] = metadata
    result['metadata']['requested_cutoff'] = datetime or date
    return result


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
    mgr = SymbolManager(seed_file=settings.default_symbols_file)
    mgr.load_from_csv(settings.default_symbols_file)

    client = YFinanceClient(request_delay=0.3)
    importer = HistoricalImporter(repository=repo, yf_client=client)

    # Reuse known exchange metadata; never label an unknown symbol as HOSE.
    targets = mgr.parse_symbol_inputs(list(dict.fromkeys(raw_symbols)))
    known = set(mgr.symbols_df['symbol'])
    for target in targets:
        if target['symbol'] not in known:
            target['exchange'] = 'UNKNOWN'

    reporter = importer.import_symbols(targets, resume=False)
    summary = reporter.generate_summary()
    updated_symbols = repo.get_symbols_summary()

    return {
        "batch_id": reporter.batch_id,
        "status": "ok" if summary['successful_symbols'] == len(targets) else "incomplete",
        "requested_count": len(targets),
        "fetched_count": summary['successful_symbols'] + summary['partial_symbols'],
        "summary": summary,
        "results": reporter.symbol_stats,
        "available_symbols": [s["symbol"] for s in updated_symbols]
    }


@app.get('/api/data-quality')
def data_quality_report():
    """Serve an explicitly generated audit, only when it matches the active SQLite file."""
    import json
    from src.data_quality import assert_report_matches
    if not FORCE_MOCK:
        raise HTTPException(409, 'Báo cáo này chỉ áp dụng cho SQLite.')
    report_path = settings.reports_dir / 'data_quality.json'
    if not report_path.exists():
        raise HTTPException(404, 'Chưa có báo cáo. Chạy audit_quality.py với database đang dùng.')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    repo = get_repo()
    try:
        assert_report_matches(report, repo.db_path)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc))
    return report

# Research endpoints use closed daily database candles and never place orders.
from src.research import analyze, size_position
from src.discovery import read_catalog, rank_catalog, db_revision, research_cache
from src.web.market_data import validate_request
from pydantic import Field

class ResearchScanRequest(BaseModel):
    symbols: List[str] = Field(min_length=1, max_length=30)

class PositionRequest(BaseModel):
    capital: float = Field(gt=0, allow_inf_nan=False)
    entry: float = Field(gt=0, allow_inf_nan=False)
    stop: float = Field(gt=0, allow_inf_nan=False)
    target: float = Field(gt=0, allow_inf_nan=False)
    risk_pct: float = Field(default=1, gt=0, le=5)
    max_position_pct: float = Field(default=20, gt=0, le=100)
    fee_pct: float = Field(default=0.15, ge=0, le=5)
    sell_tax_pct: float = Field(default=0.1, ge=0, le=5)
    slippage_pct: float = Field(default=0.1, ge=0, le=5)
    lot: int = 100

@app.get('/api/research/{symbol}')
def research_symbol(symbol: str):
    symbol=validate_request(symbol,'1d','db')
    repo=get_repo()
    revision=db_revision(getattr(repo,'db_path',None)) if FORCE_MOCK else None
    day=pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').date().isoformat()
    key=(revision,day,symbol) if revision is not None else None
    cached=research_cache.get(key)
    if cached is not None:
        cached['cache_hit']=True
        return cached
    df,meta=load_market_data(symbol,'1d','db',lambda:repo,YFinanceClient)
    result={'symbol':meta['symbol'],'metadata':meta,**analyze(df),'cache_hit':False}
    result['calculated_at']=pd.Timestamp.now(tz='UTC').isoformat()
    if revision==db_revision(getattr(repo,'db_path',None)):
        research_cache.put(key,result)
    return result

@app.post('/api/research-scan')
def research_scan(req: ResearchScanRequest):
    items=[]
    for symbol in dict.fromkeys(s.strip().upper() for s in req.symbols):
        try:items.append(research_symbol(symbol))
        except HTTPException as exc:
            items.append({'symbol':symbol,'status':'ERROR','score':None,'error':exc.detail})
    items.sort(key=lambda x:(x['score'] is None,-(x['score'] or 0),x['symbol']))
    return {'items':items,'scope':'Chỉ các mã yêu cầu; không đại diện toàn thị trường.',
            'warning':'Điểm quy tắc không phải xác suất. Phải đọc trạng thái chất lượng và ngày dữ liệu.'}

@app.post('/api/position-size')
def position_size(req: PositionRequest):
    try:return size_position(**req.model_dump())
    except ValueError as exc:raise HTTPException(422,str(exc))


@app.get('/api/catalog-search')
def catalog_search(q: str=Query(default='',max_length=100), exchange: str=Query(default='',pattern='^(|HOSE|HNX|UPCOM)$'), has_data: bool=False, limit: int=Query(default=20,ge=1,le=100)):
    if not FORCE_MOCK:raise HTTPException(409,'Tìm kiếm toàn danh mục hiện hỗ trợ SQLite.')
    try:items=read_catalog(get_repo().db_path)
    except (OSError,ValueError,sqlite3.Error) as exc:raise HTTPException(503,'Không đọc được danh mục.') from exc
    return {**rank_catalog(items,q,exchange,has_data,limit),
            'catalog_count':len(items),'with_prices':sum(x['bars_count']>0 for x in items),
            'scope':'Danh mục trong database; chưa đối chiếu danh sách niêm yết hiện tại.'}

from src.evidence import evaluate
from typing import Literal

class EvidenceRequest(BaseModel):
    symbol: str = Field(min_length=1,max_length=20)
    horizon: Literal[5,10,20] = 10
    threshold: int = Field(default=70,ge=0,le=100)
    min_volume: float = Field(default=100000,ge=0,le=1e12,allow_inf_nan=False)
    fee_pct: float = Field(default=.15,ge=0,le=5,allow_inf_nan=False)
    tax_pct: float = Field(default=.1,ge=0,le=5,allow_inf_nan=False)
    slippage_pct: float = Field(default=.1,ge=0,le=5,allow_inf_nan=False)

@app.post('/api/evidence')
def evaluate_evidence(req: EvidenceRequest):
    df,meta=load_market_data(req.symbol,'1d','db',get_repo,YFinanceClient)
    try:result=evaluate(df,**req.model_dump(exclude={'symbol'}))
    except ValueError as exc:raise HTTPException(422,str(exc))
    return {'symbol':meta['symbol'],'metadata':meta,**result}

from src.phase7.api import router as phase7_router
app.include_router(phase7_router)

from src.phase8.api import router as phase8_router
app.include_router(phase8_router)
