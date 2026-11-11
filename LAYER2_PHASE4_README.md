# Layer 2 — Phase 4: Major Sequence & Context

Phase 4 bổ sung classification và context trên event history Phase 3. Không sửa
mã, cấu hình, event, database hay báo cáo Phase 3. Entry point mới là
`layer2_phase4_cli.py`; đây là workflow ngoại tuyến riêng, chưa nối vào giao diện web.

## Quy tắc được duyệt

D04 = 3.0 ATR, dùng để phân loại, không phải điều kiện CONFIRMED:
- Cấu trúc từng CONFIRMED có amplitude_atr >= 3.0 → MAJOR.
- Cấu trúc từng CONFIRMED có amplitude_atr < 3.0 → INTERNAL.
- ATR thiếu/không hợp lệ → UNCLASSIFIED cùng reason; không tự coi là INTERNAL.
- FORMING và UNCLEAR không tham gia phân loại MAJOR/INTERNAL hoặc chuỗi Major.
- Cấu trúc BROKEN vẫn giữ classification và vị trí trong lịch sử chuỗi.

Bộ lọc hiện ít phân biệt: **63 MAJOR / 1 INTERNAL trên 64 cấu trúc**. INTERNAL gần
như không xuất hiện trong baseline D01-B không cho chồng lấn. Xem lại ở Phase 5;
vai trò nhân quả của D01-B là giả thuyết kỹ thuật cần kiểm thử, chưa phải kết luận
về mọi bộ dữ liệu. Cấu trúc INTERNAL duy nhất hiện tại là VNM 62→65 (2,6984 ATR).

D12: FORMING sau ba swing đã confirmed cho thấy HL/LH; swing thứ tư quyết định
hình học đầy đủ. Đã được owner chấp nhận là giả thuyết kỹ thuật của dự án.

## Chuỗi và hai chế độ tách biệt

Chuỗi giữ **cả UP và DOWN**, gồm toàn bộ MAJOR từng được xác nhận trước/đúng T.
Đánh số từ 1 theo confirmed_at, rồi end_time, start_time, structure_id để phá hòa
một cách xác định. Các khóa phụ là quy ước kỹ thuật về thứ tự, không ưu tiên UP.
`previous_major_structure_id` trỏ tới Major trước trong lịch sử, kể cả đã BROKEN.
ACTIVE không đánh số lại hay thay previous link khi một cấu trúc bị phá.

API bắt buộc truyền `mode`:
- `EVER_CONFIRMED`: hai Major gần nhất từng được xác nhận tại T, kể cả BROKEN tại T.
- `ACTIVE`: hai Major gần nhất còn CONFIRMED tại T; bỏ các Major đã BROKEN tại T.

D08 chưa chọn mặc định; bỏ mode hoặc mode không hợp lệ thì báo lỗi. CLI cho
`--mode BOTH` như lệnh chạy rõ ràng hai truy vấn độc lập, xuất hai file khác nhau.
Không có mode gộp và không tự chọn EVER_CONFIRMED/ACTIVE khi người gọi bỏ qua.

Đủ hai mẫu: context_status=OK; thiếu: INSUFFICIENT_STRUCTURE. Trả tối đa các mẫu
thật đang có, không nhân đôi hoặc tạo mẫu giả. Khi chỉ có một mẫu, older_structure_id
NULL, latest_structure_id là mẫu đó. Không đủ mẫu được ghi thêm selection_reason_code.

D10 vẫn DEFERRED: mọi context đều có is_long_candidate=NULL và
reason_code=LONG_CONTEXT_NOT_EVALUATED, ngay cả khi thiếu cấu trúc. Layer 3 sẽ quyết
quy tắc Long; không suy Long từ hướng UP/DOWN ở đây.

## Point-in-time và version

