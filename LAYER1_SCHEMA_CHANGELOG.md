# Layer 1 output schema 1.1.0 — 29/10/2026

Đổi tên cột chính theo yêu cầu, trong cả DataFrame và exporter CSV/JSON:

| Trước | Hiện tại |
|---|---|
| type | swing_type |
| price | extreme_price |
| confirm_time | confirmed_at |
| atr_at_candidate | atr_at_extreme |

Thứ tự cột chính:
`swing_id, ticker, timeframe, swing_type, extreme_price, extreme_time, confirmed_at, atr_at_extreme, source_version, rule_version`.
Giữ các cột phụ threshold_T, reversal_size_in_ATR, bars_since_prev_swing,
confirm_delay_bars, volume_ratio, label và alias mà reader Layer 2 hiện tại cần.

- source_version=qta-layer1-1.1.0; rule_version=wilder-pivot-zigzag-v1.
- `swing_id` duy nhất trong bảng của một ticker/timeframe, giữ integer để Layer 2 không đổi.
  Export từ chối ID trùng/NULL. Không coi ID này là khóa toàn cục giữa các mã/lần chạy.
- `ticker` truyền qua config; CLI yêu cầu --ticker. Runner cũ truyền --symbol vào config.
  API không truyền mã giữ NULL, không đoán. Không sửa Layer 2/common/models/database.
- ATR không hợp lệ xuất ô trống CSV / NULL JSON / NaN pandas; không ép thành 0.
  Loader common cũ vẫn có fallback ATR thiếu→0, được giữ nguyên; output file giữ NULL.
- Thời gian DataFrame có timezone. File giữ wall-time ở cột chính cho so sánh chuỗi của
  Layer 2, bổ sung extreme_time_iso/confirmed_at_iso/timezone để tránh mất timezone.
- `save_swings` của package Layer 1 giữ metadata canonical khi nhận list do detector trả.
  `common.io.save_swings` trực tiếp vẫn là exporter legacy.
- Thuật toán phát hiện, cấu hình cơ sở, detector lưu trữ và database không thay đổi.
- Báo cáo so sánh cũ trong reports/layer1 là lịch sử; file output mới cho Layer 2 ở
  reports/layer1_schema/{HPG,FPT,VNM,VCB,SSI}.csv.

## Kiểm chứng lượt sửa này

- 51 tests passed, 1 warning Starlette/httpx, 25.63 giây.
- Bao gồm 6 ca mới cho schema/metadata CSV/JSON, ATR NULL, ID trùng và bảng rỗng.
- Test Layer 2 đọc file và lọc as_of đúng tại thời điểm xác nhận đầu tiên.
- Chạy CLI và run_pipeline trên HPG mẫu: 61 swings, hoàn tất Layer 2.
- Regression cùng snapshot 5 mã, cutoff28/10/2026: HPG57/FPT57/VNM81/VCB73/SSI56.
  So sánh type, giá, ATR, T, độ trễ và cả hai timestamp với output trước: không đổi.
- Hash xác nhận structure_builder/common/src/strategy/database/BAT không đổi.
- Không chạy lại toàn bộ suite web/database ở lượt đổi schema; 269 tests trong báo cáo cũ
  là kết quả lượt trước, không trình bày thành kết quả mới. Chưa chạy Windows thật.

## Chạy

```powershell
.\.venv\Scripts\python.exe layer1_cli.py --ticker HPG --csv data/hpg_15m_sample.csv --output data/layer1_swings.csv
```

File HPG mẫu chỉ đến19/10; dùng snapshot fetched hoặc CSV riêng nếu cần thời gian khác.
Chi tiết trong LAYER1_README.md; log và kiểm chứng ở reports/layer1_schema/.
