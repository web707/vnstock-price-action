# QTA Phase 3.2 — Kiểm tra chất lượng dữ liệu

Bản này kế thừa Phase 3.1 và phần đăng nhập hiện có. Mục tiêu là phát hiện dữ liệu thiếu, bất thường và tránh dùng nhầm database. Chưa huấn luyện mô hình dự báo mới hay chứng minh tăng độ chính xác dự báo.

## Cách chạy trên Windows

1. Dừng cửa sổ web cũ và các tiến trình đang ghi database. Giải nén ZIP này vào một thư mục mới.
2. Database giá đã có sẵn tại `data/state/qta_phase3_test.db`. Không cần chép thêm. ZIP không kèm tài khoản cũ.
3. Nếu muốn giữ tài khoản cũ, chép database tài khoản của bản cũ vào đúng vị trí tương ứng; giữ bản sao dự phòng trước khi chuyển.
4. Mở PowerShell ngay trong thư mục có `requirements.txt`, `web_app.py` và `START_QTA.bat`, chạy:

```powershell
python -m pip install -r requirements.txt
.\START_QTA.bat
```

Có thể nhấp đúp `START_QTA.bat` sau khi cài thư viện. File này tự chuyển về đúng thư mục, kiểm tra database rồi mở web. Nếu trình duyệt mở trước khi server sẵn sàng, tải lại trang. Đăng nhập bằng tài khoản của bạn, vào phần dữ liệu và bấm đọc báo cáo chất lượng.

Chạy thủ công nếu cần:

```powershell
python audit_quality.py --db data/state/qta_phase3_test.db
python web_app.py --price-db data/state/qta_phase3_test.db --no-browser
```

Sau đó truy cập địa chỉ server in trong cửa sổ PowerShell. Không chạy lệnh từ thư mục cha nếu ở đó không có `requirements.txt`.

## Kết quả snapshot ngày 22/10/2026

Mở `audit_snapshot_20261022/BAO_CAO.html` để xem báo cáo độc lập, có tìm kiếm mã và lọc trạng thái. JSON và CSV trong cùng thư mục là kết quả kiểm tra tại thời điểm này, không phải dữ liệu trực tiếp.

| Chỉ tiêu | Kết quả |
|---|---:|
| Mã trong danh mục database | 1.579 |
| Mã có giá | 407 (25,78%) |
| Mã không có giá | 1.172 |
| Mã cần rà soát | 404 |
| Mã vượt qua kiểm tra nội bộ, chưa xác minh nguồn | 3 |
| Dòng giá | 1.253.257 |
| Ngày giá mới nhất | 21/10/2026 |

Ba mã vượt qua kiểm tra nội bộ là AFX, ANT, VAB. Điều này không chứng nhận giá đúng hoặc đủ lịch sử. Không có mã bị đánh dấu INVALID theo bộ kiểm tra OHLCV/ngày hiện tại; điều đó cũng không chứng minh toàn bộ dữ liệu sạch. Có 140.538 dòng volume bằng 0, 15.810 dòng nhãn chưa xác minh và 210 lần biến động close trên 20% cần rà soát. Các nhóm có thể chồng lấn; biến động lớn có thể liên quan sự kiện doanh nghiệp hoặc thiếu phiên.

File DB được kiểm tra có SQLite integrity_check = ok và SHA256:
`2aaa3f476377b76d3abb1cdffbe03ebfba0b134ef3ed1934407f6db500c14768`

## Những gì đã thay đổi

- Audit chỉ đọc: OHLCV, ngày lỗi/trùng/tương lai, volume 0, nhãn nguồn, thiếu ADJ_CLOSE, nhiều nguồn và biến động lớn.
- Báo cáo tất cả mã, kể cả mã chưa có giá; xuất JSON/CSV và hiển thị trên web.
- API yêu cầu đăng nhập; từ chối báo cáo không khớp database dựa trên kích thước, thời gian sửa và SHA256.
- Chọn database rõ ràng bằng `--price-db`; giao diện hiển thị tên database đang dùng.
- Metadata dữ liệu giữ `price_basis=unknown` khi chưa kiểm chứng điều chỉnh giá. Nhãn VALID không được coi là chứng nhận chính xác.
- Không tự xoá dòng volume 0, sửa giá hoặc đổi nhãn chưa xác minh thành VALID.

Khi database thay đổi, phải chạy lại audit. Kiểm tra checksum áp dụng cả file, nên thay đổi bảng khác trong cùng DB cũng có thể làm báo cáo hết hiệu lực. Dừng writer trước khi audit; WAL đang hoạt động sẽ bị từ chối. Audit có thể mất một lúc vì quét toàn bộ lịch sử.

## Kiểm chứng và giới hạn

74 kiểm thử liên quan chất lượng dữ liệu, tính toàn vẹn API, bộ lọc daily Phase 3.1, phục hồi dữ liệu và đăng nhập đã chạy thành công. JavaScript giao diện đã kiểm tra cú pháp. Khởi tạo repository trên bản sao database không làm đổi checksum.

Chưa kiểm thử thao tác giao diện trực tiếp trên trình duyệt hoặc chạy launcher trên Windows. Chưa kiểm chứng kết nối Yahoo/Oracle trực tiếp, đối chiếu nguồn giá độc lập, danh sách niêm yết hiện tại, lịch nghỉ lễ, chia tách/cổ tức hoặc độ chính xác dự báo ngoài mẫu. Bản này cung cấp nền tảng kiểm tra dữ liệu; không đưa ra tỷ lệ thắng hay cam kết dự báo.

Đây là phân tích thuật toán, không phải lời khuyên đầu tư.