Đầu vào là **toàn bộ market_structure_event**, không phải bảng trạng thái cuối.
Mỗi truy vấn lọc available_at <= T, replay đúng thứ tự event, rồi mới phân loại và
chọn cặp. T đúng lúc CONFIRMED thì mẫu được dùng; T đúng lúc BROKEN thì ACTIVE loại
mẫu, EVER_CONFIRMED vẫn giữ. Không đọc trạng thái cuối để suy ngược lịch sử.

`config/layer2_phase4_baseline.json` chứa ngưỡng, policy, thứ tự, mode không mặc định,
Long NULL, ghi chú và upstream version/hash. Phase 4 có rule_version riêng; ID cấu
trúc giữ từ Phase 3 để truy xuất nguồn. Snapshot/context IDs bao gồm version, stream,
T và mode. Registry chặn cùng rule_version nhưng config khác. Muốn đổi cấu hình phải
đổi rule_version; mã không tự nâng version hoặc chọn threshold theo mã cổ phiếu.

SQLite mới: `reports/layer2_phase4/structure_context.sqlite`:
- phase4_rule_version: registry JSON/hash.
- phase4_snapshot: snapshot hoàn chỉnh tại T, bất biến.
- classified_structure_snapshot: classification của từng cấu trúc tại T.
- major_structure_sequence: thứ tự Major và previous link tại T.
- structure_context_snapshot: mode, cặp IDs, trạng thái và Long NULL.

Ghi lại cùng dữ liệu không nhân bản. Cùng snapshot/context ID khác nội dung bị từ
chối trong transaction. Snapshot quá khứ và phiên bản khác cùng tồn tại, không
update/xóa lịch sử. Dữ liệu gốc và database QTA cũ không bị thay đổi.

## Chạy trên Python có pandas

Tại thư mục gốc ZIP sau giải nén:

```bash
python layer2_phase4_cli.py --events reports/layer2_phase3/HPG/market_structure_event.csv --ticker HPG --timeframe 15m --source-version qta-layer1-1.1.0 --as-of "2026-10-28 23:59:59+07:00" --mode BOTH --output reports/my_phase4_run --sqlite
python tools/report_layer2_phase4.py
python run_layer2_phase4_tests.py > LAYER2_PHASE4_TEST_LOG.txt 2>&1
```

Output CLI phải là thư mục chưa tồn tại. Thay `BOTH` bằng `EVER_CONFIRMED` hoặc
`ACTIVE` để chạy một chế độ. Có thể truyền `--rules path/to/config.json`.

API:

```python
import pandas as pd
from structure_builder_sfs.phase4 import MajorContext
engine = MajorContext(pd.read_csv("reports/layer2_phase3/HPG/market_structure_event.csv"))
result = engine.last_two("2026-10-28 23:59:59+07:00",
    ticker="HPG", timeframe="15m", source_version="qta-layer1-1.1.0",
    mode="ACTIVE")
```

## Giới hạn và công việc Phase 5

Snapshot hiện tại kết thúc 28/10/2026; truy vấn không tự lấy thêm dữ liệu. Chỉ nên
đánh giá T trong phạm vi dữ liệu đã xử lý. Source stream cần được chỉ định rõ;
không trộn phiên bản Layer 1. Lỗi event/thiếu lịch sử/mismatch version bị từ chối,
không tự sửa. Module đọc snapshot bất biến, chưa phải giao thức live feed/revision.

Phase 5: xem lại D04 cùng tác động không chồng lấn của D01-B; quyết D05 và xem lại
D02-A; báo thêm số BROKEN và tỷ lệ BROKEN cho D06-C (buffer 0.5 ATR) và D07-C
(hai Close), nêu mẫu số, horizon và trường hợp bị phá ngay lúc sinh. Hai biến thể
chưa chạy và chưa bật ở Phase 4. D08 mặc định vẫn DEFERRED; D10 giao Layer 3.
Chưa backtest PnL, mô phỏng lệnh, kiểm chứng ngoài mẫu hay thử chạy Windows.
