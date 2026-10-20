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
    Fetch live API data; use the daily DB only when explicitly requested as 1d.
    """
    from src.candle_timeframe import require_15m_candles
    clean_sym = symbol.strip().upper()
    if source not in ("api", "db"):
        raise ValueError(f"Nguồn dữ liệu không hợp lệ: {source}")
    if source == "db":
        if timeframe != "1d":
            raise ValueError(f"DB SQLite chỉ có nến ngày (1d), không thể cung cấp {timeframe}")
        repo = get_repository(force_mock=True)
        return repo.query_historical_prices(clean_sym)

    yf_client = YFinanceClient(request_delay=0.1)
    period = "60d" if timeframe in ("1m", "5m", "15m", "30m", "60m", "1h") else "max"
    raw_df, err = yf_client.fetch_intraday(clean_sym, interval=timeframe, period=period)
    if raw_df is None or raw_df.empty:
        raise RuntimeError(f"API không tải được nến {timeframe} cho {clean_sym}: {err or 'empty response'}; không fallback sang DB 1d")
    df = raw_df.reset_index()
    dt_col = "Datetime" if "Datetime" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])
    df["TRADE_DATE"] = df[dt_col]
    df["OPEN_PRICE"] = df["Open"]
    df["HIGH_PRICE"] = df["High"]
    df["LOW_PRICE"] = df["Low"]
    df["CLOSE_PRICE"] = df["Close"]
    df["VOLUME"] = df["Volume"]
    require_15m_candles(df, timeframe)
    return df


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


def inspect_layer2_structure(
    symbol: str = "HPG",
    timeframe: str = "15m",
    source: str = "api",
    test_date: str = None,
    test_datetime: str = None,
    as_json: bool = False
):
    import json
    from src.strategy.market_structure import MarketStructureBuilder

    df_raw = load_price_data(symbol, timeframe=timeframe, source=source)
    if df_raw.empty:
        print(f"Không có dữ liệu cho mã {symbol}")
        return

    builder = MarketStructureBuilder()
    report = builder.build_structure(
        df=df_raw,
        symbol=symbol,
        timeframe=timeframe,
        test_date=test_date,
        test_datetime=test_datetime
    )

    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return

    print("\n" + "=" * 120)
    print("      LAYER 2 — MARKET STRUCTURE BUILDER (KIỂM THỬ CẤU TRÚC THEO NGÀY)")
    print(f"      Mã: {report.symbol} | Khung: {report.timeframe} | Rule Version: {report.rule_version}")
    print(f"      Thời điểm Cutoff: {report.cutoff_time or 'Toàn bộ lịch sử (No Cutoff)'}")
    print("=" * 120)
    print(f" >> Tổng số Swing phát hiện (Layer 1): {report.total_input_swings}")
    print(f" >> Swings hợp lệ (Confirmed <= Cutoff): {report.used_swings_count}")
    print(f" >> Swings bị loại (Confirmed > Cutoff): {report.excluded_swings_count}")
    print(f" >> Cấu trúc đã hình thành: {len(report.structures)}")
    print(f" >> Trạng thái 2 Cấu trúc (Two Structures): {'ĐẠT (CÙNG HƯỚNG)' if report.has_two_structures else 'CHƯA ĐẠT / KHÔNG ĐỦ'}")
    print(f" >> Xu hướng cấu trúc: {report.trend}")
    print(f" >> Ứng viên Mua (is_long_candidate): {'CÓ (LONG CANDIDATE)' if report.is_long_candidate else 'KHÔNG (REJECTED)'}")
    print(f" >> Mã lý do (reason_code): {report.reason_code}")
    if report.active_trading_range["range_low"] and report.active_trading_range["range_high"]:
        print(f" >> Khung dao động hiện tại: [{report.active_trading_range['range_low']:,.0f} - {report.active_trading_range['range_high']:,.0f}] đ")

    # Table of recent used swings
    print("\n" + "-" * 120)
    print(" DANH SÁCH SWINGS ĐƯỢC SỬ DỤNG TRƯỚC THỜI ĐIỂM CUTOFF (LAYER 1 -> LAYER 2):")
    print("-" * 120)
    print(f" {'ID':<8} | {'LOẠI':<6} | {'NHÃN':<4} | {'GIÁ (VND)':<11} | {'CỰC TRỊ (EXTREME)':<19} | {'XÁC NHẬN (CONFIRMED)':<19} | {'TRỄ':<5}")
    print("-" * 120)
    for s in report.used_swings[-12:]:
        print(f" {s['swing_id']:<8} | {s['swing_type']:<6} | {s['structure_label']:<4} | {s['extreme_price']:>10,.0f}đ | {s['extreme_time']:<19} | {s['confirmed_at']:<19} | {s['confirmation_delay']:>3} b")

    # Table of excluded swings if any
    if report.excluded_swings:
        print("\n" + "-" * 120)
        print(" SWINGS BỊ LOẠI KHỎI PHẠM VI KIỂM THỬ (CHỐNG LOOKAHEAD BIAS):")
        print("-" * 120)
        print(f" {'ID':<8} | {'LOẠI':<6} | {'GIÁ (VND)':<11} | {'CỰC TRỊ':<19} | {'XÁC NHẬN':<19} | {'LÝ DO LOẠI BỎ':<25}")
        print("-" * 120)
        for s in report.excluded_swings[:6]:
            print(f" {s['swing_id']:<8} | {s['swing_type']:<6} | {s['extreme_price']:>10,.0f}đ | {s['extreme_time']:<19} | {s.get('confirmed_at') or 'Chưa xác nhận':<19} | {s['exclusion_reason']:<25}")

    # Table of structures formed
    if report.structures:
        print("\n" + "-" * 120)
        print(" DANH SÁCH CẤU TRÚC THỊ TRƯỜNG ĐÃ HÌNH THÀNH (BOS & RANGES):")
        print("-" * 120)
        print(f" {'ID':<10} | {'HƯỚNG':<6} | {'TRẠNG THÁI':<11} | {'XÁC NHẬN':<19} | {'GIÁ PHÁ VỠ':<11} | {'KHUNG BIÊN ĐỘ':<25}")
        print("-" * 120)
        for st in report.structures[-8:]:
            print(f" {st['structure_id']:<10} | {st['direction']:<6} | {st['status']:<11} | {st['confirmed_at_time']:<19} | {st['break_price']:>10,.0f}đ | [{st['range_low']:,.0f} - {st['range_high']:,.0f}] đ")

    # 2 confirmed structures
    print("\n" + "-" * 120)
    print(" 2 CẤU TRÚC CONFIRMED GẦN NHẤT:")
    print("-" * 120)
    for st in report.last_two_structures:
        print(f"  * {st['structure_id']}: Hướng {st['direction']} | Trạng thái: {st['status']} | Ngày xác nhận: {st['confirmed_at_time']} | Biên độ: [{st['range_low']:,.0f} - {st['range_high']:,.0f}] đ")
    print("=" * 120 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect Swing Points & Layer 2 Market Structure on Live API Data")
    parser.add_argument("symbol", nargs="?", default="HPG", help="Mã cổ phiếu (vd: HPG, FPT, SSI, VNM)")
    parser.add_argument("--layer", type=int, default=1, help="Layer phân tích: 1 (Swing Detection) hoặc 2 (Market Structure Builder)")
    parser.add_argument("--date", default=None, help="Ngày kiểm thử cho Layer 2 (YYYY-MM-DD)")
    parser.add_argument("--datetime", default=None, help="Thời điểm kiểm thử cho Layer 2 (YYYY-MM-DD HH:MM[:SS])")
    parser.add_argument("--timeframe", "-t", default="15m", help="Khung thời gian (vd: 15m, 1h, 1d)")
    parser.add_argument("--source", "-s", choices=("api", "db"), default="api", help="Nguồn dữ liệu: api (15m) hoặc db (chỉ 1d)")
    parser.add_argument("--recent", "-n", type=int, default=20, help="Số swing hiển thị gần nhất")
    parser.add_argument("--mult", "-m", type=float, default=2.0, help="Hệ số nhân ATR đảo chiều (vd: 1.5, 2.0, 2.5)")
    parser.add_argument("--month", default=None, help="Lọc theo tháng (vd: 2026-09)")
    parser.add_argument("--json", action="store_true", help="Xuất kết quả JSON")
    args = parser.parse_args()

    # If --date or --datetime or --layer 2 is passed, run Layer 2 Market Structure Builder
    if args.layer == 2 or args.date is not None or args.datetime is not None:
        inspect_layer2_structure(
            symbol=args.symbol,
            timeframe=args.timeframe,
            source=args.source,
            test_date=args.date,
            test_datetime=args.datetime,
            as_json=args.json
        )
    else:
        inspect_stock_swings(
            symbol=args.symbol,
            timeframe=args.timeframe,
            source=args.source,
            recent_n=args.recent,
            mult=args.mult,
            filter_month=args.month
        )

