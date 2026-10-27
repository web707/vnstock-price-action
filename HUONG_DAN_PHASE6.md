# QTA Phase 6 — Kiểm chứng tín hiệu có căn cứ

## Chạy trên Windows

Dừng bản cũ, giải nén toàn bộ ZIP vào thư mục mới. Database giá đã có sẵn trong `data/state/qta_phase3_test.db`.

Lần đầu trên máy này: nhấp đúp **SETUP_QTA.bat**. File sẽ tìm Python, cài requirements rồi khởi động. Những lần sau chỉ cần nhấp đúp **START_QTA.bat**. Chờ audit hoàn tất và mở http://127.0.0.1:8000. Giữ cửa sổ server mở. Nếu trình duyệt mở trước server, tải lại trang.

Bộ tìm Python ưu tiên .venv có sẵn, `py -3.12`, `py -3`, sau đó `python`. Yêu cầu Python >=3.11, khuyến nghị 3.12. Nếu vẫn không tìm thấy thì cài Python từ python.org, chọn Add python.exe to PATH và mở lại cửa sổ lệnh. File này không tự tải hay cài Python.

Chạy thủ công nếu muốn, từng lệnh một:

```bat
py -3.12 -m pip install -r requirements.txt
py -3.12 audit_quality.py --db data/state/qta_phase3_test.db
py -3.12 web_app.py --price-db data/state/qta_phase3_test.db
```

Máy mới chưa có tài khoản thì đăng ký trên trang đăng nhập. Gói không chứa tài khoản từ máy cũ.

## Luồng sử dụng mới

Tìm doanh nghiệp → đọc hồ sơ kỹ thuật → nhấn **Kiểm chứng tín hiệu mã này** → chọn tham số → **Đánh giá lịch sử**. Cũng có thể mở tab Kiểm chứng tín hiệu trên thanh điều hướng.

Trang mới hiển thị số cửa sổ được chọn, lợi suất trung bình sau phí, chênh lệch so với baseline, tỷ lệ thắng lịch sử và khoảng Wilson 95%. Bảng theo thời gian chia tối đa 4 giai đoạn liên tiếp. Bảng 20 cửa sổ gần nhất hiển thị ngày tín hiệu, ngày vào/ra, điểm và lợi suất. Xuất CSV lấy toàn bộ quan sát đủ điều kiện, bao gồm cả những cửa sổ không được bộ điểm chọn, cùng tham số đã dùng.

Ba trạng thái chính:

- Chưa đủ mẫu: dưới 20 cửa sổ được chọn. Đây là ngưỡng cảnh báo thực dụng, không phải bảo đảm thống kê khi vượt 20.
- Chưa thấy lợi thế: lợi suất bình quân bộ điểm không lớn hơn baseline.
- Chênh lệch bình quân dương trong mẫu: chỉ là mô tả lịch sử; không có nghĩa đã chứng minh ý nghĩa thống kê hoặc hiệu quả tương lai.

Không có mẫu thì các thống kê để trống, không điền tỷ lệ thắng giả. Profit factor để trống khi không có mẫu hoặc không có tổng lỗ, tránh biểu diễn vô hạn như một kết quả chắc chắn.

## Thuật toán và phương pháp

Phân tích hiện tại và đánh giá lịch sử dùng cùng `score_components` trong src/research.py. Chỉ báo được tính một lần trên toàn chuỗi; không tính lại toàn lịch sử cho mỗi ngày. Công thức MA/RSI/MACD/ATR và các trọng số được giữ nhất quán với bộ điểm của Phase 5.

Đánh giá bắt đầu ở nến thứ 200 để đủ MA200. Với kỳ h thuộc 5, 10, 20: tín hiệu được tính ở close t; giả định mua open t+1 và bán close t+h. Các mốc t cách nhau h bản ghi, nên cửa sổ nắm giữ không chồng lấn. Kết quả đánh giá một lịch cố định, không phải mọi tín hiệu phát sinh hằng ngày.

Bộ lọc chỉ dùng thông tin tại thời điểm tín hiệu: volume TB20 đủ ngưỡng; 20 nến gần nhất có volume >0 và nhãn VALID; 20 biến động close gần nhất không vượt 20% tuyệt đối; 20 nến gần nhất cùng nguồn. VALID chỉ là nhãn nhập dữ liệu, chưa chứng nhận giá chính xác. Các trường hợp bị loại có thể là đặc điểm hợp lệ của thị trường, không mặc nhiên là lỗi.

