"""
Table Formatting Utilities for Printing Swings (Table 1) and Market Structures (Table 2).
Strictly matches output specifications in Section 3.
"""

from typing import List, Optional
from common.models import Swing, MarketStructure


def find_repeating_cycle(labels: List[str]) -> str:
    """
    If labels sequence repeats a shorter cycle completely (e.g. ['LH', 'LL', 'LH', 'LL']),
    return that cycle joined by ' + ' (e.g. 'LH + LL').
    Otherwise, return all labels joined by ' + '.
    """
    if not labels:
        return "N/A"

    n = len(labels)
    for k in range(1, n // 2 + 1):
        if n % k == 0:
            cycle = labels[:k]
            if cycle * (n // k) == labels:
                return " + ".join(cycle)

    return " + ".join(labels)


def format_swings_table(
    swings: List[Swing],
    limit: Optional[int] = 20,
    show_all: bool = False
) -> str:
    """
    Table 1 - List of swing highs and lows (11 columns):
    STT | LOẠI | CT | THỜI ĐIỂM CỰC TRỊ | GIÁ (VND) | ATR(14) | NGƯỠNG T_i | XÁC NHẬN | TRỄ | VOL/MED | BIÊN ĐỘ
    """
    display_swings = swings if show_all or limit is None else swings[-limit:]
    if not display_swings:
        return "Không có dữ liệu swing để hiển thị."

    lines = []
    header = (
        f" {'STT':<4} | {'LOẠI':<11} | {'CT':<4} | {'THỜI ĐIỂM CỰC TRỊ':<19} | {'GIÁ (VND)':<11} | "
        f"{'ATR(14)':<8} | {'NGƯỠNG T_i':<10} | {'XÁC NHẬN':<19} | {'TRỄ':<5} | {'VOL/MED':<8} | {'BIÊN ĐỘ':<9}"
    )
    divider = "-" * len(header)
    lines.append(divider)
    lines.append(header)
    lines.append(divider)

    for s in display_swings:
        stt = s.swing_id
        s_type = "ĐỈNH (HIGH)" if s.swing_type == "HIGH" else "ĐÁY  (LOW) "
        ct = s.structure_label if s.structure_label else ""
        ext_time = str(s.extreme_time)[:19]
        price_str = f"{s.extreme_price:>10,.0f}đ"
        atr_str = f"{s.atr_at_extreme:>6,.0f} đ" if s.atr_at_extreme is not None else "   N/A"
        thresh_str = f"{s.threshold:>8,.0f} đ" if s.threshold is not None else "     N/A"
        conf_time = str(s.confirmed_at)[:19]
        lag_str = f"{s.lag_bars:>3} b"
        vol_str = f"{s.vol_over_median:>5.2f}x" if s.vol_over_median is not None else "  N/A"

        if s.pct_change is not None:
            pct_str = f"{s.pct_change:>+8.2f}%"
        else:
            pct_str = "     N/A"

        lines.append(
            f" {stt:<4} | {s_type:<11} | {ct:<4} | {ext_time:<19} | {price_str} | "
            f"{atr_str} | {thresh_str} | {conf_time:<19} | {lag_str} | {vol_str} | {pct_str}"
        )

    lines.append(divider)
    return "\n".join(lines)


def format_structures_table(
    structures: List[MarketStructure],
    limit: Optional[int] = 20,
    show_all: bool = False,
    verbose: bool = False
) -> str:
    """
    Table 2 - Market Structures (5 standard columns, optional extra columns with verbose):
    ID | Swing bắt đầu | Swing kết thúc | Phân loại | Bằng chứng chính
    """
    display_structs = structures if show_all or limit is None else structures[-limit:]
    if not display_structs:
        return "Chưa có cấu trúc nào được hình thành."

    lines = []
    if verbose:
        header = (
            f" {'ID':<6} | {'Bắt đầu':<9} | {'Kết thúc':<9} | {'Phân loại':<10} | {'Trạng thái':<10} | "
            f"{'Mã lý do':<24} | {'Xác nhận':<19} | {'Rule Ver':<28} | {'Bằng chứng chính'}"
        )
    else:
        header = f" {'ID':<6} | {'Swing bắt đầu':<14} | {'Swing kết thúc':<15} | {'Phân loại':<10} | {'Bằng chứng chính'}"

    divider = "-" * max(len(header), 85)
    lines.append(divider)
    lines.append(header)
    lines.append(divider)

    forming_detected = False
    for st in display_structs:
        if st.status == "FORMING":
            forming_detected = True

        evidence = st.main_evidence or find_repeating_cycle(st.labels_sequence)

        if verbose:
            lines.append(
                f" {st.structure_id:<6} | {st.start_swing_id:<9} | {st.end_swing_id:<9} | "
                f"{st.structure_type:<10} | {st.status:<10} | {st.reason_code:<24} | "
                f"{(st.confirmed_at or 'N/A'):<19} | {st.rule_version:<28} | {evidence}"
            )
        else:
            lines.append(
                f" {st.structure_id:<6} | {st.start_swing_id:<14} | {st.end_swing_id:<15} | "
                f"{st.structure_type:<10} | {evidence}"
            )

    lines.append(divider)
    if forming_detected:
        lines.append("(*) Chú thích: Cấu trúc cuối cùng đang ở trạng thái FORMING (đang mở, chưa đóng).")

    return "\n".join(lines)
