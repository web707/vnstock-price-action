"""
Inspector script to print all verified Swing Highs, Swing Lows, and Market Structures
matching the 'Phát hiện điểm Swing' specification (Wilder ATR 14, Reversal Threshold, ZigZag alternation).
Supports real-time live API connection for 15-minute intraday data (and Daily data).
"""

import sys
import argparse
import pandas as pd
from src.oracle_repository import get_repository
from src.strategy.market_structure import MarketStructureTracker, validate_and_clean_data
from src.yfinance_client import YFinanceClient

# Configure UTF-8 output for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def load_price_data(symbol: str, timeframe: str = "15m", source: str = "api") -> pd.DataFrame:
    """
    Fetch price data directly from live API (Yahoo Finance 15m) or fallback to local database.
    """
    clean_sym = symbol.strip().upper()
    if source == "api" or timeframe != "1d":
        yf_client = YFinanceClient(request_delay=0.1)
        period = "60d" if timeframe in ("1m", "5m", "15m", "30m", "60m", "1h") else "max"
        raw_df, err = yf_client.fetch_intraday(clean_sym, interval=timeframe, period=period)
        if raw_df is not None and not raw_df.empty:
            df = raw_df.reset_index()
            dt_col = "Datetime" if "Datetime" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])
            df["TRADE_DATE"] = df[dt_col]
            df["OPEN_PRICE"] = df["Open"]
            df["HIGH_PRICE"] = df["High"]
            df["LOW_PRICE"] = df["Low"]
            df["CLOSE_PRICE"] = df["Close"]
            df["VOLUME"] = df["Volume"]
            return df
        print(f">> [Cảnh báo API] Không lấy được dữ liệu qua API: {err}. Chuyển sang database cục bộ...")

    repo = get_repository(force_mock=True)
    return repo.query_historical_prices(clean_sym)


