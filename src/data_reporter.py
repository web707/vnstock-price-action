"""
Data Coverage & Quality Reporter Module.
Generates comprehensive coverage and quality audit reports in CSV, Markdown,
and formatted console outputs.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from src.config import settings
from src.import_logger import logger


class DataReporter:
    """Compiles statistics and exports coverage & quality reports."""

    def __init__(self, batch_id: str):
        self.batch_id = batch_id
        self.symbol_stats: List[Dict[str, Any]] = []
        self.start_time = datetime.now(timezone.utc)
        self.end_time: Optional[datetime] = None

    def record_symbol_result(
        self,
        symbol: str,
        yahoo_ticker: str,
        exchange: str,
        status: str,  # SUCCESS, NO_DATA, FAILED, PARTIAL
        records_fetched: int,
        records_valid: int,
        records_rejected: int,
        earliest_date: Optional[str] = None,
        latest_date: Optional[str] = None,
        error_message: Optional[str] = None,
        warnings_count: int = 0
    ) -> None:
        """Record the audit metrics for an individual symbol run."""
        self.symbol_stats.append({
            "symbol": symbol,
            "yahoo_ticker": yahoo_ticker,
            "exchange": exchange,
            "status": status,
            "records_fetched": records_fetched,
            "records_valid": records_valid,
            "records_rejected": records_rejected,
            "warnings_count": warnings_count,
            "earliest_date": str(earliest_date) if earliest_date else "N/A",
            "latest_date": str(latest_date) if latest_date else "N/A",
            "error_message": error_message or ""
        })

    def generate_summary(self) -> Dict[str, Any]:
        """Aggregate all metrics into an executive summary."""
        self.end_time = datetime.now(timezone.utc)
        total_symbols = len(self.symbol_stats)

        successful_symbols = sum(1 for s in self.symbol_stats if s["status"] == "SUCCESS")
        no_data_symbols = sum(1 for s in self.symbol_stats if s["status"] == "NO_DATA")
        failed_symbols = sum(1 for s in self.symbol_stats if s["status"] == "FAILED")
        partial_symbols = sum(1 for s in self.symbol_stats if s["status"] == "PARTIAL")

        supported_by_yf = successful_symbols + partial_symbols
        coverage_pct = (supported_by_yf / total_symbols * 100.0) if total_symbols > 0 else 0.0

        total_fetched = sum(s["records_fetched"] for s in self.symbol_stats)
        total_valid = sum(s["records_valid"] for s in self.symbol_stats)
        total_rejected = sum(s["records_rejected"] for s in self.symbol_stats)
        total_warnings = sum(s["warnings_count"] for s in self.symbol_stats)

        duration_sec = (self.end_time - self.start_time).total_seconds()

        return {
            "batch_id": self.batch_id,
            "start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "end_time": self.end_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "duration_seconds": round(duration_sec, 2),
            "total_input_symbols": total_symbols,
            "successful_symbols": successful_symbols,
            "partial_symbols": partial_symbols,
            "no_data_symbols": no_data_symbols,
            "failed_symbols": failed_symbols,
            "symbols_needing_retry": failed_symbols,
            "supported_by_yfinance": supported_by_yf,
            "market_coverage_rate_pct": round(coverage_pct, 2),
            "total_records_fetched": total_fetched,
            "total_records_valid": total_valid,
            "total_records_rejected": total_rejected,
            "total_warnings": total_warnings
        }

    def export_reports(self) -> Tuple[Path, Path]:
        """
        Export detailed CSV and summary Markdown reports to data/reports/.
        Returns (csv_path, markdown_path).
        """
        summary = self.generate_summary()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Export detailed CSV
        csv_path = settings.reports_dir / f"coverage_details_{self.batch_id}_{timestamp_str}.csv"
        df = pd.DataFrame(self.symbol_stats)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        # 2. Export summary Markdown
        md_path = settings.reports_dir / f"coverage_summary_{self.batch_id}_{timestamp_str}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# BÁO CÁO ĐỘ BAO PHỦ VÀ CHẤT LƯỢNG DỮ LIỆU CHỨNG KHOÁN\n\n")
            f.write(f"- **Mã đợt chạy (Batch ID)**: `{summary['batch_id']}`\n")
            f.write(f"- **Thời gian bắt đầu**: {summary['start_time']}\n")
            f.write(f"- **Thời gian kết thúc**: {summary['end_time']}\n")
            f.write(f"- **Tổng thời gian chạy**: {summary['duration_seconds']} giây\n\n")

            f.write("## 1. Tổng quan độ bao phủ thị trường\n\n")
            f.write(f"| Chỉ số | Giá trị |\n")
            f.write(f"| :--- | :--- |\n")
            f.write(f"| Tổng số mã đầu vào | {summary['total_input_symbols']} |\n")
            f.write(f"| Số mã có dữ liệu trên Yahoo Finance | {summary['supported_by_yfinance']} |\n")
            f.write(f"| Số mã tải thành công 100% | {summary['successful_symbols']} |\n")
            f.write(f"| Số mã có dữ liệu một phần | {summary['partial_symbols']} |\n")
            f.write(f"| Số mã không có dữ liệu (404/Delisted) | {summary['no_data_symbols']} |\n")
            f.write(f"| Số mã lỗi kết nối / cần thử lại | {summary['symbols_needing_retry']} |\n")
            f.write(f"| **Tỷ lệ bao phủ khả dụng** | **{summary['market_coverage_rate_pct']}%** |\n\n")

            f.write("## 2. Thống kê chất lượng bản ghi OHLCV\n\n")
            f.write(f"| Chỉ số bản ghi | Số lượng |\n")
            f.write(f"| :--- | :--- |\n")
            f.write(f"| Tổng bản ghi tải về | {summary['total_records_fetched']} |\n")
            f.write(f"| Bản ghi hợp lệ lưu Database | {summary['total_records_valid']} |\n")
            f.write(f"| Bản ghi bị loại do sai lệch | {summary['total_records_rejected']} |\n")
            f.write(f"| Cảnh báo chất lượng (Volume 0 / Biến động mạnh) | {summary['total_warnings']} |\n\n")

            f.write("## 3. Danh sách các mã gặp lỗi hoặc không có dữ liệu\n\n")
            abnormal_symbols = [s for s in self.symbol_stats if s["status"] != "SUCCESS"]
            if abnormal_symbols:
                f.write("| Mã | Ticker Yahoo | Sàn | Trạng thái | Chi tiết nguyên nhân |\n")
                f.write("| :--- | :--- | :--- | :--- | :--- |\n")
                for s in abnormal_symbols[:50]:  # Limit top 50 in summary
                    f.write(f"| {s['symbol']} | {s['yahoo_ticker']} | {s['exchange']} | {s['status']} | {s['error_message']} |\n")
                if len(abnormal_symbols) > 50:
                    f.write(f"\n*(Còn {len(abnormal_symbols) - 50} mã khác được ghi đầy đủ trong file CSV)*\n")
            else:
                f.write("Tất cả các mã được tải đều thành công 100% không có lỗi.\n")

        logger.info(f"Generated coverage reports:\n  - CSV: {csv_path}\n  - Markdown: {md_path}")
        return csv_path, md_path

    def print_terminal_summary(self) -> None:
        """Print an eye-friendly table to the terminal."""
        s = self.generate_summary()
        banner = "=" * 65
        print("\n" + banner)
        print("          BÁO CÁO ĐỘ BAO PHỦ DỮ LIỆU CHỨNG KHOÁN VIỆT NAM")
        print(banner)
        print(f" Mã đợt chạy (Batch ID)       : {s['batch_id']}")
        print(f" Thời gian thực thi           : {s['duration_seconds']}s")
        print(f" Tổng số mã kiểm tra          : {s['total_input_symbols']}")
        print(f" Số mã tải hoàn hảo (100%)    : {s['successful_symbols']}")
        print(f" Số mã tải có bản ghi lọc bỏ  : {s['partial_symbols']}")
        print(f" Số mã không có dữ liệu (404) : {s['no_data_symbols']}")
        print(f" Số mã lỗi / cần thử lại      : {s['failed_symbols']}")
        print(f" Tỷ lệ bao phủ khả dụng       : {s['market_coverage_rate_pct']}%")
        print("-" * 65)
        print(f" Tổng bản ghi tải về          : {s['total_records_fetched']:,}")
        print(f" Bản ghi hợp lệ               : {s['total_records_valid']:,}")
        print(f" Bản ghi bị loại do lỗi       : {s['total_records_rejected']:,}")
        print(f" Cảnh báo chất lượng          : {s['total_warnings']:,}")
        print(banner + "\n")