Nếu volume tại điểm vào/ra bằng 0, cửa sổ được báo riêng là không có khối lượng để thực hiện và không đưa vào thống kê. Việc loại này dùng thông tin thực hiện trong tương lai và có thể gây thiên lệch; báo cáo nêu rõ số trường hợp. Chưa có mô hình trì hoãn khớp lệnh hoặc mô phỏng lệnh không khớp đầy đủ.

Chi phí áp dụng theo giả định người dùng chọn:

- Giá mua sau chi phí = open × (1 + slippage) × (1 + fee).
- Thu về khi bán = close × (1 − slippage) × (1 − fee − tax).
- Lợi suất ròng = thu về / chi phí mua − 1.

Baseline là mọi cửa sổ qua cùng bộ lọc, bộ điểm chọn các cửa sổ có điểm >= ngưỡng. Hai nhóm khác số mẫu và mức tham gia thị trường; nhóm chọn là tập con baseline. Chênh lệch bình quân không phải lợi nhuận danh mục, CAGR, Sharpe hay kết quả buy-and-hold. Chưa mô phỏng vốn, lô, T+2, giới hạn giá, thanh khoản khớp lệnh, stop-loss hoặc cổ tức.

## Kiểm chứng thực hiện

- 99 kiểm thử đạt: hồi quy đăng nhập/API/dữ liệu, công thức chỉ báo, điểm dùng chung, không sử dụng dữ liệu tương lai, entry ở open kế tiếp, cửa sổ không chồng lấn, chi phí, dữ liệu thiếu, Wilson và tham số không hợp lệ.
- Luồng JavaScript được kiểm tra với jsdom và API FastAPI thật: đăng nhập, mở hồ sơ, chuyển sang kiểm chứng, tính HPG, hiển thị khoảng thống kê, tải CSV, AAV không có mẫu đủ điều kiện và xoá kết quả cũ khi mã mới lỗi. Không có lỗi JavaScript trong các luồng đã kiểm tra.
- Smoke test trên HPG, FPT, AAV, ABB dùng DB đã gửi; JSON không chứa NaN/Infinity. AAV và ABB trả về 0 mẫu đủ điều kiện với tham số mặc định, không suy ra tỷ lệ thắng. Chi tiết trong phase6_validation.json.
- JavaScript qua kiểm tra cú pháp. Chưa kiểm chứng trực quan trên trình duyệt thật; các lần tải Chromium trước thất bại. DOM test không thay thế visual/browser test.
- Các file .bat đã được chỉnh cho Windows nhưng chưa chạy trên Windows trong môi trường bàn giao.

## Giới hạn cần đọc

Đây là đánh giá quy tắc cố định trên lịch sử, chưa phải kiểm định ngoài mẫu độc lập. Không huấn luyện mô hình hay tối ưu tham số. Xem kết quả rồi thay ngưỡng nhiều lần có thể gây overfitting. Việc chia 4 giai đoạn không tự biến toàn bộ dữ liệu thành tập ngoài mẫu.

Khoảng Wilson 95% mô tả tỷ lệ thắng mẫu dưới giả định thống kê; quan sát thị trường có thể phụ thuộc dù cửa sổ không chồng lấn. Không dùng khoảng này làm xác suất thắng của giao dịch sắp tới.

Kỳ giữ tính theo bản ghi: nếu thiếu phiên thì thời gian thực tế có thể dài hơn. Chưa xác minh lịch nghỉ lễ, danh sách niêm yết, nguồn giá hoặc điều chỉnh chia tách/cổ tức. Có thể có thiên lệch sống sót. Các dữ liệu có vẻ hợp lệ vẫn có thể làm sai kết quả nếu cơ sở giá chưa đúng.

Database đi kèm là dữ liệu bạn đã gửi, ngày giá mới nhất 21/10/2026. Bản này không cập nhật thêm dữ liệu giá và không cam kết dự báo chính xác hơn.

Đây là phân tích thuật toán, không phải lời khuyên đầu tư.