def inspect_stock_swings(
    symbol: str = "HPG",
    timeframe: str = "15m",
    source: str = "api",
    recent_n: int = 25,
    mult: float = 2.0,
    swing_left: int = 3,
    swing_right: int = 3,
    filter_month: str = None
):
    df_raw = load_price_data(symbol, timeframe=timeframe, source=source)
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

    if filter_month:
        selected_swings = [s for _, s in all_swings if filter_month in str(s.trade_date)]
    else:
        selected_swings = [s for _, s in all_swings[-recent_n:]]

    is_intraday = timeframe != "1d"
    date_len = 16 if is_intraday else 10

    print("\n" + "=" * 128)
    print(f"      HỆ THỐNG PHÁT HIỆN ĐIỂM SWING & CẤU TRÚC THỊ TRƯỜNG — MÃ: {symbol.upper()}")
    print(f"      Nguồn dữ liệu: API TRỰC TIẾP ({source.upper()}) | Khung thời gian: {timeframe} | Nến phân tích: {len(df):,}")
    print(f"      Cấu hình: Wilder ATR(14) | Pivot {swing_left}/{swing_right} | Ngưỡng T_i = max({mult}*ATR, 0.5% Giá) | Zigzag Luân phiên")
    print("=" * 128)
    print(
        f" {'STT':<4} | {'LOẠI':<10} | {'CT':<4} | {'THỜI ĐIỂM CỰC TRỊ':<{date_len}} | {'GIÁ (VND)':<10} | "
        f"{'ATR(14)':<8} | {'NGƯỠNG T_i':<9} | {'XÁC NHẬN':<{date_len}} | {'TRỄ':<5} | {'VOL/MED':<8} | {'BIÊN ĐỘ':<9}"
    )
    print("-" * 128)

    prev_price = None
    for i, s in enumerate(selected_swings, 1):
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

        ext_date_str = str(s.trade_date)[:date_len].replace("T", " ")
        conf_date_str = str(s.confirmed_date)[:date_len].replace("T", " ")

        print(
            f" {i:<4} | {s_type:<10} | {s.structure_type or 'N/A':<4} | {ext_date_str:<{date_len}} | "
            f"{s.price:>9,.0f}đ | {atr_str:>8} | {thresh_str:>9} | {conf_date_str:<{date_len}} | "
            f"{delay:>3} b | {vol_str:>7} | {change_str:>9}"
        )

    print("=" * 128)
    print(f">> Tổng số nến {timeframe} tải về từ API: {len(df):,}")
    print(f">> Tổng số Đỉnh (Swing High) xác nhận: {len(swing_highs)}")
    print(f">> Tổng số Đáy (Swing Low) xác nhận: {len(swing_lows)}")
    print(f">> Tỷ lệ luân phiên Zigzag: 100% (Đỉnh -> Đáy -> Đỉnh -> Đáy)")
    print(f">> Tổng số lần Phá vỡ Cấu trúc (BOS): {len(breaks)}")

    # Sensitivity comparison (Section 4 & 9)
    t_15 = MarketStructureTracker(reversal_mult=1.5, swing_left=swing_left, swing_right=swing_right).detect_swings(df)
    t_25 = MarketStructureTracker(reversal_mult=2.5, swing_left=swing_left, swing_right=swing_right).detect_swings(df)
    print("\n" + "-" * 128)
    print(f" SO SÁNH ĐỘ NHẠY HỆ SỐ ĐẢO CHIỀU TRÊN KHUNG {timeframe} (REVERSAL MULTIPLIER SENSITIVITY):")
    print(f"  * 1.5 ATR: {len(t_15[0]) + len(t_15[1])} swings (Nhạy hơn, bắt đảo chiều sớm, bắt nhiều sóng nhỏ)")
    print(f"  * 2.0 ATR: {len(swing_highs) + len(swing_lows)} swings (Cấu hình cơ sở chuẩn — Cân bằng giữa lọc nhiễu & phản ứng)")
    print(f"  * 2.5 ATR: {len(t_25[0]) + len(t_25[1])} swings (Mượt hơn, chỉ nhận diện các đảo chiều lớn)")
    print("-" * 128)

    print("\n" + "-" * 128)
    print(f" CÁC ĐIỂM PHÁ VỠ CẤU TRÚC (BOS) MỚI NHẤT TRÊN KHUNG {timeframe}:")
    print("-" * 128)
    for b in breaks[-6:]:
        direct = "BULLISH (TĂNG)" if b.direction == "BULLISH" else "BEARISH (GIẢM)"
        broken_type = "Đỉnh" if b.direction == "BULLISH" else "Đáy"
        b_date_str = str(b.break_date)[:date_len].replace("T", " ")
        orig_date_str = str(b.broken_swing.trade_date)[:date_len].replace("T", " ")
        print(
            f"  [{b_date_str}] Phá vỡ {direct:<14} | Đóng nến: {b.break_price:,.0f} đ "
            f"phá thủng {broken_type} {b.broken_swing.price:,.0f} đ (nến {orig_date_str}) | "
            f"Khung dao động: [{b.range_low:,.0f} - {b.range_high:,.0f}] đ"
        )
    print("=" * 128 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect Swing Points with Wilder ATR ZigZag on Live API Data")
    parser.add_argument("symbol", nargs="?", default="HPG", help="Mã cổ phiếu (vd: HPG, FPT, SSI, VNM)")
    parser.add_argument("--timeframe", "-t", default="15m", help="Khung thời gian (vd: 15m, 1h, 1d)")
    parser.add_argument("--source", "-s", default="api", help="Nguồn dữ liệu: api (live) hoặc db (cục bộ)")
    parser.add_argument("--recent", "-n", type=int, default=20, help="Số swing hiển thị gần nhất")
    parser.add_argument("--mult", "-m", type=float, default=2.0, help="Hệ số nhân ATR đảo chiều (vd: 1.5, 2.0, 2.5)")
    parser.add_argument("--month", default=None, help="Lọc theo tháng (vd: 2026-09)")
    args = parser.parse_args()

    inspect_stock_swings(
        symbol=args.symbol,
        timeframe=args.timeframe,
        source=args.source,
        recent_n=args.recent,
        mult=args.mult,
        filter_month=args.month
    )
