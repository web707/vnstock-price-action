"""
Complete Pipeline Runner: Layer 1 (Detect Swings) -> Save File -> Layer 2 (Build Structure) -> Print Tables.
Demonstrates clean decoupling of modules.
"""

import sys
import argparse
from pathlib import Path
import pandas as pd

# UTF-8 console output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from swing_detector import detect_swings, SwingDetectorConfig, save_swings
from structure_builder import MarketStructureBuilder
from common.table_formatter import format_swings_table, format_structures_table


def load_candles(symbol: str, csv_path: str = None, timeframe: str = "15m") -> pd.DataFrame:
    """Load candles from local CSV if provided, else fetch from Yahoo Finance API."""
    if csv_path:
        p = Path(csv_path)
        if not p.exists():
            raise FileNotFoundError(f"Không tìm thấy file nến tại: {csv_path}")
        df = pd.read_csv(p)
        return df

    from src.yfinance_client import YFinanceClient
    # Fetch live 15m from Yahoo Finance
    yf_client = YFinanceClient(request_delay=0.1)
    period = "60d" if timeframe in ("1m", "5m", "15m", "30m", "60m", "1h") else "max"
    raw_df, err = yf_client.fetch_intraday(symbol.strip().upper(), interval=timeframe, period=period)
    if raw_df is None or raw_df.empty:
        raise RuntimeError(f"Không tải được dữ liệu nến cho {symbol} qua API: {err}")
    return raw_df.reset_index()


def main():
    parser = argparse.ArgumentParser(
        description="Run Pipeline: Layer 1 Swing Detection -> Save File -> Layer 2 Market Structure Builder"
    )
    parser.add_argument("--symbol", "-s", type=str, default="HPG", help="Mã cổ phiếu (vd: HPG, SSI, VNM)")
    parser.add_argument("--csv", type=str, default="data/hpg_15m_sample.csv", help="Đường dẫn file nến 15m (mặc định data/hpg_15m_sample.csv)")
    parser.add_argument("--output-swings", "-o", type=str, default="data/swings_output.csv", help="Đường dẫn lưu file swings kết quả")
    parser.add_argument("--last", "-n", type=int, default=20, help="Số lượng bản ghi gần nhất hiển thị trên bảng")
    parser.add_argument("--all", action="store_true", help="Hiển thị toàn bộ lịch sử thay vì cắt N dòng cuối")
    parser.add_argument("--verbose", "-v", action="store_true", help="Hiển thị chi tiết trạng thái, lý do phân loại, rule_version")
    parser.add_argument("--as-of", type=str, default=None, help="Thời điểm kiểm thử (chỉ dùng swings confirmed_at <= as-of)")

    args = parser.parse_args()
    sym = args.symbol.upper()

    print("\n" + "=" * 120)
    print(f"      PIPELINE PHÁT HIỆN SWING (LAYER 1) & DỰNG CẤU TRÚC THỊ TRƯỜNG (LAYER 2) — MÃ: {sym}")
    print("=" * 120)

    # 1. Load Candles
    print(f">> [BƯỚC 1] Nạp dữ liệu nến 15m từ: {args.csv or 'Yahoo Finance API'}...")
    df_candles = load_candles(sym, csv_path=args.csv, timeframe="15m")
    print(f">> Đã nạp thành công {len(df_candles):,} cây nến 15 phút.")

    # 2. Run Layer 1: Detect Swings
    print(f">> [BƯỚC 2] Chạy Layer 1 — Phát hiện đỉnh/đáy (Wilder ATR 14, Ngưỡng T_i, ZigZag)...")
    cfg = SwingDetectorConfig(swing_left=3, swing_right=3, reversal_mult=2.0, timeframe="15m")
    detected_swings = detect_swings(df_candles, config=cfg)
    print(f">> Layer 1 phát hiện thành công: {len(detected_swings)} swings (Đỉnh & Đáy luân phiên 100%).")

    # 3. Save Swings to disk
    out_swings_path = Path(args.output_swings)
    print(f">> [BƯỚC 3] Xuất danh sách swings ra file: {out_swings_path}...")
    save_swings(detected_swings, out_swings_path)
    print(f">> File {out_swings_path} đã sẵn sàng cho Layer 2 hoặc các module khác tái sử dụng.")

    # 4. Run Layer 2: Market Structure Builder (Directly from Swings file / memory)
    print(f">> [BƯỚC 4] Chạy Layer 2 — Đọc file swings và dựng cấu trúc (Bước A: Gán nhãn, Bước B: Phân đoạn Bruni)...")
    builder = MarketStructureBuilder(bear_after_up_is_unclear=True)
    labelled_swings, structures = builder.build_from_file(out_swings_path, as_of_time=args.as_of)

    # 5. Print Results
    print("\n" + "=" * 120)
    print("      BẢNG 1 — DANH SÁCH ĐỈNH / ĐÁY SWING (LAYER 1 + NHÃN BƯỚC A)")
    print("=" * 120)
    print(format_swings_table(labelled_swings, limit=args.last, show_all=args.all))

    print("\n" + "=" * 120)
    print("      BẢNG 2 — CẤU TRÚC THỊ TRƯỜNG THEO QUY TẮC NHÁP (DRAFT BRUNI RULES)")
    print("=" * 120)
    print(format_structures_table(structures, limit=args.last, show_all=args.all, verbose=args.verbose))
    print("=" * 120 + "\n")

    # Check last two confirmed
    status_two, two_structs = builder.get_last_two_confirmed(structures)
    if status_two == "OK" and two_structs:
        print(f">> Trạng thái 2 Cấu trúc CONFIRMED liền kề gần nhất: ĐẠT ({two_structs[0].structure_id} -> {two_structs[1].structure_id})")
        print(f"   * {two_structs[0].structure_id}: {two_structs[0].structure_type} ({two_structs[0].main_evidence})")
        print(f"   * {two_structs[1].structure_id}: {two_structs[1].structure_type} ({two_structs[1].main_evidence})")
    else:
        print(f">> Trạng thái 2 Cấu trúc CONFIRMED liền kề gần nhất: {status_two} (Chưa đủ 2 cấu trúc CONFIRMED liền kề)")


if __name__ == "__main__":
    main()
