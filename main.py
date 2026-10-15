"""
Main CLI Entry Point for Vietnam Stock Market Data Collection & Oracle Storage Pipeline.
Supports commands: init-db, symbols, historical, update, retry-failed, report, verify.
"""

import sys
import argparse
from typing import List, Dict, Any, Optional

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from src.config import settings
from src.import_logger import logger
from src.symbol_manager import SymbolManager
from src.yfinance_client import YFinanceClient
from src.oracle_repository import get_repository, OracleConnectionError
from src.historical_importer import HistoricalImporter
from src.incremental_updater import IncrementalUpdater
from src.data_reporter import DataReporter
from src.backtest_helper import BacktestHelper


def get_target_symbols(args, symbol_mgr: SymbolManager) -> List[Dict[str, Any]]:
    """Determine targets based on CLI arguments."""
    symbols_arg = getattr(args, "symbols", None)
    if symbols_arg:
        return symbol_mgr.parse_symbol_inputs(symbols_arg)

    exchange_arg = getattr(args, "exchange", None)
    exchanges = [e.strip() for e in exchange_arg.split(",")] if exchange_arg else None
    return symbol_mgr.filter_symbols(
        exchanges=exchanges,
        limit=getattr(args, "limit", None)
    )


def cmd_init_db(args):
    """Initialize Oracle Database Schema."""
    logger.info("Executing init-db command...")
    mock_mode = getattr(args, "mock_db", False)
    repo = get_repository(force_mock=mock_mode)

    # Health check
    is_ok, msg = repo.check_connection()
    logger.info(f"Connection check: {msg}")
    if not is_ok and not mock_mode:
        logger.error(
            "Cannot connect to Oracle Database. Please check ORACLE_* variables in .env "
            "or run with --mock-db for local testing."
        )
        sys.exit(1)

    success, init_msg = repo.init_schema()
    if success:
        logger.info(f"Schema status: {init_msg}")
    else:
        logger.error(f"Schema initialization failed: {init_msg}")
        sys.exit(1)


def cmd_symbols(args):
    """Import and inspect symbol list."""
    logger.info("Executing symbols command...")
    csv_path = getattr(args, "csv_path", None)
    mgr = SymbolManager(seed_file=csv_path)
    df = mgr.load_from_csv(csv_path)

    targets = get_target_symbols(args, mgr)
    print(f"\n--- DANH MỤC MÃ CHỨNG KHOÁN (Tổng nạp: {len(df)}, Khớp bộ lọc: {len(targets)}) ---")
    for item in targets[:30]:
        print(f"[{item['exchange']:<5}] {item['symbol']:<8} -> {item['yahoo_ticker']:<12} | {item['company_name'][:40]}")
    if len(targets) > 30:
        print(f"... và {len(targets) - 30} mã khác.")

    if getattr(args, "save_to_db", False):
        repo = get_repository(force_mock=getattr(args, "mock_db", False))
        count = repo.upsert_symbols(targets)
        logger.info(f"Saved {count} symbols into database.")


def cmd_historical(args):
    """Fetch complete historical market data."""
    logger.info("Executing historical command...")
    csv_path = getattr(args, "csv_path", None)
    mgr = SymbolManager(seed_file=csv_path)
    mgr.load_from_csv(csv_path)
    targets = get_target_symbols(args, mgr)

    if not targets:
        logger.warning("No symbols matched criteria.")
        return

    repo = get_repository(force_mock=getattr(args, "mock_db", False))
    importer = HistoricalImporter(repository=repo)
    importer.import_symbols(
        symbols_meta=targets,
        start_date=getattr(args, "start_date", None),
        end_date=getattr(args, "end_date", None),
        resume=not getattr(args, "no_resume", False)
    )


def cmd_update(args):
    """Synchronize latest price data incrementally."""
    logger.info("Executing update command...")
    csv_path = getattr(args, "csv_path", None)
    mgr = SymbolManager(seed_file=csv_path)
    mgr.load_from_csv(csv_path)
    targets = get_target_symbols(args, mgr)

    if not targets:
        logger.warning("No symbols matched criteria.")
        return

    repo = get_repository(force_mock=getattr(args, "mock_db", False))
    updater = IncrementalUpdater(repository=repo)
    updater.update_symbols(symbols_meta=targets, force_days_back=getattr(args, "days_back", None))


