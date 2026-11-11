# Layer 2 — Phase 2: Swing Legs & Amplitude

Chỉ Phase 2 theo SFS v1.0. Giữ nguyên code cũ trong `structure_builder/` và
`src/strategy/`; Phase 1 và Layer 1 không đổi. Module mới:
`structure_builder_sfs.phase2`.

## Chạy độc lập (Python 3.10+; kiểm thử thực tế Python ghi trong log)

Cài dependencies tối thiểu cho Phase 1/2:

```bash
python -m pip install pandas numpy
python layer2_phase2_cli.py --swings reports/layer1_schema/HPG.csv --ohlcv reports/layer1/HPG_clean.csv --as-of "2026-10-28 23:59:59+07:00" --output my_phase2_hpg
python run_layer2_phase2_tests.py > LAYER2_PHASE2_TEST_LOG.txt 2>&1
python tools/report_layer2_phase2.py
```

CLI chỉ ghi vào thư mục mới để không ghi đè snapshot. Lệnh chạy test ghi đè log
cùng tên: hãy dùng tên khác nếu muốn giữ nguyên log bàn giao. Không cần tải lại
thị trường để tái lập bộ dữ liệu 5 mã đã kèm. Web/BAT/run_pipeline cũ không được
chuyển sang Phase 2 trong gói này.

```python
from structure_builder_sfs.phase2 import LegConfig, build_legs, sensitivity
result = build_legs(swings_df, ohlcv_df, as_of="2026-10-28 23:59:59+07:00",
                    config=LegConfig(atr_multiplier=3.0))
legs = result["swing_leg"]
comparison = sensitivity(legs)  # 1.5 / 2.0 / 2.5 / 3.0
```

## Hợp đồng dữ liệu

- Biên độ tuyệt đối = abs(end_price - start_price).
- `pct_amplitude` là tỷ lệ, không phải số đã nhân 100: 0.1 nghĩa là 10%.
- `atr_reference` lấy từ swing BẮT ĐẦU; thiếu/không hợp lệ → NULL, không gán 0.
- `amplitude_atr` = absolute_amplitude / atr_reference.
- Ngưỡng = atr_multiplier × atr_reference; dùng so sánh >= (bao gồm bằng ngưỡng).
- `available_at` = max(confirmed_at của hai endpoint); `event_time` = end_time.
- `duration_minutes`: thời gian lịch, bao gồm nghỉ trưa/qua đêm.
- `duration_bars`: chỉ tính khi có lịch nến liên tục 15 phút đã kiểm tra; khác
  trường hợp đó để NULL, không lấy duration_minutes/15 qua giờ nghỉ.
- `classification` luôn UNCLASSIFIED trong Phase 2. Không tạo market_structure.
- Reason `AMPLITUDE_TOO_SMALL_INTERNAL` là tên có sẵn trong SFS, KHÔNG có nghĩa
  classification=INTERNAL ở Phase 2; chi tiết được ghi trong payload_json.
- NULL trong JSON dùng `DataFrame.to_json`; CSV là ô trống. Boolean NULL khác False.
- `leg_id`: SHA256 của ticker/timeframe/source_version/rule_version/config hash/
  hai swing ID. Chạy cùng snapshot/config → cùng ID; version khác có namespace khác.
  Nếu đổi config, nên đặt rule_version mới; config_hash tránh va chạm khi quên đổi.

## Thời gian và quarantine

Hàm replay các nhóm confirmed_at đến as_of, mỗi nhóm dùng Phase 1 để sắp theo
extreme_time. Đây không phải sắp confirmed_at rồi coi đó là trật tự giá.
Leg đã phát hành được giữ bất biến. Nếu swing đến muộn chèn vào giữa leg đã
phát hành, ghi DATA_ORDER_AMBIGUOUS và quarantine bản ghi mới; cần rebuild
source/version riêng để xem xét lại. Không tự thay leg. Không backdate leg mới
nếu adjacency chỉ trở nên hợp lệ sau thời điểm hai endpoint đã xác nhận.

`phase2_audit`/`phase2_quarantine` là dấu vết bổ sung, `raw` giữ nguyên đầu vào.
`swing_label`/`quarantine` từ Phase 1 là snapshot cuối tại as_of; `swing_leg` là
lịch sử leg đã phát hành đến as_of. Vì vậy một batch lỗi xuất hiện về sau có thể
làm snapshot nhãn bị quarantine mà không xóa lịch sử leg. Không được suy ra
"active structure" từ bảng leg này; Phase 3 chưa triển khai.

`batch_log` giữ số structure/status = NULL vì chưa đánh giá; `legs` và
`leg_UNCLASSIFIED` là số leg, không dùng làm số structure UNCLASSIFIED.

## Giới hạn

Dùng replay để ưu tiên khả năng kiểm toán; chưa tối ưu incremental/stateful,
chưa lưu SQL, chưa có vòng đời cấu trúc. Dữ liệu giá vẫn là snapshot Yahoo
đã lưu, không xác thực lại với dữ liệu sở. Xem D05_PRICE_UNIT_REVIEW.md trước
khi xét điều chỉnh tolerance. Không tự thay ngưỡng hoặc sửa giá nguồn.
