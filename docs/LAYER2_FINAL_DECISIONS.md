# Layer 2 — Bảng quyết định cuối D01–D12

Ngày chốt: 04/11/2026 (Asia/Bangkok).

**Trạng thái bàn giao: Layer 2 hoàn thành theo xác nhận của owner sau Phase 5.**
Baseline nghiên cứu giữ nguyên hành vi đã kiểm thử. D08 và D10 chuyển sang Layer 3 để quyết; không cản trở việc đóng Layer 2 trong phạm vi đã thống nhất.

Tài liệu này là trạng thái quyết định cuối, thay thế trạng thái chờ duyệt trong các báo cáo/decision log của từng Phase. Các tài liệu và log cũ được giữ nguyên làm lịch sử, không sửa hồi tố kết quả kiểm thử.

| Quyết định | Trạng thái | Nội dung chốt | Lý do và giới hạn còn giữ |
|---|---|---|---|
| D01 | APPROVED | D01-B: cấu trúc không dùng lại leg; được chung swing ở biên. | Giữ cách chọn baseline đã duyệt. Kiểm tra chồng lấn Phase 5 tạo 83 cấu trúc từng CONFIRMED nhưng vẫn chỉ 1 INTERNAL; mẫu hiện tại chưa ủng hộ việc quy hiếm INTERNAL chủ yếu cho D01-B. Không tự thay baseline. |
| D02 | APPROVED | D02-A: UP cần strict HH + HL; DOWN cần strict LH + LL, theo tolerance D05. Cấu trúc vi phạm protected level ngay tại available_at không được CONFIRMED; giữ trong lịch sử với reason `PROTECTED_LEVEL_VIOLATED_AT_AVAILABILITY`. | D05 đã được duyệt giữ CURRENT nên tiếp tục D02-A trên đúng tolerance đã kiểm thử, không thay điều kiện hay bổ sung ứng viên để bù mẫu bị loại. Khi thử tolerance khác trong tương lai, phải xem lại tương tác với D02. |
| D03 | APPROVED | D03-A: cấu trúc hoàn chỉnh gồm 4 swing / 3 leg. | Giữ định nghĩa hình học đã duyệt, phân biệt với FORMING ba swing ở D12. |
| D04 | APPROVED | Ngưỡng 3.0 ATR chỉ để phân loại: đạt ngưỡng là MAJOR, không đạt là INTERNAL; không chặn confirmation. | Baseline có 63 MAJOR / 1 INTERNAL trên 64 cấu trúc từng CONFIRMED; ngưỡng 2.5 ATR cho 64 / 0. Bộ lọc hiện ít phân biệt; giữ ghi chú này, không suy rộng từ mẫu nhỏ. |
| D05 | APPROVED | Giữ tolerance hiện tại cho baseline nghiên cứu: `max(1 VND, 0.0001 × current_price)`. | Owner phê duyệt sau so sánh Phase 5. Phương án 0,1% giá không đổi số lượng trong mẫu. Một tick quy đổi giữ làm biến thể nghiên cứu, chờ hệ số điều chỉnh được xác minh; số liệu proxy không được coi là kết quả verified hay lý do tự đổi mặc định. |
| D06 | APPROVED | D06-A: protected level cố định tại pivot hồi của cấu trúc. | Giữ baseline đã duyệt. D06-C (buffer 0.5 ATR tại pivot hồi) đã thử riêng trong Phase 5, giữ là biến thể; giảm BROKEN không tự chứng minh quy tắc tốt hơn. |
| D07 | APPROVED | D07-A: một Close vượt strict protected level xác định break. | Giữ baseline đã duyệt. D07-C (hai Close liên tiếp) đã thử riêng và giữ là biến thể; có tác động trì hoãn break. Birth guard vẫn không cho CONFIRMED nếu đã vi phạm tại available_at. |
| D08 | DEFERRED | Giữ hai chế độ truy vấn riêng: hai cấu trúc từng CONFIRMED gần nhất (`EVER_CONFIRMED`) và hai cấu trúc còn active gần nhất (`ACTIVE`); chưa chọn mặc định. | Chờ Layer 3 quyết theo nhu cầu sử dụng context. Bên gọi phải chỉ rõ mode, không trộn hai ý nghĩa. Chuỗi Major giữ cả UP và DOWN. |
| D09 | APPROVED | Quarantine dữ liệu không hợp lệ; giữ audit, không ngầm thay lịch sử. | Bảo toàn tính truy vết và hành vi đã duyệt. Việc đóng Layer 2 không đồng nghĩa đã hoàn thiện mọi quy trình sửa/rebuild dữ liệu live. |
| D10 | DEFERRED | `is_long_candidate = NULL` và reason `LONG_CONTEXT_NOT_EVALUATED`. | Long-context thuộc quyết định Layer 3. Layer 2 chưa gán tín hiệu Long và chưa đánh giá hiệu quả giao dịch. |
| D11 | APPROVED | Các quy tắc hiện dùng được ghi nhận là giả thuyết kỹ thuật của dự án. | Owner đã duyệt quy ước nghiên cứu; không khẳng định đây là phương pháp gốc đã được xác minh hoặc tự gán nguồn tác giả. |
| D12 | APPROVED | FORMING: ba swing đầu cho thấy HL/LH; swing thứ tư quyết định cấu trúc hoàn chỉnh. | Quy ước được owner chấp nhận sau Phase 3 và ghi nhận là giả thuyết kỹ thuật của dự án; giữ nguyên trong baseline. |

## Cơ sở nghiệm thu và phạm vi bằng chứng

- Phase 5: 154/154 test đạt, 0 failures, 0 errors, 0 skipped; có TC15, TC16, TC17. Log nguyên văn giữ trong `LAYER2_PHASE5_TEST_LOG.txt`.
- Mẫu: HPG, FPT, VNM, VCB, SSI; 65 cửa sổ đạt hình học, một trường hợp pre-broken bị giữ UNCLEAR, còn 64 cấu trúc từng CONFIRMED; 44 BROKEN (68,75%).
- TC15 chứng minh hành vi thuật toán trên snapshot cố định đang kiểm thử; chưa chứng minh dữ liệu hồi tố là dữ liệu lịch sử as-received. Biến thể tick dùng hệ số proxy chưa verified, không nâng cấp kết luận này khi đóng Layer 2.
- Chưa mở rộng universe vì thiếu cặp OHLCV 15 phút và swing Layer 1 tương ứng. Không kết luận hiệu quả chiến lược hoặc khả năng khái quát qua nhiều chế độ thị trường.
- Lần đóng gói cuối chỉ bổ sung tài liệu quyết định này. Mã nguồn, cấu hình thực thi, database, báo cáo và log Phase 5 giữ nguyên; không chạy lại hay gán một lượt test mới cho thay đổi tài liệu.

## Bàn giao sang Layer 3

D08 và D10 là hai quyết định còn DEFERRED. Biến thể tick quy đổi tiếp tục chờ xác minh hệ số điều chỉnh; D06-C/D07-C vẫn là biến thể nghiên cứu, không phải mặc định. Layer 3 chưa được triển khai trong gói này.
