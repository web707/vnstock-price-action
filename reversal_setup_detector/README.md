# Layer 3 — Phase 1

Module độc lập: kiểm tra OHLCV, công thức body/wick, đỏ/xanh/doji, bộ ba đỏ liên tiếp và khoảng trống nến. Chưa chọn context, chưa tạo setup, chưa tìm nến G, chưa có lifecycle/storage/LONG_SETUP.

## Chạy lại

Từ thư mục gốc gói ZIP, dùng Python 3.10+ (khuyến nghị môi trường Python hiện có của QTA). Module chạy bằng standard library; test đối chiếu Layer 2 cần pandas có sẵn theo requirements của dự án. Trên Windows, cài `tzdata` nếu Python không có cơ sở dữ liệu timezone IANA.

```bash
python reversal_setup_detector/run_phase1_tests.py > LAYER3_PHASE1_TEST_LOG.txt 2>&1
python reversal_setup_detector/tools/report_phase1.py > reports/layer3_phase1/DATA_RUN_LOG.txt 2>&1
```

API chính:

```python
from reversal_setup_detector import Rules, Calendar, analyze
rules = Rules()
# expected_slots: danh sách lịch đã chuẩn hóa do pipeline cung cấp;
# mỗi slot có open_at, close_at, session_id. verified phải phản ánh bằng chứng thật.
calendar = Calendar(expected_slots, rules,
                    calendar_id="YOUR_VERSIONED_CALENDAR", verified=True,
                    coverage_start="2026-10-26 00:00+07:00",
                    coverage_end="2026-10-27 00:00+07:00")
result = analyze(candle_rows, rules, calendar,
                 as_of="2026-10-26 15:00+07:00")
```

`candle_rows` có ticker, timeframe, candle_time, open/high/low/close/volume và available_at nếu biết. `result` gồm candles (cả invalid), triplets, gaps, diagnostics, metrics. Triplet giữ đủ OHLCV và timestamp của R1/R2/R3, version/hash, lịch và available_at. Đây là pattern_id, KHÔNG phải setup_id.

## Quy tắc và dữ liệu

- Giá dùng Decimal từ biểu diễn đầu vào; không thêm tolerance vào màu nến hoặc so sánh body > total_wick. Volume=0 hợp lệ; không lọc theo volume.
- Sắp xếp theo thời gian trong từng ticker/timeframe, không sửa OHLCV. Nến invalid là barrier; không xóa rồi ghép hai bên. Tất cả bản ghi trùng timestamp đã biết bị quarantine. Dữ liệu thiếu định danh/timestamp không định vị được làm API báo lỗi contract thay vì ngầm bỏ qua.
- Cấu hình đề xuất timestamp open theo Layer 1: `candle_time = Datetime`, đóng nến tại slot.close_at; với mẫu 15m hiện tại là candle_time + 15 phút. `available_at = max(close_at, source_available_at)`; thiếu available_at thì derive close, có cờ availability_derived. Nến đến trễ chỉ được dùng khi thực sự available; available_at của bộ ba là max availability của cả ba.
- Calendar là đầu vào độc lập có coverage và version/hash. Không suy lịch từ các hàng đang có vì sẽ che nến thiếu. Calendar.template chỉ tái dùng mẫu L1 ngày thường AM/PM, luôn UNVERIFIED; không xác nhận lịch nghỉ lễ hay cách nhà cung cấp ghi ATO/ATC.
- Gap verified ghi DATA_GAP_IN_CANDLE_SEQUENCE; gap theo mẫu ghi UNVERIFIED_CALENDAR_GAP. Cả hai đều chặn ghép trong phép chạy nghiên cứu này, không nội suy nến. Ngoài mẫu lịch là invalid. Đây là xử lý thận trọng công khai trong cấu hình, chờ duyệt cùng L3-D04, không khẳng định lịch mẫu là lịch chuẩn của sở.
- Gap chỉ tính giữa timestamp đầu/cuối đã quan sát; không tuyên bố đủ dữ liệu ở hai đầu. Không có quá trình tự sửa/thu hồi dữ liệu live trong Phase 1.
- `allow_cross_session_sequences=true` là đề xuất theo chữ đặc tả. Slot kế tiếp qua trưa/qua đêm được liền nhau nếu calendar xác nhận không có nến thiếu. Biến thể false có rule_version riêng, chỉ để báo cáo.
- File `five_slot_window_diagnostics.csv` đếm ranh giới của 5 slot dự kiến sau từng R3 (bao gồm ranh giới R3 → slot đầu). Có cột complete_5_valid_bars; cửa sổ thiếu nến không được coi là hoàn chỉnh. Không tìm G, không check ratio/context, không chuyển trạng thái; đây chỉ là chẩn đoán phục vụ L3-D04.
- Calendar của dữ liệu thật chưa verified: thống kê 25 triplet là có điều kiện theo template. Có 09:00/14:30 thiếu có hệ thống và các ngày không có dữ liệu; không tự phân biệt nghỉ lễ với thiếu toàn phiên. Cần lịch chuẩn và mô tả timestamp của nhà cung cấp trước khi khẳng định completeness.
- Dữ liệu dùng snapshot điều chỉnh đã lưu. Prefix test chỉ kiểm chứng thuật toán candle trên snapshot đó; chưa kiểm chứng lịch sử as-received hay context Layer 2 của Phase 2.

## Version và phạm vi

`config/L3_REVERSAL_V1.json` lưu cả tham số Phase 1 và các trường dự kiến cho phase sau. L3-D01…D05 đều PROPOSED. Các trường context/ratio/lifecycle không được thực thi trong Phase 1. API sao chép config; thay config V1 phải dùng rule_version khác. config_hash và calendar_hash đi cùng output; chưa có registry persistence (Phase 4).

Bản sao phần B giữ nguyên bytes từ heading PHẦN B đến cuối file, gồm cả code fence. Bản prompt đầy đủ lưu tại source/PROMPT_LAYER3_VA_SPEC.md để đối chiếu. Đây là baseline dự án, chưa khẳng định phương pháp gốc Gianluca Bruni.
