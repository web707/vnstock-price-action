# Thay đổi Phase 6 → Phase 7

## Giữ nguyên

- Database giá giữ nguyên byte và schema, kèm trong ZIP; không migrate phá dữ liệu.
- Giao diện `/`, API và các module Phase 6 vẫn còn: đăng nhập, quản trị, tải/khôi phục giá, tìm mã, phân tích, evidence và backtest cũ.
- Cơ chế auth/session/CSRF áp dụng cho API mới. Thêm chuyển đến login cho `/phase7` chưa đăng nhập.

## Thêm mới

- `src/phase7/features.py`: regime từng mã, trọng số điểm thích nghi, ADX/slope/ATR percentile, volume/OBV/A-D, pivot xác nhận, breakout/pullback, VCP heuristic, phân kỳ; khung tuần đã đóng.
- `model.py`: logistic L2 và scaler/imputer train-only, calibration validation-only, purged expanding walk-forward, Brier/AUC/log loss, bins/Wilson, contributions, abstention khi thiếu mẫu/model cũ, sensitivity C, block-bootstrap Monte Carlo.
- `portfolio.py`: next-session orders, vốn tiền mặt, ATR sizing/trailing, trần tỷ trọng/rủi ro/thanh khoản, thanh toán bảo thủ, sàn/trần có tham chiếu hoặc xấp xỉ ghi rõ, metrics và benchmark có điều kiện.
- `data.py`, `service.py`: đọc SQLite read-only, cache revision/TTL, độ rộng cùng phiên, RS/percentile, ngành theo khoảng hiệu lực, compare/correlation, sức khỏe dữ liệu.
- `store.py`: dữ liệu cá nhân tách DB, watchlist/alert dedup/nhật ký/filter theo username.
- `reports.py`: PDF tiếng Việt có phân trang và CSV chống formula injection; xuất mã/toàn bộ scan.
- `api.py`, `ui.html`: giao diện responsive sáng/tối, canvas nến/MA/volume/pivot/B-S, các màn hình nghiên cứu, model, danh mục, cá nhân, chất lượng dữ liệu.
- `import_phase7_reference.py`, templates CSV: nhập benchmark/calendar/limits/sectors/units có kiểm tra trước khi ghi.
- Test mới, Playwright script, guide, báo cáo validation và requirements-dev.

## Thay đổi nhỏ trong nền cũ

- `src/web/app.py`: include router Phase 7.
- `src/web/auth.py`: `/phase7` redirect login tương tự `/`.
- `src/web/templates/index.html`: link mở Phase 7; không bỏ nội dung cũ.
- `web_app.py`: trình duyệt mặc định mở `/phase7`.
- `requirements.txt`: thêm scikit-learn và reportlab.
- `SETUP_QTA.bat`: kiểm tra đã giải nén, tạo `.venv` và cài thư viện trong đó. START/FIND_PYTHON giữ luồng kiểm tra Python/database.

## Chưa hoàn tất mục tiêu nâng cao

- Chưa có bằng chứng hiệu quả OOS; dữ liệu kèm thiếu benchmark/ngành/universe lịch sử và chỉ ít mẫu đạt calibration.
- Chưa xử lý đầy đủ survivorship, corporate actions và thực thi intraday thị trường Việt Nam. STRICT là kiểm tra tham chiếu đã cung cấp, không chứng nhận khớp đúng quy chế.
- Chưa học trọng số theo regime VN-Index/breadth lịch sử. Điểm thích nghi dùng regime từng mã.
- Monte Carlo mới là chẩn đoán, chưa formal significance/multiple-testing control.
- Rebalance mới thay tập mã, không ép weights; correlation là công cụ đọc, chưa ràng buộc tối ưu.
- Cảnh báo chỉ trong tab đang mở; nhật ký chưa sửa/đóng một phần/import broker.
- Cold scan chưa dưới vài giây; chưa chạy BAT trên Windows thật; dữ liệu live/Yahoo/Oracle không được xác minh trong đợt này.

Chi tiết định nghĩa, giả định, điều kiện từ chối và kế hoạch Phase 8 ở `HUONG_DAN_PHASE7.md`.
