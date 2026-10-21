# QTA — Đợt 2: Tài khoản và phân quyền

## Chạy bản mới
1. Dừng bản cũ bằng Ctrl+C trong PowerShell.
2. Giải nén bản đợt 2 vào thư mục mới. Vào thư mục `vnstock-price-action-main` chứa `web_app.py`.
3. Chạy:

```powershell
python -m pip install -r requirements.txt
python web_app.py --no-browser
```

4. Mở http://127.0.0.1:8000. Trang sẽ chuyển sang `/login`.
5. Bấm Đăng ký, tạo tên đăng nhập (3–32 ký tự a-z/0-9/._-) và mật khẩu (10–128 ký tự). Sau đó đăng nhập.
6. Bấm Thiết lập tài khoản để lưu tên hiển thị và mã mặc định. Mã mặc định phải có trong database để được chọn trên dashboard.

Không có mật khẩu mặc định. Tài khoản đầu tiên cũng là user, không tự trở thành admin.

## Cấp admin
Sau khi đăng ký tài khoản, mở PowerShell thứ hai trong cùng thư mục dự án và chạy (thay `thinh` bằng tên đã đăng ký):

```powershell
python -m src.web.auth --promote thinh
```

Đăng xuất rồi đăng nhập lại. Trong Thiết lập tài khoản, admin có thể tải danh sách tài khoản và đổi quyền tài khoản khác. Đổi quyền qua giao diện sẽ thu hồi các phiên của tài khoản bị đổi. Không cho tự thay đổi quyền để tránh mất tài khoản admin đang quản lý.

## Quyền
- Khách: chỉ xem trang đăng nhập và đăng ký/đăng nhập.
- User: dashboard, biểu đồ, tín hiệu, backtest, xem dữ liệu, lưu thiết lập của mình.
- Admin: thêm quyền tải dữ liệu vào database chung và quản lý quyền tài khoản.
- Toàn bộ `/api/*` khác hai endpoint đăng ký/đăng nhập yêu cầu phiên hợp lệ. Trang docs cũng yêu cầu đăng nhập.
- Giá thị trường và chức năng backtest hiện vẫn dùng database chung. Chỉ hồ sơ/thiết lập được tách theo người dùng; watchlist, danh mục và lịch sử backtest riêng sẽ thuộc bước mở rộng sau.

## Cách bảo vệ
- Mật khẩu băm scrypt với salt ngẫu nhiên. Không lưu mật khẩu rõ.
- Cookie HttpOnly, SameSite=Strict; phiên ngẫu nhiên được lưu dạng SHA-256 phía server, hết hạn sau 8 giờ.
- Đăng nhập lại thay phiên hiện tại; đăng xuất thu hồi phiên trên server.
- Request ghi dữ liệu yêu cầu JSON và CSRF token; kiểm tra Origin nếu có. Đã gỡ CORS wildcard.
- Giới hạn đăng ký/đăng nhập: 10 lần theo tên tài khoản và 40 lần theo IP trong 15 phút. Bộ đếm lưu SQLite, dùng chung giữa worker. Giới hạn tính mọi lần thử, kể cả thành công; chưa có cơ chế mở khóa qua UI.
- Không tin header X-Forwarded-For từ client. Khi sau proxy, nhiều người có thể cùng chịu giới hạn IP.
- Quản trị không trả password hash hay token phiên trong danh sách tài khoản.

## Lưu dữ liệu / nâng cấp
Tài khoản, phiên và thiết lập nằm trong `data/state/qta_accounts.db`, tách khỏi database giá `vietnam_stocks_mock.db`. Khi chuyển bản sau, dừng server rồi sao lưu/copy file tài khoản này. Không đưa file tài khoản hoặc `.env` vào Git hay gửi công khai. Bản ZIP bàn giao không có tài khoản/phiên kiểm thử.

Nếu bạn đã tải thêm dữ liệu giá vào bản cũ, dừng server và copy `data/state/vietnam_stocks_mock.db` từ bản cũ sang bản mới để giữ dữ liệu đó. Nếu dùng Oracle, copy `.env` cấu hình tại máy của bạn và chạy với `--oracle-db`; tài khoản QTA vẫn lưu SQLite riêng.

## Triển khai và giới hạn
Bản này dành cho chạy local mặc định. Khi đưa lên Internet cần HTTPS, `QTA_COOKIE_SECURE=1`, và `QTA_PUBLIC_ORIGIN` đúng tên miền; kiểm tra reverse proxy, sao lưu và quyền truy cập file DB. Chưa có xác minh email, quên mật khẩu, MFA hay nhật ký audit quản trị. Chưa thực hiện pentest hay chứng nhận an toàn production.

Đã sửa header dashboard cho phép xuống hàng và bỏ nhãn Oracle cố định. Màn hình đăng nhập dùng CSS nội bộ; dashboard cũ vẫn sử dụng Tailwind/Chart.js CDN và cần mạng để tải chúng.

## Kiểm thử
Kết quả: toàn bộ suite 121 test đạt; sau đó bổ sung 3 ca bảo mật và chạy lại nhóm auth: 24/24 đạt (tổng 124 ca đã kiểm tra). Có 1 cảnh báo deprecation Starlette/HTTPX, không có test thất bại.

Chạy `python -m pytest -q` trong thư mục dự án. Test dùng database tài khoản tạm, không sửa tài khoản thật. Có kiểm thử API auth, CSRF, role, hết hạn/thu hồi phiên, giới hạn thử, tách thiết lập người dùng và hồi quy bộ phân tích đợt 1.

Cú pháp JS của hai trang đã được kiểm tra bằng Node. Chưa kiểm tra trực quan/đầu-cuối trên trình duyệt thực của bản đợt 2; không suy diễn rằng toàn bộ giao diện đã được xác minh từ test API.