def cmd_retry_failed(args):
    """Retry failed symbols from previous import batches."""
    logger.info("Executing retry-failed command...")
    repo = get_repository(force_mock=getattr(args, "mock_db", False))
    failed_syms = repo.get_failed_symbols(batch_id=getattr(args, "batch_id", None))

    if not failed_syms:
        logger.info("No failed symbols found in database logs.")
        return

    logger.info(f"Found {len(failed_syms)} failed symbols to retry: {', '.join(failed_syms[:10])}...")
    csv_path = getattr(args, "csv_path", None)
    mgr = SymbolManager(seed_file=csv_path)
    mgr.load_from_csv(csv_path)
    targets = mgr.parse_symbol_inputs(failed_syms)

    importer = HistoricalImporter(repository=repo)
    importer.import_symbols(targets, resume=False)


def cmd_verify(args):
    """Verify stored records and query database summary."""
    logger.info("Executing verify command...")
    repo = get_repository(force_mock=getattr(args, "mock_db", False))
    summary = repo.get_database_summary()

    print("\n" + "=" * 60)
    print("      TỔNG KẾT DỮ LIỆU ĐÃ LƯU TRONG CƠ SỞ DỮ LIỆU")
    print("=" * 60)
    print(f" Tổng số mã trong STOCK_SYMBOLS : {summary['total_symbols']:,}")
    print(f" Số mã có dữ liệu giá           : {summary['symbols_with_prices']:,}")
    print(f" Tổng số bản ghi giá lịch sử    : {summary['total_price_records']:,}")
    print(f" Ngày giao dịch sớm nhất        : {summary['earliest_date']}")
    print(f" Ngày giao dịch mới nhất        : {summary['latest_date']}")
    print(f" Tổng số nhật ký import         : {summary['total_logs']:,}")
    print(f" Tổng số sự kiện DN (Events)    : {summary['total_events']:,}")
    print("=" * 60 + "\n")

    # Sample query test
    symbols_arg = getattr(args, "symbols", None)
    if symbols_arg:
        test_sym = symbols_arg.split(",")[0].strip().upper()
        helper = BacktestHelper(repo)
        df = helper.get_symbol_history(test_sym)
        if not df.empty:
            print(f"--- Mẫu 5 ngày gần nhất của mã {test_sym} ---")
            print(df[["OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "ADJ_CLOSE", "VOLUME"]].tail())


def cmd_report(args):
    """Export coverage and quality report from database logs."""
    logger.info("Executing report command...")
    repo = get_repository(force_mock=getattr(args, "mock_db", False))
    summary = repo.get_database_summary()
    print("Báo cáo hiện trạng cơ sở dữ liệu:")
    for k, v in summary.items():
        print(f" - {k}: {v}")


def cmd_signals(args):
    """Scan and display Price Action Confluence Signals."""
    logger.info("Executing signals command...")
    repo = get_repository(force_mock=getattr(args, "mock_db", False))
    mgr = SymbolManager(seed_file=getattr(args, "csv_path", None))
    mgr.load_from_csv(getattr(args, "csv_path", None))
    targets = get_target_symbols(args, mgr)
    target_symbols = [t["symbol"] for t in targets]

    if not target_symbols:
        logger.warning("No symbols selected.")
        return

    from src.strategy.strategy_engine import JohnLucasPruniStrategy
    strat = JohnLucasPruniStrategy(
        swing_left=getattr(args, "swing_left", 3),
        swing_right=getattr(args, "swing_right", 2),
        candle_validation_mode=getattr(args, "candle_mode", "middle_candle"),
        min_risk_reward=getattr(args, "min_rr", 1.5)
    )

    print("\n" + "=" * 70)
    print("    TÍN HIỆU HỢP LƯU GIÁ (JOHN LUCAS PRUNI - 2 CẤU TRÚC & 3 CÂY NẾN)")
    print("=" * 70)

    total_found = 0
    for sym in target_symbols:
        df = repo.query_historical_prices(sym, start_date=getattr(args, "start_date", None), end_date=getattr(args, "end_date", None))
        if df.empty or len(df) < 15:
            continue
        signals = strat.scan_dataframe(df, sym)
        if signals:
            total_found += len(signals)
            print(f"\n>> Mã: {sym} ({len(signals)} tín hiệu phát hiện)")
            for s in signals[-5:]:  # show latest 5
                print(f"  [{str(s.trade_date)[:10]}] {s.signal_type:<4} | Vùng: [{s.confluence_low:,.0f} - {s.confluence_high:,.0f}] | Limit: {s.limit_price:,.0f} | SL: {s.stop_loss_price:,.0f} | TP: {s.take_profit_price:,.0f} | R:R: {s.risk_reward_ratio}")

    print("\n" + "-" * 70)
    print(f"Tổng số tín hiệu hợp lưu phát hiện: {total_found}")
    print("=" * 70 + "\n")


def cmd_backtest(args):
    """Execute backtest for John Lucas Pruni Strategy."""
    logger.info("Executing backtest command...")
    repo = get_repository(force_mock=getattr(args, "mock_db", False))
    mgr = SymbolManager(seed_file=getattr(args, "csv_path", None))
    mgr.load_from_csv(getattr(args, "csv_path", None))
    targets = get_target_symbols(args, mgr)
    target_symbols = [t["symbol"] for t in targets]

    if not target_symbols:
        logger.warning("No symbols selected for backtest.")
        return

    from src.strategy.strategy_engine import JohnLucasPruniStrategy
    from src.backtest.execution_models import VietnamExecutionEngine
    from src.backtest.backtest_engine import BacktestEngine

    strat = JohnLucasPruniStrategy(
        swing_left=getattr(args, "swing_left", 3),
        swing_right=getattr(args, "swing_right", 2),
        candle_validation_mode=getattr(args, "candle_mode", "middle_candle"),
        entry_mode=getattr(args, "entry_mode", "zone_boundary"),
        min_risk_reward=getattr(args, "min_rr", 1.5)
    )
    exec_engine = VietnamExecutionEngine(
        same_bar_collision=getattr(args, "same_bar_collision", "sl_first")
    )
    engine = BacktestEngine(
        repository=repo,
        strategy=strat,
        execution_engine=exec_engine,
        initial_capital=getattr(args, "capital", 100_000_000.0),
        position_size_pct=getattr(args, "position_size", 0.20),
        long_only=not getattr(args, "bidirectional", False)
    )

    res = engine.run_backtest(
        symbols=target_symbols,
        start_date=getattr(args, "start_date", None),
        end_date=getattr(args, "end_date", None)
    )

    # Save to database
    try:
        repo.save_backtest_run(
            run_data={
                "run_id": res["run_id"],
                "symbols": target_symbols,
                "start_date": getattr(args, "start_date", "2010-01-01"),
                "end_date": getattr(args, "end_date", "2026-10-15"),
                "initial_capital": getattr(args, "capital", 100_000_000.0)
            },
            signals=res["signals"],
            orders=res["orders"],
            trades=res["trades"],
            metrics=res["portfolio_metrics"]
        )
        logger.info(f"Saved backtest run [{res['run_id']}] to database.")
    except Exception as e:
        logger.warning(f"Could not save run to database: {e}")

    # Export CSV & Markdown
    csv_p, md_p = engine.export_results(res)

    # Print summary
    m = res["portfolio_metrics"]
    banner = "=" * 70
    print("\n" + banner)
    print("      KẾT QUẢ BACKTEST CHIẾN LƯỢC JOHN LUCAS PRUNI (2 CẤU TRÚC & 3 NẾN)")
    print(banner)
    print(f" Mã đợt chạy (Run ID)        : {res['run_id']}")
    print(f" Danh mục cổ phiếu           : {', '.join(target_symbols)}")
    print(f" Tổng tín hiệu phát hiện     : {res['total_signals_detected']}")
    print(f" Số lệnh Limit được đặt      : {res['total_orders_placed']}")
    print(f" Số giao dịch đã khớp & đóng : {res['total_trades_executed']}")
    print("-" * 70)
    print(f" Tỷ lệ thắng (Win Rate)      : {m['win_rate_pct']}% ({m['win_count']} Thắng / {m['loss_count']} Thua)")
    print(f" Tỷ lệ Thắng / Thua (W/L)    : {m['win_loss_pnl_ratio']} (Avg Win: {m['avg_win']:,.0f} | Avg Loss: {m['avg_loss']:,.0f})")
    print(f" Hệ số lợi nhuận (Profit Fac): {m['profit_factor']}")
    print(f" Kỳ vọng / Lệnh (EV / Trade) : {m['expected_value_per_trade']:,.2f} VND")
    print(f" Lợi nhuận ròng (Net PnL)    : {m['net_pnl']:,.2f} VND (ROI: {m['roi_pct']}%)")
    print(f" Tổng thuế & phí giao dịch   : {m['total_fees_and_taxes']:,.2f} VND")
    print(f" Mức sụt giảm tối đa (MDD)   : {m['max_drawdown_pct']}% ({m['max_drawdown_amount']:,.2f} VND)")
    print(f" Chuỗi thua dài nhất         : {m['max_consecutive_losses']} lệnh liên tiếp")
    print(f" Đánh giá nhận định Winrate 30%: {'KHẢ THI VỚI R:R CAO' if m['win_rate_30pct_viable'] else 'CHƯA ĐẠT KỲ VỌNG DƯƠNG'}")
    print(f" Kết luận tổng quan          : {m['evaluation_verdict']}")
    print(banner + "\n")


def cmd_scan_params(args):
    """Run parameter sensitivity grid scan."""
    logger.info("Executing scan-params command...")
    repo = get_repository(force_mock=getattr(args, "mock_db", False))
    mgr = SymbolManager(seed_file=getattr(args, "csv_path", None))
    mgr.load_from_csv(getattr(args, "csv_path", None))
    targets = get_target_symbols(args, mgr)
    target_symbols = [t["symbol"] for t in targets]

    if not target_symbols:
        logger.warning("No symbols selected for scan.")
        return

    from src.backtest.parameter_scanner import ParameterScanner
    scanner = ParameterScanner(repository=repo)
    df_results = scanner.run_grid_scan(
        symbols=target_symbols,
        start_date=getattr(args, "start_date", None),
        end_date=getattr(args, "end_date", None)
    )

    print("\n" + "=" * 80)
    print("      KẾT QUẢ QUÉT ĐỘ NHẠY THAM SỐ (PARAMETER SENSITIVITY GRID)")
    print("=" * 80)
    print(df_results[["parameters", "total_trades", "win_rate_pct", "profit_factor", "net_pnl", "max_drawdown_pct", "verdict"]].to_string(index=False))
    print("=" * 80 + "\n")

    out_csv = settings.reports_dir / f"parameter_scan_{len(target_symbols)}syms.csv"
    df_results.to_csv(out_csv, index=False, encoding="utf-8-sig")
    logger.info(f"Saved sensitivity grid scan to {out_csv}")


def cmd_web(args):
    """Launch FastAPI interactive web dashboard."""
    import uvicorn
    import webbrowser
    import src.web.app as web_module
    from src.web.app import app

    web_module.FORCE_MOCK = getattr(args, "mock_db", True)
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8000)
    url = f"http://{host}:{port}"
    print("\n" + "=" * 70)
    print("    VNSTOCK QUANTITATIVE DASHBOARD (PRICE ACTION JOHN LUCAS PRUNI)")
    print("=" * 70)
    print(f" >> Giao diện Web đang chạy tại: {url}")
    print(f" >> Cơ sở dữ liệu: {'Oracle Database' if not web_module.FORCE_MOCK else 'SQLite Mock (Cục bộ)'}")
    print(" >> Nhấn Ctrl + C để dừng máy chủ web.")
    print("=" * 70 + "\n")

    if not getattr(args, "no_browser", False):
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run(app, host=host, port=port, log_level="warning")


def main():
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--mock-db", action="store_true", default=argparse.SUPPRESS, help="Use local SQLite mock storage for testing")
    common_parser.add_argument("--csv-path", type=str, default=argparse.SUPPRESS, help="Custom symbols CSV file path")
    common_parser.add_argument("--symbols", type=str, default=argparse.SUPPRESS, help="Comma-separated symbols (e.g. HPG,VNM,SSI)")
    common_parser.add_argument("--exchange", type=str, default=argparse.SUPPRESS, help="Filter by exchange (HOSE,HNX,UPCoM)")
    common_parser.add_argument("--limit", type=int, default=argparse.SUPPRESS, help="Limit number of symbols to process")

    parser = argparse.ArgumentParser(
        description="Vietnam Stock Market Data Collection & Oracle Storage Pipeline",
        parents=[common_parser]
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Sub-commands")

    # init-db
    subparsers.add_parser("init-db", parents=[common_parser], help="Initialize Oracle database schema")

    # symbols
    sym_parser = subparsers.add_parser("symbols", parents=[common_parser], help="Manage and inspect stock symbols list")
    sym_parser.add_argument("--save-to-db", action="store_true", help="Save loaded symbols to database")

    # historical (alias: fetch)
    hist_parser = subparsers.add_parser("historical", aliases=["fetch"], parents=[common_parser], help="Download complete historical OHLCV data")
    hist_parser.add_argument("--start-date", type=str, default=None, help="Start date (YYYY-MM-DD)")
    hist_parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")
    hist_parser.add_argument("--history", type=str, default="max", help="History period e.g. max, 1y, 5y")
    hist_parser.add_argument("--no-resume", action="store_true", help="Disable resume from last state")

    # update (alias: sync)
    upd_parser = subparsers.add_parser("update", aliases=["sync"], parents=[common_parser], help="Incrementally synchronize recent data")
    upd_parser.add_argument("--days-back", type=int, default=None, help="Force sync last N days")

    # retry-failed
    retry_parser = subparsers.add_parser("retry-failed", parents=[common_parser], help="Retry failed tickers from logs")
    retry_parser.add_argument("--batch-id", type=str, default=None, help="Target specific batch ID")

    # verify
    subparsers.add_parser("verify", parents=[common_parser], help="Verify and summarize stored database records")

    # report
    subparsers.add_parser("report", parents=[common_parser], help="Show summary report")

    # signals
    sig_parser = subparsers.add_parser("signals", parents=[common_parser], help="Scan confluence price action signals")
    sig_parser.add_argument("--swing-left", type=int, default=3, help="Swing left lookback bars")
    sig_parser.add_argument("--swing-right", type=int, default=2, help="Swing right confirmation bars")
    sig_parser.add_argument("--candle-mode", type=str, default="middle_candle", help="Candle dominance mode (middle_candle, all_candles, cumulative)")
    sig_parser.add_argument("--min-rr", type=float, default=1.5, help="Minimum Risk/Reward ratio")
    sig_parser.add_argument("--start-date", type=str, default=None, help="Start date (YYYY-MM-DD)")
    sig_parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")

    # backtest
    bt_parser = subparsers.add_parser("backtest", parents=[common_parser], help="Run backtesting simulation")
    bt_parser.add_argument("--capital", type=float, default=100_000_000.0, help="Initial capital in VND")
    bt_parser.add_argument("--position-size", type=float, default=0.20, help="Fraction of capital per position (default 0.20 = 20%)")
    bt_parser.add_argument("--swing-left", type=int, default=3, help="Swing left lookback bars")
    bt_parser.add_argument("--swing-right", type=int, default=2, help="Swing right confirmation bars")
    bt_parser.add_argument("--candle-mode", type=str, default="middle_candle", help="Candle dominance mode")
    bt_parser.add_argument("--entry-mode", type=str, default="zone_boundary", help="Limit entry mode (zone_boundary or zone_midpoint)")
    bt_parser.add_argument("--min-rr", type=float, default=1.5, help="Minimum Risk/Reward ratio")
    bt_parser.add_argument("--same-bar-collision", type=str, default="sl_first", help="Same-bar collision handling (sl_first or tp_first)")
    bt_parser.add_argument("--bidirectional", action="store_true", help="Allow Short selling (default is Long-Only for VN spot)")
    bt_parser.add_argument("--start-date", type=str, default=None, help="Start date (YYYY-MM-DD)")
    bt_parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")

    # scan-params
    scan_parser = subparsers.add_parser("scan-params", parents=[common_parser], help="Run parameter sensitivity analysis")
    scan_parser.add_argument("--start-date", type=str, default=None, help="Start date (YYYY-MM-DD)")
    scan_parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")

    # web
    web_parser = subparsers.add_parser("web", parents=[common_parser], help="Launch interactive web dashboard")
    web_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface")
    web_parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    web_parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")

    parsed = parser.parse_args()

    try:
        if parsed.command == "init-db":
            cmd_init_db(parsed)
        elif parsed.command == "symbols":
            cmd_symbols(parsed)
        elif parsed.command in ("historical", "fetch"):
            cmd_historical(parsed)
        elif parsed.command in ("update", "sync"):
            cmd_update(parsed)
        elif parsed.command == "retry-failed":
            cmd_retry_failed(parsed)
        elif parsed.command == "verify":
            cmd_verify(parsed)
        elif parsed.command == "report":
            cmd_report(parsed)
        elif parsed.command == "signals":
            cmd_signals(parsed)
        elif parsed.command == "backtest":
            cmd_backtest(parsed)
        elif parsed.command == "scan-params":
            cmd_scan_params(parsed)
        elif parsed.command == "web":
            cmd_web(parsed)
    except OracleConnectionError as e:
        logger.error(f"Oracle Database Error: {e}")
        logger.info("TIP: To test without an active Oracle server, run with the '--mock-db' flag.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Execution Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
