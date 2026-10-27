# QTA Phase 5 — Giao diện nghiên cứu, tìm kiếm và bộ lọc

## Chạy nhanh

1. Dừng cửa sổ chạy bản cũ. Giải nén toàn bộ ZIP vào thư mục mới.
2. Database giá đã có sẵn trong `data/state/qta_phase3_test.db`.
3. Mở PowerShell tại thư mục có requirements.txt:

```powershell
python -m pip install -r requirements.txt
.\START_QTA.bat
```

Chờ kiểm tra dữ liệu rồi truy cập http://127.0.0.1:8000. Nếu trình duyệt mở sớm, tải lại trang. Giữ cửa sổ server mở khi dùng web. Máy mới chưa có tài khoản thì đăng ký trên trang đăng nhập. ZIP không chứa tài khoản cá nhân từ máy cũ.

## Cách sử dụng

Trang mặc định là **Tổng quan nghiên cứu**. Bên trái, nhập mã hoặc tên doanh nghiệp, có thể bỏ dấu tiếng Việt. Có bộ lọc sàn và chỉ mã có giá. Nhấn kết quả để xem phân tích. Mã chưa có giá được ghi rõ; chọn mã đó sẽ hiển thị thông báo thiếu dữ liệu và xoá kết quả cũ để không nhầm mã.

Hồ sơ kỹ thuật hiển thị thẻ điểm, giá đóng cửa theo đơn vị nguồn, RSI, volume tương đối, đường giá 60 phiên, bằng chứng chấm điểm, MA/ATR và mốc đỉnh đáy. Cảnh báo mặc định mở. Với dưới 200 phiên, giao diện chỉ rõ chưa đủ MA200 và tối đa có 85/100 điểm được đánh giá.

Bộ quét có lọc volume, xu hướng, loại dữ liệu có thể cũ và yêu cầu đủ 200 phiên. Bộ lọc áp dụng ngay trên kết quả đã có, không phải quét lại. Mã lỗi/thiếu dữ liệu vẫn hiển thị để không che mất vấn đề. Có thể nhấn mã trong bảng để mở hồ sơ, dừng sau lô hiện tại, hoặc xuất các hàng đang hiển thị thành CSV.

Công cụ rủi ro vẫn nhận giá bằng đồng/cổ phiếu: giá 21 nghìn đồng nhập 21000. Phí, thuế bán và trượt giá là giả định có thể chỉnh sửa, không phải xác nhận biểu phí hiện hành. Stop không đảm bảo khớp khi gap/giá sàn/thiếu thanh khoản.

Các tab cấu trúc giá, kiểm thử chiến lược, tham số và quản lý dữ liệu vẫn có trên thanh điều hướng. Bản này không bổ sung nguồn báo cáo tài chính hay dự báo học máy.

## Logic tìm kiếm và tối ưu

- Xếp hạng tìm kiếm: đúng mã → khớp đầu mã → khớp cụm tên doanh nghiệp → khớp mọi từ tìm kiếm. Bỏ dấu, không phân biệt hoa/thường; mỗi kết quả có lý do khớp. Không tự đổi một mã nhập sai thành mã khác.
- Tra toàn danh mục SQLite, bao gồm mã không có giá và mã giá thiếu hồ sơ doanh nghiệp. Danh mục hiện có 1.579 mã, 407 mã có giá; chưa xác minh danh sách niêm yết hiện tại.
- Bộ nhớ đệm kết quả nghiên cứu giới hạn 512 mục, tối đa 120 giây; danh mục tối đa 60 giây. Khoá gồm trạng thái file database và ngày Việt Nam. Khi file thay đổi, kết quả cũ không được tái sử dụng; khi có WAL/journal đang hoạt động thì bỏ qua cache. Oracle không dùng cache này.
- Kết quả cache được sao chép trước khi trả về để một yêu cầu không làm thay đổi kết quả của yêu cầu khác. Các chỉ báo không bị xấp xỉ hay cắt bớt lịch sử để tăng tốc.
- Tìm kiếm trì hoãn 220ms sau lần gõ cuối; kết quả của yêu cầu cũ không ghi đè lần tìm mới. Phân tích từng mã cũng bỏ phản hồi cũ khi đã đổi mã.
- CSS riêng cho màn hình nghiên cứu có bố cục thích ứng 760px/1100px. Các tab cũ vẫn sử dụng Tailwind/Chart.js từ CDN và cần truy cập được các CDN tương ứng.

## Kiểm chứng

90 kiểm thử hồi quy đã đạt; sau đó bổ sung kiểm thử thay đổi DB phải làm mất hiệu lực cache và chạy lại nhóm discovery: 6 kiểm thử đạt. Tổng 91 trường hợp khác nhau đã đạt qua các lượt. Bao gồm tìm tên có/không dấu, ưu tiên đúng mã, lọc sàn, mã không có giá, giới hạn cache, TTL, tránh sửa chung kết quả, WAL và thay đổi DB.

Kiểm tra tích hợp JavaScript bằng jsdom với API FastAPI thực đã đạt: khởi tạo có đăng nhập; dựng thẻ nghiên cứu; tìm tên doanh nghiệp; quét nhiều mã kèm mã lỗi; tính khối lượng; tạo tải CSV; xoá kết quả cũ khi mã mới thiếu dữ liệu. Không có lỗi JavaScript trong các luồng này. JavaScript cũng qua kiểm tra cú pháp.

Chưa xác nhận hình ảnh hiển thị/thao tác trên trình duyệt thật ở desktop/mobile: tải Chromium trong môi trường kiểm thử thất bại. Kiểm thử DOM không thay thế kiểm thử hình ảnh hoặc tương tác trình duyệt. Launcher chưa chạy trực tiếp trên Windows.

Một phép đo cục bộ với HPG: lần tính đầu khoảng 0,206 giây, lần lấy kết quả cache khoảng 0,0012 giây; chỉ báo giống nhau. Đây là thời gian hàm phía server trong môi trường thử, không phải cam kết tốc độ website/toàn thị trường. Chi tiết trong phase5_validation.json.

## Giới hạn dữ liệu và ý nghĩa điểm số

Database đính kèm là file người dùng đã gửi, ngày giá mới nhất 21/10/2026. Không có cập nhật giá mới trong bản nâng cấp này. Không coi các nhãn VALID/UNVERIFIED hoặc việc chạy thành công là chứng nhận giá đúng.

Điểm kỹ thuật vẫn là quy tắc thiết kế, không phải xác suất thắng. Lọc đủ 200 phiên giúp tránh so điểm giữa các mã có số tiêu chí khác nhau, nhưng không loại bỏ tương quan giữa chỉ báo hoặc thiên lệch danh mục. Chưa có backtest ngoài mẫu để khẳng định cải thiện dự báo/lợi nhuận.

Đây là phân tích thuật toán, không phải lời khuyên đầu tư.
