# Layer 3 Phase 2 — event-history context

API `ContextProvider` chỉ nhận event history Layer 2, không nhận bảng market_structure trạng thái cuối. Dùng Layer 2 MajorContext đã có để replay **prefix available_at <= T** và phân loại Major; không sửa code upstream. Chọn hai Major cuối theo EVER_CONFIRMED trước khi kiểm tra DOWN/CONFIRMED/BROKEN. ACTIVE chỉ xuất hiện trong audit đối chứng, không phải fallback.

```python
import pandas as pd
from reversal_setup_detector.context import ContextProvider
history = pd.read_csv('reports/layer2_phase3/HPG/market_structure_event.csv')
provider = ContextProvider(history)
result = provider.evaluate('2026-10-28 15:00+07:00',
    ticker='HPG', timeframe='15m', source_version='qta-layer1-1.1.0')
```

Payload tương lai không được parse khi query quá khứ. Prefix đã biết được validate theo rule_version/config_hash, event_sequence và transitions của Layer 2; lịch sử thiếu/đụng nhau/version sai báo lỗi contract, không bỏ qua để tìm context thuận lợi. Cache chỉ theo prefix đã biết và stream; hỗ trợ query không theo thứ tự, trả bản sao. `context_available_at` là thời điểm trạng thái mới nhất của hai cấu trúc được biết (bao gồm break), khác với end_time của hình học.

`evaluate_triplet` dùng availability của bộ ba, giữ ID hai cấu trúc cùng trạng thái tại T và reason. `context_age_bars` đếm nến hợp lệ đã available với open_time > end_time của cấu trúc thứ hai và <= open_time R3; chỉ là số nến quan sát. `context_age_coverage_complete=false` vì lịch nguồn chưa verified; không nội suy nến thiếu và không lọc độ cũ.

Cấu hình `config/L3_REVERSAL_V1_PHASE2.json` là revision mới của baseline V1, ghi các phê duyệt Phase 2. Giữ nguyên file `L3_REVERSAL_V1.json` và log Phase 1 để không thay hash/kết quả phiên bản cũ. L3-D04 DEFERRED; allow_cross_session_sequences vẫn true cho baseline nghiên cứu có điều kiện theo template.

Chạy từ gốc dự án, cùng môi trường Python/pandas của QTA:

```bash
python reversal_setup_detector/tools/report_phase2.py > reports/layer3_phase2/DATA_RUN_LOG.txt 2>&1
python reversal_setup_detector/run_phase2_tests.py > LAYER3_PHASE2_TEST_LOG.txt 2>&1
```

Test suite gồm regression Phase 1 + test Phase 2. Các test đối chiếu dữ liệu báo cáo cần chạy report trước. Phase 2 chưa tạo candidate WAITING_REVERSAL, chưa tìm G, chưa có lifecycle/event persistence/LONG_SETUP. Kết quả context_valid không phải tín hiệu giao dịch. Không đọc/ghi database gốc.
