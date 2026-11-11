# Layer 2 Phase 5 — Backtest Validation cấu trúc

Môi trường nghiên cứu riêng theo SFS mục 10. Không tính lệnh, lợi nhuận, PnL hay
win rate giao dịch. Giữ nguyên toàn bộ gói Phase 4 và database gốc. Các biến thể
chỉ có hiệu lực khi được gọi trong module Phase 5; không đổi default production.

## Tái lập

Python có pandas/numpy; chạy từ thư mục gốc dự án:

```bash
python tools/audit_phase5_inputs.py > reports/layer2_phase5/INPUT_AUDIT_LOG.txt 2>&1
python tools/report_layer2_phase5.py > reports/layer2_phase5/VALIDATION_RUN_LOG.txt 2>&1
python run_layer2_phase5_tests.py > LAYER2_PHASE5_TEST_LOG.txt 2>&1
```

Mã: structure_builder_sfs/phase5.py, phase5_metrics.py. Mỗi biến thể có rule_version
và config hash riêng; SQLite mới reports/layer2_phase5/research_events.sqlite.
Config được xuất cho từng lần chạy. Không nâng phiên bản hoặc đổi config ở giữa batch.

## Phạm vi và thuật ngữ

5 mã: HPG/FPT/VNM/VCB/SSI, OHLCV 15m và swing Layer 1 đã lưu, 07/08–28/10/2026.
Candidate = cửa sổ bốn swing đạt hình học. History record = mọi FORMING/UNCLEAR/
CONFIRMED/BROKEN. Ever-confirmed = đã từng CONFIRMED, kể cả về sau BROKEN.
Tỷ lệ BROKEN cuối mẫu = BROKEN / ever-confirmed. Pre-broken ở availability bị loại
khỏi mẫu số, vẫn giữ trong lịch sử. Không lấy số bản ghi lịch sử làm mẫu số.

Lifetime giờ = invalidated_at − confirmed_at, gồm đêm/ngày nghỉ. Mean/median
completed chỉ tính trên mẫu BROKEN. Mẫu active là right-censored; chỉ báo tuổi quan
sát tới nến đóng cuối, không coi đó là lifetime hoàn chỉnh. Đồng thời báo số nến.
Không dùng mean completed để ước lượng tuổi thọ trung bình toàn quần thể.
Bổ sung tỷ lệ BROKEN trong 20 nến quan sát, chỉ trên mẫu có >=20 nến follow-up;
mẫu thiếu horizon không tự coi là không bị phá. Có cohort theo tháng xác nhận,
không coi ba tháng này là đủ nhiều chế độ thị trường hoặc dữ liệu ngoài mẫu.

## Thay từng tham số (OAT)

- BASELINE: các quyết định đã duyệt; D04 3.0 ATR classification, D05 hiện tại.
- D05_TICK_PROXY: một tick theo thang giá điều chỉnh, có điều kiện/chưa verified.
- D05_PCT_0_1: tolerance = 0.001 × giá hiện tại (0,1%).
- D06_C: cộng/trừ 0.5 ATR tại pivot hồi vào protected level cố định.
- D07_C: hai Close liên tiếp vượt strict level sau confirmation.
- D04_2_5: chỉ đổi ngưỡng classification sang 2.5; không thay lifecycle.
- D01_OVERLAP_DIAGNOSTIC: cho cửa sổ chồng lấn, tìm lại từ swing kế tiếp; các quy
  tắc khác giữ nguyên. Chỉ kiểm tra giả thuyết hiếm INTERNAL do D01-B.

D07-C: Close hồi về hoặc chạm level reset; nến lỗi có bản ghi cũng reset.
Khoảng nghỉ không có bản ghi không tự tạo nến; liên tiếp theo quan sát, chưa kiểm
chứng lịch sở đầy đủ. Birth guard vẫn một Close cho mọi biến thể. D06-C thiếu ATR
pivot → UNCLEAR, reason PROTECTED_PIVOT_ATR_MISSING. Không tự cứu mẫu pre-broken.

## D05 và metadata điều chỉnh

CURRENT = max(1 VND, 0.0001 × current_price).
TICK_PROXY = max(effective_tick_current, effective_tick_reference) + 0.01 VND
sai số số học. Tick HOSE dựa trên giá as-traded giả định rồi quy đổi lại cùng thang.
Giá lưu suy ra là VND/share, unit_scale=1. FPT trước 21/09/2026 dùng factor 1.1,
SSI trước 17/08/2026 dùng 1.2, lấy từ Stock Splits trong snapshot nhà cung cấp;
còn lại giả định factor=1. Không tự áp thêm cash dividend vào OHLC. Epsilon 0.01
hấp thụ residual float khi dựng lưới (dưới 0.004 VND trong swing đã kiểm tra).
Không snap hoặc sửa giá. Đây là quy ước của phép thử, chưa được duyệt production.

Chưa có verified raw/as-traded prices, adjustment factors hoặc thời điểm thông tin
corporate action thực sự được biết. Tick proxy có thể dùng sự kiện sau extreme_time
để hiểu thang của snapshot tải cuối kỳ; vì thế là sensitivity ex-post có điều kiện,
KHÔNG phải kết quả lịch sử as-received được xác nhận. D05 vẫn DEFERRED. Đề xuất giữ
CURRENT cho baseline nghiên cứu chờ owner quyết; không chọn tick proxy chỉ vì ít BROKEN.
D05_label_comparisons.csv tính lại quan hệ theo từng tolerance; Phase 1 dùng để
validate input, các nhãn cũ của Phase 1 không được dùng thay cho geometry mới.

## Bằng chứng và giới hạn TC15

- 5 mã × 7 cấu hình: replay từng nến, so toàn bộ event/payload với batch tại mỗi T.
- So projection cuối; chạy lại mới từ raw input bị cắt tại 25%/50%/75% dữ liệu.
- Oracle độc lập quét cửa sổ bốn swing và các nến sau birth, không gọi lifecycle
  engine; dùng chung rule provider/validation. Oracle giới hạn dữ liệu sạch,
  confirmation đơn điệu; unit tests riêng kiểm tra lỗi và edge cases.
- TC16 ghi SQLite lặp; TC17 nhiều rule_version cùng tồn tại và chặn config collision.

PASS TC15 là bằng chứng thuật toán Layer 2 không đọc nến/swing tương lai trên
snapshot cố định đang thử. Không chứng minh dữ liệu giá đã điều chỉnh hồi tố là
point-in-time; chưa có kho as-received. Không khẳng định bảo đảm tuyệt đối mọi
revision/live feed hoặc hiệu quả giao dịch. D08 không có mode mặc định; D10 giữ NULL.

## Đầu ra

sensitivity_summary.csv: counts/delta/rates/lifetime/MAJOR/INTERNAL và Jaccard ranh giới.
structure_lifetimes.csv: mỗi mẫu với censor/follow-up/giờ/nến. monthly_cohorts.csv;
D05_label_comparisons.csv; boundary_changes.csv; break_timing_changes.csv.
Mỗi mã/cấu hình có market_structure, event, audit, config, independent_batch_oracle.
INPUT_AUDIT.json ghi input hashes và audit mở rộng universe. Gói không có thêm mã
vì các mã audit chỉ có giá ngày, thiếu OHLCV 15m + swing chuẩn; không nội suy thành
nến 15m, chưa xác minh thành phần VN30 point-in-time. Chưa kiểm thử Windows.
Bảng cuối D01–D12 nằm trong báo cáo chính và docs/LAYER2_PHASE5_DECISIONS.json.
