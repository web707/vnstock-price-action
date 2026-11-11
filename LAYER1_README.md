# Layer 1 — Swing Point Detection

Bản sửa độc lập trên QTA Phase 8. Chỉ thay package `swing_detector`; không sửa Layer 2,
database, thuật toán web trong `src/strategy`, hay script monolithic `inspect_swings.py`.
`run_pipeline.py` đang import package này nên nhận detector mới. Các màn hình web gọi
`src/strategy/market_structure.py` vẫn dùng thuật toán cũ; bản này không tự chuyển chúng.
Bản cũ trong `swing_detector_old/`, chỉ đổi đường import nội bộ để không vô tình dùng ATR mới.

## Chạy trên Windows

Giải nén toàn bộ ZIP vào thư mục mới, mở PowerShell tại thư mục có `requirements.txt`.
Giữ `SETUP_QTA.bat` và `START_QTA.bat` nguyên bản. Không chép đè database đang sử dụng.

```powershell
.\SETUP_QTA.bat
python layer1_cli.py --ticker HPG --csv data/hpg_15m_sample.csv --output data/layer1_swings.csv
python run_pipeline.py --csv data/hpg_15m_sample.csv --output-swings data/swings_output.csv
```

Nếu SETUP dùng môi trường ảo, thay `python` bằng `.\.venv\Scripts\python.exe` theo đường dẫn
môi trường của máy. Chưa kiểm thử trên Windows thật. File HPG mẫu đi kèm chỉ đến 19/10/2026;
đây không phải dữ liệu trực tiếp. Các snapshot vừa tải nằm tại `reports/layer1/fetched/`.

```powershell
python layer1_cli.py --ticker HPG --csv reports/layer1/fetched/HPG.csv --as-of "2026-10-28 15:00:00+07:00" --output data/layer1_swings.csv
python -m pytest tests/test_layer1_revision.py -q
python -m pip install matplotlib
python tools/compare_layer1.py
python tools/check_layer1_prefix.py
```

`tools/fetch_layer1_intraday.py` tải 5 mã qua yfinance và ghi lỗi nếu không tải được.
Không thay bằng dữ liệu giả hoặc daily. Chạy fetch sẽ thay snapshot nguồn trong thư mục fetched;
hãy lưu snapshot cũ nếu muốn tái hiện báo cáo hiện tại. Ngày chốt phép so sánh đặt tường minh
trong `tools/compare_layer1.py`.

## API và cấu hình

```python
import pandas as pd
from swing_detector import SwingDetectorConfig, detect_result, detect_swings_frame
from swing_detector.io import export_result
cfg = SwingDetectorConfig(ticker="HPG")  # cấu hình cơ sở chưa thay đổi
result = detect_result(pd.read_csv('candles.csv'), cfg, as_of='2026-10-28 15:00+07:00')
print(result.swings)
export_result(result, 'data/layer1_swings.csv')
```

| Tham số | Mặc định |
|---|---|
| timeframe | 15m |
| atr_period | 14, Wilder |
| pivot_left / pivot_right | 3 / 3 |
| reversal_atr_mult | 2.0 |
| reversal_min_pct | 0.005 |
| min_bars_between_swings | 0 |
| volume_lookback | 20 |
| tie_rule | first |
| timestamp_label | open |
| timezone / naive_timezone | Asia/Ho_Chi_Minh |
| sessions | 09:00–11:30 và 13:00–15:00 |
| ambiguous_bar_rule | defer |

Các alias cũ `swing_left`, `swing_right`, `reversal_mult`, `min_reversal_pct` được giữ
cho `run_pipeline.py`; nếu truyền, chúng ghi đè tham số tương ứng. Không trộn alias với
tham số mới trong cùng cấu hình. Core chỉ phụ thuộc pandas/numpy; adapter `detect_swings`
mới cần `common.models` để trả về kiểu Swing cũ.

## Quy ước bắt buộc phải hiểu

- Mỗi nến phải có Datetime/Open/High/Low/Close/Volume. Alias tên cột cũ vẫn được hỗ trợ.
- Sắp xếp ổn định, chọn bản ghi **hợp lệ đầu tiên** khi trùng timestamp; không nội suy.
  Log tổng số và từng lý do loại; volume=0 được giữ, tính vào chẩn đoán.
- Timestamp không có timezone được coi là giờ Việt Nam theo config. Cột timestamp mặc định
  là **đầu nến**: chỉ được sử dụng lúc timestamp+15 phút. `confirmed_at` là thời điểm đó;
  `extreme_time` là nhãn nến cực trị. Nếu nhà cung cấp dùng giờ đóng nến, đặt `timestamp_label='close'`.
  Chưa xác minh quy ước nhãn của nhà cung cấp bằng nguồn độc lập.
- Cần truyền `as_of` khi có khả năng dữ liệu chứa nến chưa đóng. Không truyền nghĩa là người gọi
  bảo đảm toàn bộ nến đã đóng. `--as-of` của CLI mới cắt nến trước tính chỉ báo;
  `--as-of` của runner cũ chỉ lọc ở Layer 2, không đổi runner trong phạm vi công việc này.
- Lịch phiên mặc định là **template**, không phải lịch chính thức HOSE/HNX/UPCoM.
  Cảnh báo slot thiếu có thể bao gồm nghỉ lễ, đấu giá hoặc khác quy ước provider. Không coi
  đó là số nến chắc chắn bị mất. Có thể truyền `expected_timestamps` hoặc `--calendar-csv`
  gồm cột Datetime để dùng lịch kỳ vọng riêng. Nến ngoài phiên/grid bị loại có log.
- TR đầu tiên=High-Low; 13 ATR đầu tiên NaN, ATR thứ 14=trung bình 14 TR. ATR sau đó Wilder.
  ATR nối qua gap bằng Close hợp lệ trước; không tự reset qua đêm hay điều chỉnh quyền.
