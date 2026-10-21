# QTA — Đợt 1: Chuẩn hóa dữ liệu web

## Phạm vi
Nâng cấp từ ZIP vnstock-price-action-git-source-fixed(1).zip. Giữ nguyên thuật toán ATR, swing, cấu trúc thị trường, chiến lược và backtest. Chưa triển khai đăng nhập hay thiết kế lại giao diện.

## Thay đổi
- Thêm `src/web/market_data.py`: dùng chung cho history, swings, Layer 2 và tín hiệu ngày.
- Không fallback API sang database. Database chỉ được yêu cầu với `timeframe=1d`.
- Kiểm tra schema OHLCV, số hữu hạn, giá dương, quan hệ OHLC, volume nguyên không âm, timestamp thiếu/trùng/tương lai. Sắp xếp thời gian trước khi giới hạn số nến.
- Intraday cần ít nhất hai timestamp và bằng chứng khoảng cách đúng khung nến; từ chối dữ liệu ngày giả làm 15 phút và khoảng cách nhỏ hơn khung yêu cầu. Cho phép khoảng nghỉ phiên và nến thiếu. Đây không phải xác minh toàn bộ lịch giao dịch/sàn.
- Timestamp có timezone được đổi về Asia/Ho_Chi_Minh; timestamp không timezone được hiểu là giờ Việt Nam và ghi cảnh báo trong metadata.
- Trả metadata nguồn, provider, timeframe, timezone, fetched_at (thời điểm bắt đầu đọc), data_as_of (timestamp nến cuối của tập nguồn). `freshness=unverified`, `realtime_verified=false`, `last_bar_closed=null`: không tuyên bố realtime hay nến cuối đã đóng.
- Với Layer 2, metadata mô tả tập dữ liệu nguồn trước cutoff; requested_cutoff mô tả yêu cầu, cutoff_time trong báo cáo mô tả mốc phân tích.
- Biểu đồ và bảng tín hiệu hiện dùng chung nguồn DB/khung ngày. Biểu đồ hiển thị tối đa 300 nến, tín hiệu tính trên toàn bộ lịch sử ngày. Xóa kết quả cũ khi đổi mã; xử lý lỗi HTTP; bỏ qua phản hồi trễ của mã đã đổi.
- Sửa `/api/fetch`: đường dẫn seed đúng, constructor importer đúng, lấy batch_id từ reporter, số mã tải thành công dựa trên kết quả thật; dùng thông tin sàn có sẵn, không mặc định mọi mã là HOSE. UI báo riêng thành công/một phần/không dữ liệu/lỗi.
- Bổ sung FastAPI, Uvicorn, HTTPX trong requirements.
- Test Layer 2 cũ đã sửa yêu cầu DB sang khung 1d rõ ràng.

## Chạy trên máy của bạn
Giải nén và mở terminal trong thư mục `vnstock-price-action-main`:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python web_app.py --no-browser
```

Mở http://127.0.0.1:8000. Mặc định dùng SQLite cục bộ. Muốn dùng Oracle cần cấu hình `.env` và chạy `python web_app.py --oracle-db --no-browser`.

Ví dụ API:
- `/api/history/HPG?source=db&timeframe=1d&limit=300`
- `/api/history/HPG?source=api&timeframe=15m&limit=300`
- `/api/swings/HPG?source=api&timeframe=15m`
- `/api/layer2/structure/HPG?source=db&timeframe=1d&date=2026-09-15`

Lỗi dữ liệu dùng `detail.code` và `detail.message`. SOURCE_UNAVAILABLE: nguồn không dùng được; TIMEFRAME_SOURCE_MISMATCH: DB không có intraday; TIMEFRAME_MISMATCH: không xác minh được khung; INVALID_OHLCV/INVALID_TIMESTAMP: dữ liệu không đạt kiểm tra. Một số lỗi tham số và lỗi Layer 2 kế thừa vẫn có detail dạng chuỗi.

## Kiểm chứng và giới hạn
Kết quả: `python -m pytest -q` — **100 passed**, 1 cảnh báo deprecation của Starlette TestClient/HTTPX (không làm test thất bại).

Kiểm thử dùng fixture xác định và database mẫu đi kèm; không xác thực giá thị trường bằng nguồn độc lập. Đã kiểm tra cú pháp JavaScript bằng Node. Chưa kiểm tra giao diện trực tiếp trong trình duyệt, chưa kết nối Yahoo/Oracle thực tế của người dùng.

Chưa xác minh độ trễ theo lịch nghỉ/sàn, đơn vị giá gốc, điều chỉnh cổ tức/chia tách, nguồn gốc dữ liệu mẫu, trạng thái đóng nến và tính đầy đủ dữ liệu. Không nên coi kiểm tra timestamp là chứng nhận chất lượng nhà cung cấp. Các hạng mục này cần đối chiếu nguồn thực tế trước khi dùng để quyết định giao dịch. Kiểm chứng đầy đủ backtest thuộc đợt 5.

Bản ZIP giữ nguyên byte các tệp dữ liệu/database mẫu từ ZIP đầu vào; không đóng gói database/log được sinh hoặc thay đổi khi chạy test. Không chứa môi trường ảo/cache.
