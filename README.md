# QuantumTrade AI (QTA)

**Mã dự án nghiên cứu: NCKH-BIGDATA-STOCK-2026**

QTA nghiên cứu cách phát hiện swing, cấu trúc thị trường và tín hiệu đảo chiều trên dữ liệu cổ phiếu Việt Nam. Pipeline theo dõi thời điểm một nến hoặc sự kiện có thể được sử dụng, giúp kiểm tra look-ahead bias trong replay.

## Kiến trúc

| Tầng | Mã nguồn | Vai trò |
| --- | --- | --- |
| Layer 1 | `swing_detector/` | Kiểm tra OHLCV, tính Wilder ATR và xác nhận pivot/swing theo thời điểm dữ liệu có sẵn |
| Layer 2 | `structure_builder_sfs/` | Dựng cấu trúc SFS, phân loại và ghi sự kiện chuyển trạng thái để tái hiện theo thời gian |
| Layer 3 | `reversal_setup_detector/` | Áp dụng quy tắc `L3_REVERSAL_V1`, theo dõi vòng đời setup và hỗ trợ lưu trạng thái vào SQLite |

Luồng phân tích là **OHLCV 15 phút → swing → sự kiện cấu trúc → reversal setup**. Các thành phần chính dùng Python 3.12, pandas, NumPy và SQLite. Collector Yahoo dùng yfinance và tzdata. Nền tảng Phase 8 và ứng dụng web có [tài liệu riêng](PHASE8_PLATFORM_README.md).

## Cấu trúc thư mục

- `extensions/daily_15m_collector/` chứa collector 15 phút, cấu hình VN30, lịch nghỉ HOSE và launcher Windows.
- `extensions/vn30_expansion/` chạy replay nghiên cứu và xuất funnel theo mã, kể cả các mã thiếu dữ liệu.
- `docs/` và `config/` chứa đặc tả và quy tắc. Xem [đặc tả Layer 2](docs/SFS_LAYER2_v1.0.md) và [đặc tả Layer 3](docs/SPEC_LAYER3_v1.0.md).
- `tests/`, `phase*_tests/` và `reversal_setup_detector/tests/` chứa các bài kiểm tra.
- `reports/` và thư mục dữ liệu của collector được tạo ở máy chạy.

## Cài đặt trên Windows

Mở PowerShell tại thư mục clone. Bỏ qua Git LFS smudge nếu chỉ cần mã nguồn và không cần fixture Phase 8 cũ.

```powershell
$env:GIT_LFS_SKIP_SMUDGE = '1'
git clone https://github.com/web707/vnstock-price-action.git
cd vnstock-price-action
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-qta-research.txt
```

### Thu thập OHLCV 15 phút

```powershell
.\.venv\Scripts\python.exe -X utf8 extensions/daily_15m_collector/collect_vn30_yahoo.py --fallback-59
```

Collector dùng các mã `.VN` trong [cấu hình kỳ VN30 tháng 7/2026](extensions/daily_15m_collector/config.vn30.2026-07.json). Mỗi mã có kết quả riêng trong `logs/fetch_runs.jsonl` của module. Collector thử `60d`, có thể thử lại với `59d` khi truy vấn lỗi. SQLite ghi thêm theo khóa mã/khung giờ/timestamp và giữ bản đã ghi khi Yahoo trả lại cùng khóa. Dữ liệu thực, log, SQLite live và ZIP bàn giao lưu tại máy chạy. Hãy kiểm tra quyền sử dụng và phân phối dữ liệu với nhà cung cấp trước khi chia sẻ.

Để chạy sau phiên, xem [hướng dẫn Task Scheduler](docs/WINDOWS_VN30_COLLECTOR.md). Launcher `extensions/daily_15m_collector/vn30/RUN_AFTER_CLOSE.bat` thử toàn bộ danh sách và dùng lịch nghỉ HOSE theo năm.

### Chạy pipeline nghiên cứu

```powershell
.\.venv\Scripts\python.exe -X utf8 -m layer1_cli --help
.\.venv\Scripts\python.exe -X utf8 -m extensions.vn30_expansion.run_vn30
```

Layer 1 nhận CSV cục bộ có `Datetime,Open,High,Low,Close,Volume`. Runner VN30 đọc snapshot nghiên cứu tại `reports/layer1/<TICKER>_clean.csv`, xuất kết quả sang `reports/extensions/vn30/` và ghi `MISSING_15M_OHLCV` cho mã chưa có dữ liệu. Bản clone mới không kèm snapshot nghiên cứu mới. [Hướng dẫn Module VN30](extensions/vn30_expansion/README.md) mô tả hợp đồng dữ liệu và lịch replay. SQLite từ Yahoo chưa được nối tự động vào replay do cần lịch và mốc công bố nến đã xác minh.

## Chạy test không cần dữ liệu thị trường

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest --noconftest -q tests/test_layer1_revision.py phase1_tests phase2_tests phase3_tests phase4_tests phase5_tests reversal_setup_detector/tests extensions/daily_15m_collector/test_collector.py extensions/vn30_expansion/test_vn30.py -k "not Real and not snapshot and not evidence"
```

Các ca dùng snapshot hoặc báo cáo replay cần dữ liệu cục bộ. Lệnh trên chạy bộ test công khai đã chọn.

## Kiểm chứng và giới hạn

- Bản xác nhận Layer 3 trước đó ghi nhận 100 bài regression và 22 ca acceptance đạt. Replay snapshot 5 mã ghi nhận 4.482 nến và 16 checkpoint vòng đời point-in-time theo lịch thực nghiệm của snapshot. Các ca replay snapshot cần dữ liệu cục bộ tương ứng.
- Lần thu thập ngày 11/11/2026 nhận dữ liệu 15 phút cho cả 30 mã cấu hình. Collector giữ nguyên nến đã ghi qua các lượt chạy lại. Kết quả này xác nhận độ phủ ở thời điểm kiểm tra.
- Nhãn 14:45, bản ghi volume 0, thời điểm Yahoo công bố từng nến và lịch point-in-time theo nhà cung cấp còn cần xác minh. Danh sách HOSE có hiệu lực theo kỳ công bố. Replay theo các kỳ lịch sử cần danh mục tại từng thời điểm.

Dự án phục vụ nghiên cứu. Các tín hiệu và kết quả replay không phải khuyến nghị đầu tư hay bằng chứng về lợi nhuận.
