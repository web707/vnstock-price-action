# Layer 2 — Phase 3

Triển khai ngoại tuyến theo SFS cho Structure Rule Provider và lịch sử trạng thái.
Entry point mới: `layer2_phase3_cli.py`. Không thay pipeline/web/BAT hay DB gốc.
Python có pandas, như môi trường Phase 2. Chạy từ thư mục gốc dự án:

```bash
python run_layer2_phase3_tests.py > LAYER2_PHASE3_TEST_LOG.txt 2>&1
python tools/report_layer2_phase3.py
python layer2_phase3_cli.py --swings reports/layer1_schema/HPG.csv --ohlcv reports/layer1/HPG_clean.csv --as-of '2026-10-28 23:59:59+07:00' --output reports/new_phase3_run --sqlite
```

Thư mục CLI output phải chưa tồn tại. JSON cấu hình tùy chọn qua `--rules`.
`config/layer2_phase3_baseline.json` là cấu hình đầy đủ, bất biến theo rule_version;
RuleProvider sao chép sâu và tính config_hash. Đổi quy tắc phải đổi rule_version.
Các policy chưa hỗ trợ bị từ chối; thiếu break rule thì UNCLEAR, không xác nhận.
Không có tên mã cổ phiếu, mức giá hoặc điều kiện HH/HL hard-code trong engine.
Các trạng thái và policy được hỗ trợ là hợp đồng triển khai; điều kiện chọn cửa sổ,
so sánh, protected level, break, amplitude và transition lấy từ cấu hình.

## Quy tắc đã duyệt

- D01-B: cửa sổ tham lam 4 swing liên tiếp, không tái sử dụng leg, cho phép chung
  swing biên; sau cửa sổ đạt hình học tiến 3 swing, kể cả bị từ chối lúc sinh.
- D02-A/D03-A: UP LOW–HIGH–LOW–HIGH với HL+HH; DOWN đối xứng LH+LL. Tolerance
  giữ `max(1, current_price * 0.0001)` theo D05 đang hoãn.
- D06-A: protected level cố định tại pivot hồi thứ ba.
- D07-A: một Close đã đóng vượt nghiêm ngặt protected level; bằng mức hoặc chỉ
  wick xuyên mức không làm BROKEN. Chỉ theo dõi nến mở từ confirmed_at trở đi.
- Tại available_at, Close cuối đã đóng vi phạm level: UNCLEAR, reason riêng,
  confirmed_at và invalidated_at NULL; không xóa, không hồi sinh hay lấp cửa sổ.
- D04: biên độ đầu–cuối/ATR tại swing đầu, ngưỡng 3 ATR là annotation. Thiếu ATR
  giữ NULL, không cản xác nhận hình học; audit Phase 1 ghi dữ liệu ATR thiếu.
- D09: dữ liệu mâu thuẫn bị quarantine; không thay swing đã xuất bản một cách ngầm.
- D11: giả thuyết kỹ thuật của dự án; không gán là phương pháp gốc đã kiểm chứng.

FORMING là quy ước kỹ thuật cấu hình: bắt đầu khi ba swing đã biết thỏa quan hệ
HL/LH hiện có. Swing thứ tư không đạt thì FORMING→UNCLEAR và tìm tiếp từ swing kế.
Vì vậy số bản ghi lịch sử lớn hơn số cửa sổ đủ bốn swing đạt hình học.

## Thời gian và event store

`StructureEngine` nhận snapshot bất biến, `advance(T)` xử lý theo thời điểm có
thông tin. Tại cùng timestamp, xử lý nến đóng trước swing. Có thể gọi `snapshot(T)`
cho quá khứ đã xử lý; không dùng trạng thái cuối để suy ngược lịch sử.
Đây là replay tăng dần trên snapshot, chưa có giao thức nhận sửa đổi live feed.

- formation_available_at: biết đủ ba swing để FORMING.
- geometry_available_at: biết đủ cửa sổ bốn swing đạt hình học.
- confirmed_at: thời điểm thực sự được CONFIRMED.
- invalidated_at: thời điểm đóng nến đầu tiên vi phạm sau confirmation.
- available_at trong projection: thời điểm cập nhật trạng thái hiện tại.
- event_time: extreme_time cuối cho sự kiện cấu trúc, open_time nến cho break.
- Mỗi event có available_at riêng, sequence và snapshot trạng thái trong payload.

`market_structure_event` append-only trong API lưu trữ. SQLite mới trong
`reports/layer2_phase3/structure_events.sqlite` có registry rule_version/config,
projection market_structure và event table. Ghi lặp không tăng số hàng; snapshot
cũ không làm lùi projection. Xung đột lịch sử hoặc cùng version khác config báo lỗi
và rollback. Không thay DB `data/state/qta_phase3_test.db`.

Các cấu trúc đều UNCLASSIFIED; structure_sequence_no và previous_major_structure_id
NULL. Chưa có chuỗi Major, context snapshot hoặc Long flag.

## Quyết định còn mở và giới hạn

D05 phải xử lý trước Phase 5; khi đó xem lại D02-A. D08 (chuỗi Major) và D10
(Long-context) còn mở, chưa triển khai. D06-C buffer 0.5 ATR và D07-C hai Close
được lưu disabled để thử ở Phase 5; chưa cho bật trong baseline này.

Chỉ dùng snapshot 5 mã 07/08–28/10/2026. Chưa kiểm chứng lịch sở và staleness của
Close cuối có sẵn tại availability; không tự thêm TTL hay điều chỉnh tick. D05
vẫn còn vấn đề tolerance/giá điều chỉnh đã ghi ở Phase 2. Break theo toàn bộ nến
còn lại trong snapshot, không dùng giới hạn 20 nến của khảo sát phương án.
Không có đánh giá PnL, vận hành live hoặc xác nhận tương thích Windows trong lượt này.
