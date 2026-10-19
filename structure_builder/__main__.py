"""
CLI Entry Point for Layer 2: Market Structure Builder.
Usage:
    python -m structure_builder --swings swings.csv [--last 20] [--all] [--verbose]
"""

import sys
import argparse
from pathlib import Path

# UTF-8 encoding support for console output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from structure_builder.builder import MarketStructureBuilder
from common.table_formatter import format_swings_table, format_structures_table


def main():
    parser = argparse.ArgumentParser(
        description="Layer 2 — Market Structure Builder (Standalone Swings Runner)"
    )
    parser.add_argument(
        "--swings",
        "-s",
        type=str,
        required=True,
        help="Đường dẫn tới file lưu danh sách swings (CSV hoặc JSON)"
    )
    parser.add_argument(
        "--last",
        "-n",
        type=int,
        default=20,
        help="Số lượng bản ghi gần nhất hiển thị trên bảng (mặc định 20)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Hiển thị toàn bộ lịch sử thay vì cắt N dòng cuối"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Hiển thị chi tiết trạng thái, lý do phân loại, rule_version"
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="Thời điểm kiểm thử (chỉ dùng swings có confirmed_at <= as-of)"
    )

    args = parser.parse_args()

    file_path = Path(args.swings)
    if not file_path.exists():
        print(f"Lỗi: File {file_path} không tồn tại.", file=sys.stderr)
        sys.exit(1)

    builder = MarketStructureBuilder()
    swings, structures = builder.build_from_file(file_path, as_of_time=args.as_of)

    print("\n" + "=" * 120)
    print("      BẢNG 1 — DANH SÁCH ĐỈNH / ĐÁY SWING (LAYER 1 + NHÃN BƯỚC A)")
    print("=" * 120)
    print(format_swings_table(swings, limit=args.last, show_all=args.all))

    print("\n" + "=" * 120)
    print("      BẢNG 2 — CẤU TRÚC THỊ TRƯỜNG THEO QUY TẮC NHÁP (DRAFT BRUNI RULES)")
    print("=" * 120)
    print(format_structures_table(structures, limit=args.last, show_all=args.all, verbose=args.verbose))
    print("=" * 120 + "\n")


if __name__ == "__main__":
    main()
