# QTA Phase 4 — Nghiên cứu kỹ thuật và quản trị rủi ro

## Chạy trên máy mới

ZIP đã có database tại `data/state/qta_phase3_test.db`. Giải nén toàn bộ vào một thư mục mới. Mở PowerShell tại nơi chứa requirements.txt rồi chạy:

```powershell
python -m pip install -r requirements.txt
.\START_QTA.bat
```

Chờ audit hoàn tất và mở http://127.0.0.1:8000. Đừng đóng cửa sổ server. Máy mới chưa có tài khoản thì đăng ký ngay trên trang đăng nhập. Database tài khoản cũ không nằm trong bộ dữ liệu bạn đã gửi.

Sau đăng nhập, mở tab **Nghiên cứu & Rủi ro**. Dữ liệu giá đi kèm là bản bạn gửi, ngày giá mới nhất 21/10/2026; không tự trở thành dữ liệu hiện tại.

## Chức năng mới

1. Phân tích từng mã: MA20/50/200, RSI14, MACD 12/26/9, ATR14, volume so với 20 phiên trước, volume trung bình, vùng đỉnh/đáy 20 phiên trước. Hiển thị trạng thái xu hướng, lý do chấm điểm, cảnh báo và kịch bản có điều kiện.
2. Bộ quét: nhập danh sách hoặc quét tất cả mã có giá trong database; xử lý từng lô 30 mã, có tiến độ và dừng sau lô hiện tại. Sắp xếp điểm giảm dần, lọc volume trung bình 20 phiên. Mã lỗi vẫn xuất hiện để không che mất thiếu hụt dữ liệu. Đây là bộ lọc kỹ thuật/thanh khoản, chưa có lọc P/E, ROE hay báo cáo tài chính.
3. Công cụ khối lượng lệnh mua: giới hạn đồng thời ngân sách rủi ro và tỷ trọng, làm tròn theo lô 1/100; tính phí hai chiều, thuế bán giả định và trượt giá. Hiển thị R:R sau chi phí. Không đặt lệnh thực tế.

## Logic và cách hiểu

Điểm 0–100 là tổng trọng số quy tắc do thiết kế, chưa tối ưu theo dữ liệu hay hiệu chỉnh thành xác suất:

| Điều kiện | Điểm |
|---|---:|
| Close > MA20 | 20 |
| MA20 > MA50 | 20 |
| Close > MA200 | 15 |
| RSI từ 50 đến 70 | 15 |
| MACD histogram > 0 | 15 |
| Close vượt high của 20 phiên trước, volume >= 1,5 lần trung bình 20 phiên trước | 15 |

Các tiêu chí có tương quan; điểm cao không chứng minh lợi thế giao dịch. RSI >70 không tự động coi là bán. Chưa đủ 200 phiên thì tiêu chí MA200 không có điểm, không chuẩn hoá lại; cần cân nhắc điều này khi so sánh mã mới niêm yết.

MA dùng trung bình trượt. RSI và ATR dùng trung bình Wilder với seed số học; RSI chuỗi phẳng là 50, chuỗi chỉ tăng là 100. MACD dùng EMA adjust=False, có giai đoạn khởi tạo. Mốc đột phá và volume nền đều dịch một phiên để không tự đưa nến hiện tại vào mức so sánh. Dữ liệu ngày hôm nay luôn bị loại theo chính sách nến đóng hiện có, kể cả mở web sau phiên.

Dưới 60 nến không chấm điểm. Dữ liệu OHLCV/ngày không hợp lệ bị chặn. Cảnh báo dùng cửa sổ 120 phiên gần nhất, kèm chẩn đoán toàn lịch sử. Nhiều nguồn, volume 0, nhãn chưa xác minh và dữ liệu cũ được nêu rõ. REVIEW vẫn có điểm nghiên cứu nhưng không phải tín hiệu được phê duyệt. UNVERIFIED chỉ có nghĩa chưa phát hiện cảnh báo gần đây trong các kiểm tra đang có; không xác nhận giá đúng.

Vùng giá là high/low trượt đã quan sát, không phải swing được xác nhận hay mục tiêu chắc chắn. Turnover20 là close × volume trung bình theo đơn vị nguồn; không gọi là VND khi chưa kiểm chứng đơn vị giá. Chưa bổ sung thuật toán dự báo học máy hoặc thay đổi thuật toán swing/FVG cũ.

## Tính khối lượng

Nhập giá bằng đồng/cổ phiếu (21 nghìn đồng nhập 21000). Công cụ không tự lấy giá nguồn chưa kiểm chứng đơn vị. Vốn nên là phần vốn bạn dành cho kế hoạch này; công cụ không biết tiền mặt khả dụng, vị thế đang giữ, tương quan danh mục hoặc nghĩa vụ thanh toán.

- Chi phí mua mỗi cổ phiếu = entry × (1 + trượt giá) × (1 + phí).
- Thu hồi tại stop = stop × (1 − trượt giá) × (1 − phí − thuế bán).
- Rủi ro mỗi cổ phiếu = chi phí mua − thu hồi tại stop.
- Số cổ phiếu = làm tròn xuống theo lô của min(ngân sách rủi ro / rủi ro mỗi cổ phiếu, hạn mức tỷ trọng / chi phí mua).

Giới hạn nhập rủi ro mỗi lệnh 0–5% (không gồm 0). Các phí/thuế là giả định có thể sửa, không phải xác nhận biểu phí hay quy định hiện hành. Stop không được bảo đảm thực hiện: gap, giá sàn, thanh khoản hoặc hạn chế bán có thể làm lỗ thực tế lớn hơn.

## Kiểm chứng

- 84 kiểm thử liên quan nghiên cứu, chất lượng dữ liệu, API, phục hồi và đăng nhập đã đạt; sau đó bổ sung kiểm tra yêu cầu đăng nhập cho 3 API mới và chạy lại nhóm nghiên cứu: 11 kiểm thử đạt. Tổng 85 trường hợp đã được chạy thành công qua các lượt này.
- Kiểm tra chỉ báo tại một thời điểm không đổi khi thêm hoặc sửa dữ liệu phía sau (chống look-ahead).
- Kiểm tra chuỗi giá phẳng/tăng, điều kiện breakout, mức phí, khối lượng theo lô, giới hạn rủi ro và trường hợp vốn quá nhỏ.
- Chạy phân tích và kiểm tra JSON hữu hạn trên 407 mã có giá: không có exception, 403 REVIEW, 2 UNVERIFIED, 2 INSUFFICIENT_DATA tại thời điểm chạy. Chi tiết trong `phase4_validation.json`. Đây là kiểm tra vận hành, không phải kiểm chứng độ đúng của giá hoặc hiệu suất đầu tư.
- JavaScript đã qua kiểm tra cú pháp. Chưa kiểm thử thao tác trực tiếp trên trình duyệt hoặc launcher trên Windows.
- Chưa đối chiếu nguồn độc lập, chưa backtest ngoài mẫu để chứng minh bộ điểm mới cải thiện lợi nhuận. Không có tỷ lệ thắng được khẳng định.

Đây là phân tích thuật toán, không phải lời khuyên đầu tư.
