"""
Backtest Engine Module.
Executes walk-forward backtesting simulations across Vietnam stock tickers
strictly free of lookahead bias, with full transaction accounting and reporting.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import uuid
from pathlib import Path
import pandas as pd
from src.config import settings
from src.import_logger import logger
from src.strategy.strategy_engine import JohnLucasPruniStrategy
from src.strategy.confluence import ConfluenceSignal
from src.backtest.execution_models import Order, Trade, VietnamExecutionEngine
from src.backtest.performance_metrics import PerformanceMetricsCalculator


class BacktestEngine:
    """Executes event-driven backtesting for John Lucas Pruni Price Action strategy."""

    def __init__(
        self,
        repository,
        strategy: Optional[JohnLucasPruniStrategy] = None,
        execution_engine: Optional[VietnamExecutionEngine] = None,
        initial_capital: float = 100_000_000.0,
        position_size_pct: float = 0.20,  # 20% capital per position
        long_only: bool = True,           # Vietnam spot stock market is Long-Only
        max_active_positions: int = 1
    ):
        self.repo = repository
        self.strategy = strategy or JohnLucasPruniStrategy()
        self.execution_engine = execution_engine or VietnamExecutionEngine()
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.long_only = long_only
        self.max_active_positions = max_active_positions

    def run_backtest(
        self,
        symbols: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute full portfolio or single-stock walk-forward backtest.
        """
        run_id = run_id or f"RUN_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        logger.info(f"Starting Backtest Run [{run_id}] for {len(symbols)} symbol(s)...")

        all_signals: List[ConfluenceSignal] = []
        all_orders: List[Order] = []
        all_trades: List[Trade] = []
        per_symbol_results: Dict[str, Any] = {}

        for sym in symbols:
            logger.info(f"Backtesting symbol: {sym}...")
            df = self.repo.query_historical_prices(sym, start_date=start_date, end_date=end_date)
            if df.empty or len(df) < 15:
                logger.warning(f"Insufficient historical data for {sym} (records: {len(df)})")
                continue

            # Format dates if needed
            if "TRADE_DATE" in df.columns:
                df["TRADE_DATE"] = [d.date() if hasattr(d, "date") else d for d in pd.to_datetime(df["TRADE_DATE"])]

            # 1. Scan signals across time series
            signals = self.strategy.scan_dataframe(df, sym)
            all_signals.extend(signals)

            # Filter for Long-Only if configured for Vietnam spot equity
            if self.long_only:
                target_signals = [s for s in signals if s.signal_type == "BUY"]
            else:
                target_signals = signals

            logger.info(f"Detected {len(signals)} total confluence signals ({len(target_signals)} executable) for {sym}")

            # 2. Simulate orders and trades walk-forward
            sym_orders: List[Order] = []
            sym_trades: List[Trade] = []

            # Map signals by bar_index
            sig_by_bar: Dict[int, List[ConfluenceSignal]] = {}
            for s in target_signals:
                sig_by_bar.setdefault(s.bar_index, []).append(s)

            pending_orders: List[Order] = []
            active_position_order: Optional[Order] = None

            n = len(df)
            for bar_idx in range(n):
                row = df.iloc[bar_idx]
                t_date = row["TRADE_DATE"] if "TRADE_DATE" in row else df.index[bar_idx]

                # Step A: Evaluate active position for SL / TP exit
                if active_position_order is not None:
                    closed_trade = self.execution_engine.evaluate_open_position(
                        active_position_order, bar_idx, row, t_date
                    )
                    if closed_trade is not None:
                        sym_trades.append(closed_trade)
                        active_position_order = None

                # Step B: Evaluate pending limit orders for fill (only if no active position)
                remaining_pending = []
                for p_order in pending_orders:
                    # An order can only fill at a bar SUBSEQUENT to its placement (bar_idx > placed_bar_idx)
                    if bar_idx > p_order.placed_bar_idx and active_position_order is None:
                        is_filled = self.execution_engine.evaluate_pending_order(p_order, bar_idx, row, t_date)
                        if is_filled:
                            active_position_order = p_order
                            continue
                    # Keep if still pending
                    if p_order.status == "PENDING":
                        # Also check expiry
                        if (bar_idx - p_order.placed_bar_idx) > self.execution_engine.max_pending_bars:
                            p_order.status = "EXPIRED"
                        else:
                            remaining_pending.append(p_order)

                pending_orders = remaining_pending

                # Step C: Check if a new signal was created at close of this bar
                if bar_idx in sig_by_bar and active_position_order is None and len(pending_orders) < self.max_active_positions:
                    for sig in sig_by_bar[bar_idx]:
                        # Calculate position quantity (100 shares round lots)
                        allocated_capital = self.initial_capital * self.position_size_pct
                        raw_shares = int(allocated_capital / sig.limit_price)
                        quantity = (raw_shares // self.execution_engine.round_lot_size) * self.execution_engine.round_lot_size

                        if quantity > 0:
                            order = Order(
                                order_id=f"ORD_{sig.signal_id}",
                                signal_id=sig.signal_id,
                                symbol=sym,
                                order_type="BUY_LIMIT" if sig.signal_type == "BUY" else "SELL_LIMIT",
                                placed_bar_idx=bar_idx,
                                placed_date=t_date,
                                limit_price=sig.limit_price,
                                stop_loss=sig.stop_loss_price,
                                take_profit=sig.take_profit_price,
                                quantity=quantity,
                                status="PENDING"
                            )
                            pending_orders.append(order)
                            sym_orders.append(order)

            # Close any open trade at end of data
            if active_position_order is not None and len(df) > 0:
                last_row = df.iloc[-1]
                last_date = last_row["TRADE_DATE"] if "TRADE_DATE" in last_row else df.index[-1]
                pnl_info = self.execution_engine.calculate_trade_pnl(
                    direction="LONG" if active_position_order.order_type == "BUY_LIMIT" else "SHORT",
                    entry_price=active_position_order.fill_price or active_position_order.limit_price,
                    exit_price=float(last_row["CLOSE_PRICE"]),
                    quantity=active_position_order.quantity
                )
                sym_trades.append(Trade(
                    trade_id=f"TRD_{active_position_order.order_id}_EOD",
                    order_id=active_position_order.order_id,
                    symbol=sym,
                    direction="LONG" if active_position_order.order_type == "BUY_LIMIT" else "SHORT",
                    entry_bar_idx=active_position_order.fill_bar_idx or active_position_order.placed_bar_idx,
                    entry_date=active_position_order.fill_date or active_position_order.placed_date,
                    entry_price=active_position_order.fill_price or active_position_order.limit_price,
                    exit_bar_idx=len(df) - 1,
                    exit_date=last_date,
                    exit_price=float(last_row["CLOSE_PRICE"]),
                    exit_reason="END_OF_DATA",
                    quantity=active_position_order.quantity,
                    gross_pnl=pnl_info["gross_pnl"],
                    net_pnl=pnl_info["net_pnl"],
                    return_pct=pnl_info["return_pct"],
                    commission_paid=pnl_info["commission_paid"],
                    tax_paid=pnl_info["tax_paid"],
                    slippage_cost=pnl_info["slippage_cost"],
                    holding_bars=(len(df) - 1) - (active_position_order.fill_bar_idx or 0)
                ))

            all_orders.extend(sym_orders)
            all_trades.extend(sym_trades)
            per_symbol_results[sym] = PerformanceMetricsCalculator.calculate_metrics(sym_trades, self.initial_capital)

        # Overall Portfolio Metrics
        portfolio_metrics = PerformanceMetricsCalculator.calculate_metrics(all_trades, self.initial_capital)

        return {
            "run_id": run_id,
            "symbols": symbols,
            "start_date": start_date,
            "end_date": end_date,
            "total_signals_detected": len(all_signals),
            "total_orders_placed": len(all_orders),
            "total_trades_executed": len(all_trades),
            "portfolio_metrics": portfolio_metrics,
            "per_symbol_metrics": per_symbol_results,
            "trades": all_trades,
            "orders": all_orders,
            "signals": all_signals
        }

    def export_results(self, backtest_result: Dict[str, Any]) -> Tuple[Path, Path]:
        """
        Export backtest results to CSV and a comprehensive Markdown report.
        """
        run_id = backtest_result["run_id"]
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Export Trades CSV
        trades_csv_path = settings.reports_dir / f"backtest_trades_{run_id}_{ts_str}.csv"
        trades_data = []
        for t in backtest_result["trades"]:
            trades_data.append({
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_date": str(t.entry_date)[:10],
                "entry_price": t.entry_price,
                "exit_date": str(t.exit_date)[:10],
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
                "quantity": t.quantity,
                "gross_pnl": t.gross_pnl,
                "net_pnl": t.net_pnl,
                "return_pct": t.return_pct,
                "commission_paid": t.commission_paid,
                "tax_paid": t.tax_paid,
                "slippage_cost": t.slippage_cost,
                "holding_bars": t.holding_bars
            })
        pd.DataFrame(trades_data).to_csv(trades_csv_path, index=False, encoding="utf-8-sig")

        # 2. Export Markdown Report
        md_path = settings.reports_dir / f"backtest_report_{run_id}_{ts_str}.md"
        m = backtest_result["portfolio_metrics"]
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# BÁO CÁO NGHIÊN CỨU & KIỂM CHỨNG CHIẾN LƯỢC JOHN LUCAS PRUNI\n\n")
            f.write(f"- **Mã đợt chạy (Run ID)**: `{run_id}`\n")
            f.write(f"- **Phương pháp**: Price Action 2 Cấu trúc & 3 Cây nến (John Lucas Pruni)\n")
            f.write(f"- **Danh mục cổ phiếu**: {', '.join(backtest_result['symbols'])}\n")
            f.write(f"- **Vốn ban đầu**: {self.initial_capital:,.0f} VND\n")
            f.write(f"- **Chế độ giao dịch**: {'Long-Only (Cổ phiếu giao ngay VN)' if self.long_only else 'Bidirectional'}\n\n")

            f.write("## 1. Kết quả kiểm chứng nhận định Tỷ lệ thắng 30%\n\n")
            f.write(f"| Chỉ số hiệu suất | Giá trị thực nghiệm | Ghi chú lý thuyết |\n")
            f.write(f"| :--- | :--- | :--- |\n")
            f.write(f"| **Tỷ lệ thắng (Win Rate)** | **{m['win_rate_pct']}%** | Video đề cập ~30% |\n")
            f.write(f"| Số giao dịch thắng (Win) | {m['win_count']} | Lợi nhuận TB: {m['avg_win']:,.2f} VND |\n")
            f.write(f"| Số giao dịch thua (Loss) | {m['loss_count']} | Thua lỗ TB: {m['avg_loss']:,.2f} VND |\n")
            f.write(f"| Tỷ lệ Thắng/Thua (Win/Loss Ratio) | **{m['win_loss_pnl_ratio']}** | Cần > 2.33 để hòa vốn nếu Winrate 30% |\n")
            f.write(f"| **Hệ số lợi nhuận (Profit Factor)** | **{m['profit_factor']}** | Gross Profit / Gross Loss |\n")
            f.write(f"| **Kỳ vọng lợi nhuận (EV / Trade)** | **{m['expected_value_per_trade']:,.2f} VND** | Lợi nhuận kỳ vọng trên mỗi lệnh |\n")
            f.write(f"| **Lợi nhuận ròng (Net PnL)** | **{m['net_pnl']:,.2f} VND** | Sau thuế & phí giao dịch |\n")
            f.write(f"| Tổng phí giao dịch & thuế | {m['total_fees_and_taxes']:,.2f} VND | Phí 0.15% + Thuế bán 0.1% + Trượt giá |\n")
            f.write(f"| Tỷ suất sinh lời (ROI) | {m['roi_pct']}% | Trên tổng vốn ban đầu |\n")
            f.write(f"| Mức sụt giảm tối đa (Max Drawdown) | {m['max_drawdown_pct']}% | {m['max_drawdown_amount']:,.2f} VND |\n")
            f.write(f"| Chuỗi thua dài nhất | {m['max_consecutive_losses']} lệnh | Rủi ro tâm lý cần kiểm soát |\n")
            f.write(f"| **Đánh giá tổng quan (Verdict)** | **{m['evaluation_verdict']}** | Khả thi với tỷ lệ 30%: {m['win_rate_30pct_viable']} |\n\n")

            f.write("## 2. Chi tiết kết quả theo từng mã cổ phiếu\n\n")
            f.write("| Mã | Số lệnh | Thắng | Thua | Win Rate | Net PnL (VND) | Profit Factor | Max DD (%) |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for sym, sm in backtest_result["per_symbol_metrics"].items():
                f.write(f"| {sym} | {sm['total_trades']} | {sm['win_count']} | {sm['loss_count']} | {sm['win_rate_pct']}% | {sm['net_pnl']:,.2f} | {sm['profit_factor']} | {sm['max_drawdown_pct']}% |\n")

            f.write("\n## 3. Nhật ký 15 giao dịch gần nhất\n\n")
            if backtest_result["trades"]:
                f.write("| Mã | Ngày vào | Giá vào | Ngày ra | Giá ra | Lý do đóng | Lợi nhuận ròng (VND) | Tỷ suất |\n")
                f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
                for tr in backtest_result["trades"][-15:]:
                    f.write(f"| {tr.symbol} | {str(tr.entry_date)[:10]} | {tr.entry_price:,.0f} | {str(tr.exit_date)[:10]} | {tr.exit_price:,.0f} | {tr.exit_reason} | {tr.net_pnl:,.2f} | {tr.return_pct:.2f}% |\n")
            else:
                f.write("Không có giao dịch nào được khớp trong khoảng thời gian kiểm thử.\n")

        logger.info(f"Exported backtest reports:\n  - CSV: {trades_csv_path}\n  - Markdown: {md_path}")
        return trades_csv_path, md_path