- Một ứng viên phải đạt điều kiện trái ngay khi ghi nhận. Theo dõi cực trị tốt nhất **trong
  các ứng viên hợp lệ**; không giữ vô hạn cực trị không thể trở thành pivot trái.
  Bên trái dùng `>` cho HIGH, `<` cho LOW; bên phải dùng `>=`/`<=`.
  First-tie áp dụng toàn cửa sổ trái, kể cả các nến bằng giá không đứng liên tiếp.
- ATR và ngưỡng được cố định tại nến cực trị, không phải lúc cửa sổ phải đóng. Cần đủ nến
  phải và mức đảo chiều vẫn đạt T trên nến xác nhận hiện tại. Không hồi tố một lần chạm
  ngưỡng trước khi pivot sẵn sàng. Có thể làm giảm số swing so với cách lưu lần chạm trước.
- INIT cho phép bắt đầu HIGH hoặc LOW. Sau đó luân phiên tuyệt đối; tối đa một xác nhận/nến.
  Khi chuyển trạng thái có thể lấy ứng viên đối nghịch từ các nến đã biết sau cực trị vừa
  xác nhận; không xác nhận ngược thời gian hoặc trên cùng bước xử lý.
- Nến outside (High cao hơn và Low thấp hơn nến trước), có range >= T và cập nhật cực trị
  hoặc chạm ngưỡng: hoãn xác nhận trên nến đó. INIT có cả hai hướng đủ điều kiện cũng hoãn.
  Đây là quy tắc bảo thủ được chọn, không tái dựng thứ tự giao dịch bên trong nến.
- Khoảng cách và độ trễ tính bằng **số nến hợp lệ quan sát được**, không tính slot bị thiếu.
- `volume_ratio` = tổng Volume từ nến sau cực trị đến nến xác nhận / trung vị đúng 20 nến
  trước cực trị. Vì tử số là tổng nhiều nến, tỷ lệ phụ thuộc độ dài nhịp. Thiếu 20 nến hoặc
  median=0 thì NaN; không lọc swing theo volume.
- HH/LH so với HIGH trước; HL/LL so với LOW trước; lần đầu hoặc bằng giá để trống. Không dựng
  UP/DOWN/UNCLEAR. Adapter cũ để `structure_label=None`, Layer 2 tự gán nhãn như trước.

## Output và audit

Schema hiện tại (source_version=qta-layer1-1.1.0; rule_version=wilder-pivot-zigzag-v1):

```text
swing_id, ticker, timeframe, swing_type, extreme_price, extreme_time,
confirmed_at, atr_at_extreme, source_version, rule_version,
threshold_T, reversal_size_in_ATR, bars_since_prev_swing,
confirm_delay_bars, volume_ratio, label
```

`confirmed_at` thay `confirm_time`; `atr_at_extreme` thay `atr_at_candidate`;
`swing_type` thay `type`; `extreme_price` thay `price`. Không giữ bốn tên cũ trong
output chuẩn. Các bảng phân tích lịch sử ở reports/layer1 vẫn là báo cáo của lần chạy trước,
không dùng làm input Layer 2; output chuẩn mới nằm ở reports/layer1_schema/.

`swing_id` là số nguyên tăng từ 1, duy nhất trong một bảng cho một ticker/timeframe.
Đây là hợp đồng Layer 2 hiện tại, không phải ID toàn cục giữa nhiều mã/lần chạy.
Khi lưu nhiều mã vào SQL dùng khóa gồm ticker/timeframe/rule_version/run_id/swing_id;
không ghép các bảng rồi coi swing_id tự nó là khóa toàn cục. Exporter từ chối ID trùng/NULL.

Truyền `SwingDetectorConfig(ticker="HPG")`; ticker được strip/uppercase. API cũ không truyền
mã vẫn chạy nhưng ticker=NULL, không tự đoán từ tên file hoặc giá. CLI mới bắt buộc --ticker;
run_pipeline truyền --symbol vào config Layer 1. Hai cột version mô tả phần mềm/quy tắc,
không phải phiên bản dữ liệu của nhà cung cấp. Thuật toán không đổi ở bản chỉnh schema này.

`atr_at_extreme` thiếu/không hợp lệ được xuất NULL trong JSON, ô trống trong CSV,
NaN trong pandas; không ép thành 0. Detector vẫn không xác nhận swing khi ATR chưa đủ 14 nến.

CSV/JSON thêm threshold, lag_bars, vol_over_median, source_timeframe, structure_label,
pct_change, index, confirmed_at_index để Layer 2 hiện tại đọc trực tiếp. Các cột chính
extreme_time/confirmed_at dùng wall-time địa phương trong file do Layer 2 so sánh chuỗi;
*_iso và timezone giữ thông tin timezone. DataFrame core vẫn dùng timestamp có timezone.
CSV UTF-8 không BOM. Loader common cũ có fallback ATR thiếu thành 0 và volume thiếu thành 1;
không sửa loader do yêu cầu giữ Layer 2. Dùng cột canonical để kiểm toán giá trị NULL.

`detect_result` trả swings/candles/diagnostics/events/indices. `detect_swings` vẫn trả một
list-compatible object cho runner cũ, mang theo kết quả canonical; gọi `swing_detector.save_swings`
để giữ đầy đủ metadata. `common.io.save_swings` trực tiếp chỉ biết model legacy.

Chi phí/trượt giá chưa mô phỏng. Module sau này phải giao dịch từ `confirmed_at` trở đi,
không khớp lệnh tại giá cực trị quá khứ. Không có tuyên bố lợi nhuận hoặc dự báo chính xác hơn.
