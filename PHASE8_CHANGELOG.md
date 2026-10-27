# Phase 8 — thay đổi so với Phase 7

- Giữ database nguồn nguyên byte trong ZIP, migration QTA8 có backup, atomic rollback và idempotence; importer bảo vệ revision.
- Bổ sung schema/CSV cho RAW, PIT universe, quyền, benchmark, calendar, daily limits, coverage. Kế hoạch incremental và adapter benchmark tùy chọn, chưa tải dữ liệu live thành công.
- Giá gốc + cột điều chỉnh, causal forward rescale, báo lỗi dữ liệu; không suy đoán ngành hoặc sự kiện quyền.
- Pooled logistic/calibration, rolling/expanding date splits, purging/embargo, date-block bootstrap, permutation giữ tần suất, registry cấu hình/dataset, strata và 3 mức bằng chứng. Từ chối xác suất khi không đủ điều kiện.
- Replay T+2 PM, tiền chờ thanh toán, trần/sàn, tick/lot, volume cap, slippage theo thanh khoản, fees/custody/margin và quyền. So sánh cùng lệnh lý tưởng với thực thi. Dữ liệu thật thiếu thì chặn.
- Quét vector hóa và cache mã/phiên bản; cùng dữ liệu407 mã: 20,889 → 2,837 giây trong môi trường kiểm thử. Sửa điểm flow VSI do nhiễu số thực.
- Trang /phase8 với Vì sao, bằng chứng, nghiên cứu OOS, health theo mã/năm, CSV, filter persistence, light/dark, mobile. Link giữ nguyên giao diện /phase7 và /.
- Thêm tests, Chromium smoke, benchmark script, hướng dẫn và log kiểm chứng thực tế.

## Chưa hoàn thành bằng dữ liệu thật

PIT toàn thị trường, benchmark/industry đầy đủ, quyền lịch sử, rulebook hiệu lực lịch sử, mô hình OOS nối engine end-to-end, giảm survivorship bias có định lượng, cache cập nhật riêng suffix và Windows thật. Không tuyên bố dự báo chính xác hơn. Chi tiết HUONG_DAN_PHASE8.md và PHASE8_VALIDATION.json.
