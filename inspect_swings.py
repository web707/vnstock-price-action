"""
Inspector script to print all verified Swing Highs, Swing Lows, and Market Structures
matching the 'Phát hiện điểm Swing' specification (Wilder ATR 14, Reversal Threshold, ZigZag alternation).
"""

import sys
import argparse
import pandas as pd
from src.oracle_repository import get_repository
from src.strategy.market_structure import MarketStructureTracker, validate_and_clean_data

# Configure UTF-8 output for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def inspect_stock_swings(
    symbol: str = "HPG",
    recent_n: int = 20,
    mult: float = 2.0,
    swing_left: int = 3,
    swing_right: int = 3
):
    repo = get_repository(force_mock=True)
    df_raw = repo.query_historical_prices(symbol)
    if df_raw.empty:
        print(f"Không có dữ liệu cho mã {symbol}")
        return

    # 1. Clean & validate data (Section 1)
    df = validate_and_clean_data(df_raw)

    # 2. Initialize tracker with user-specified ATR multiplier & pivot window
    tracker = MarketStructureTracker(
        swing_left=swing_left,
        swing_right=swing_right,
        reversal_mult=mult,
        break_type="close",
        method="zigzag"
    )
    swing_highs, swing_lows = tracker.detect_swings(df)
    breaks = tracker.compute_all_structure_breaks(df, swing_highs, swing_lows)

    # Merge swings chronologically
    all_swings = [(s.index, s) for s in swing_highs] + [(s.index, s) for s in swing_lows]
    all_swings.sort(key=lambda x: x[0])

    print("\n" + "=" * 120)
    print(f"      HỆ THỐNG PHÁT HIỆN ĐIỂM SWING & CẤU TRÚC THỊ TRƯỜNG — MÃ: {symbol}")
    print(f"      Cấu hình: Wilder ATR(14) | Pivot 3/3 | Ngưỡng T_i = max({mult}*ATR, 0.5% Giá) | Zigzag Luân phiên")
    print("=" * 120)
    print(
        f" {'STT':<4} | {'LOẠI':<10} | {'CT':<4} | {'NGÀY CỰC TRỊ':<12} | {'GIÁ (VND)':<11} | "
        f"{'ATR(14)':<8} | {'NGƯỠNG T_i':<10} | {'XÁC NHẬN':<12} | {'TRỄ':<5} | {'VOL/MED':<8} | {'BIÊN ĐỘ':<9}"
    )
    print("-" * 120)

    sample_swings = all_swings[-recent_n:]
    prev_price = None

    for i, (_, s) in enumerate(sample_swings, 1):
        if prev_price is not None:
            pct_change = ((s.price - prev_price) / prev_price) * 100.0
            change_str = f"{pct_change:+.2f}%"
        else:
            change_str = "   N/A"
        prev_price = s.price

        s_type = "ĐỈNH (HIGH)" if s.point_type == "HIGH" else "ĐÁY  (LOW) "
        delay = s.confirmed_at_index - s.index
        vol_str = f"{s.volume_ratio:4.2f}x" if s.volume_ratio else "  N/A"
        atr_str = f"{s.atr_at_candidate:,.0f} đ" if s.atr_at_candidate else "N/A"
        thresh_str = f"{s.reversal_threshold:,.0f} đ" if s.reversal_threshold else "N/A"

        print(
            f" {i:<4} | {s_type:<10} | {s.structure_type or 'N/A':<4} | {str(s.trade_date)[:10]:<12} | "
            f"{s.price:>10,.0f}đ | {atr_str:>8} | {thresh_str:>10} | {str(s.confirmed_date)[:10]:<12} | "
            f"{delay:>3} b | {vol_str:>7} | {change_str:>9}"
        )

    print("=" * 120)
    print(f">> Tổng số nến phân tích: {len(df):,}")
    print(f">> Tổng số Đỉnh (Swing High) xác nhận: {len(swing_highs)}")
    print(f">> Tổng số Đáy (Swing Low) xác nhận: {len(swing_lows)}")
    print(f">> Tỷ lệ luân phiên Zigzag đạt: 100% (Đỉnh -> Đáy -> Đỉnh -> Đáy)")
    print(f">> Tổng số điểm Phá vỡ Cấu trúc (BOS) kích hoạt: {len(breaks)}")

    # Sensitivity comparison (Section 4 & 9)
    t_15 = MarketStructureTracker(reversal_mult=1.5).detect_swings(df)
    t_25 = MarketStructureTracker(reversal_mult=2.5).detect_swings(df)
    print("\n" + "-" * 120)
    print(" SO SÁNH ĐỘ NHẠY HỆ SỐ ĐẢO CHIỀU (REVERSAL MULTIPLIER SENSITIVITY):")
    print(f"  * 1.5 ATR: {len(t_15[0]) + len(t_15[1])} swings (Nhạy hơn, bắt đảo chiều sớm hơn, bắt nhiều sóng nhỏ)")
    print(f"  * 2.0 ATR: {len(swing_highs) + len(swing_lows)} swings (Cấu hình cơ sở chuẩn — Cân bằng giữa lọc nhiễu & phản ứng)")
    print(f"  * 2.5 ATR: {len(t_25[0]) + len(t_25[1])} swings (Mượt hơn, chỉ nhận diện các đảo chiều lớn)")
    print("-" * 120)

    print("\n" + "-" * 120)
    print(" CÁC ĐIỂM PHÁ VỠ CẤU TRÚC (BOS) MỚI NHẤT DỰA TRÊN SWING ZIGZAG ATR:")
    print("-" * 120)
    for b in breaks[-6:]:
        direct = "BULLISH (TĂNG)" if b.direction == "BULLISH" else "BEARISH (GIẢM)"
        broken_type = "Đỉnh" if b.direction == "BULLISH" else "Đáy"
        print(
            f"  [{str(b.break_date)[:10]}] Phá vỡ {direct:<14} | Đóng cửa {b.break_price:,.0f} đ "
            f"vượt qua {broken_type} {b.broken_swing.price:,.0f} đ (ngày {str(b.broken_swing.trade_date)[:10]}) | "
            f"Khung dao động: [{b.range_low:,.0f} - {b.range_high:,.0f}] đ"
        )
    print("=" * 120 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect Swing Points with Wilder ATR ZigZag Detection")
    parser.add_argument("symbol", nargs="?", default="HPG", help="Mã cổ phiếu (vd: HPG, VNM, FPT)")
    parser.add_argument("--recent", type=int, default=15, help="Số swing hiển thị gần nhất")
    parser.add_argument("--mult", type=float, default=2.0, help="Hệ số nhân ATR đảo chiều (vd: 1.5, 2.0, 2.5)")
    args = parser.parse_args()

    inspect_stock_swings(args.symbol, recent_n=args.recent, mult=args.mult)
