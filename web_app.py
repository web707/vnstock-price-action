"""
Web Application Launcher for Vietnam Stock Price Action Dashboard.
Starts FastAPI Uvicorn server on localhost and opens the web interface.
"""

import sys
import os
from pathlib import Path
import argparse
import webbrowser
import uvicorn
from src.import_logger import logger
from src.web.app import app
import src.web.app as web_module


def main():
    parser = argparse.ArgumentParser(description="VNStock Price Action Web Dashboard")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--mock-db", action="store_true", default=True, help="Force mock SQLite database")
    parser.add_argument("--oracle-db", action="store_true", help="Connect to Oracle Database instead of Mock")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    parser.add_argument('--price-db', help='Đường dẫn database giá SQLite đã có')
    args = parser.parse_args()
    if args.price_db:
        if args.oracle_db:
            parser.error('--price-db không dùng cùng --oracle-db')
        price_db = Path(args.price_db).resolve()
        if not price_db.is_file():
            parser.error('Không tìm thấy database giá. Kiểm tra đường dẫn --price-db.')
        os.environ['QTA_PRICE_DB'] = str(price_db)

    # Configure repo mode
    if args.oracle_db:
        web_module.FORCE_MOCK = False
    else:
        web_module.FORCE_MOCK = True

    url = f"http://{args.host}:{args.port}"
    print("\n" + "=" * 70)
    print("    VNSTOCK QUANTITATIVE DASHBOARD (PRICE ACTION JOHN LUCAS PRUNI)")
    print("=" * 70)
    print(f" >> Giao diện Web đang chạy tại: {url}")
    print(f" >> Cơ sở dữ liệu: {'Oracle Database' if not web_module.FORCE_MOCK else 'SQLite Mock (Cục bộ)'}")
    print(" >> Nhấn Ctrl + C để dừng máy chủ web.")
    print("=" * 70 + "\n")

    if not args.no_browser:
        try:
            webbrowser.open(url + "/phase8")
        except Exception:
            pass

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
