# Báo cáo kiểm chứng Phase 8 — 27/10/2026

## Kết luận

**Chưa đủ bằng chứng hiệu quả.** Chưa chứng minh dự báo chính xác hơn Phase 7 hoặc thắng VN-Index. Giao diện từ chối xác suất hiện tại và chặn replay thực tế thiếu dữ liệu. Không có dữ liệu giá/index giả được thêm vào database.

| Hạng mục | Kết quả thực đo |
|---|---|
| Toàn bộ pytest | 235 passed, 2 warnings, 30,50 giây |
| Phase 8 sau chỉnh mốc tuổi mô hình/registry | 47 passed, 1 warning, 2,52 giây |
| Chromium headless | Passed desktop1440×1000 và mobile390×844, không lỗi JS |
| Windows thật | Chưa kiểm thử; BAT chỉ được rà soát |
| Migration DB đầy đủ | Backup integrity ok, số dòng cũ không đổi, idempotent |
| Database nguyên bản trong ZIP | SHA-256 khớp Phase 7; chưa migration |
| Quét407 mã Phase7 / Phase8 cold app-cache | 20,889 / 2,837 giây |
| Phase8 cache đĩa | 2,193 giây; vẫn đọc/hash lịch sử |
| Benchmark mới tải | 0 dòng; provider không khả dụng |

Warnings pytest: deprecation Starlette/httpx và parser ngày ở test invalid_date cũ. Không có test failure. Lần đầu chạy tests không chỉ định database chứa giá đã thất bại vì repository mặc định rỗng; chạy lại đúng trên bản sao database kèm gói đạt kết quả ở trên. Không chạy tests ghi lên database nguồn.

## OOS thực tế

6 mã HPG/FPT/VNM/VCB/SSI/MWG; Logistic L2 C=1; horizon10; threshold0,55; expanding, embargo10; train1260/validation252/test252; eligibility20 dòng VALID và volume>0.

- 873 dòng OOS, **154 cụm ngày**, 181 tín hiệu chọn. Không coi 873 dòng hay154 cụm ngày là số mẫu hoàn toàn độc lập.
- Brier score: 0,26137. Đây là metric dự báo nhãn, chưa phải P&L thực thi.
- 98 dòng có volume tại thời điểm vào/ra bằng0; lợi suất nhãn không thể coi là giao dịch khớp được.
- Mốc cuối biết nhãn validation 12/09/2025; 288 phiên dữ liệu đã qua. Tất cả xác suất hiện tại bị từ chối, cả vì tuổi mô hình và thiếu dữ liệu nền.

| Đối chứng | Cụm ngày | Chênh lệch bình quân / nhãn | p đã điều chỉnh |
|---|---:|---:|---:|
| VN-Index | 0 | Không tính được | Không tính được |
| Mua các mã đủ điều kiện cùng cửa sổ | 48 | −0,6157 điểm % | 0,2118 |
| MA50, các ngày cả hai có vị thế | 42 | −1,1587 điểm % | 0,1798 |
| Hoán vị mã cùng tần suất/ngày | 26 | −1,1366 điểm % | 0,5115 |

Các chênh lệch trên **không phải lợi nhuận năm**, không phải NAV danh mục. Kết quả âm không bị che, nhưng dữ liệu và số cụm ngày chưa đủ để nâng thành kết luận “Bằng chứng ngược” theo gate đã công bố. VN-Index chưa có dữ liệu nên không tuyên bố thắng/thua thị trường.

CI95, fold boundaries/counts, calibration, strata, predictions và dòng quan sát nằm trong `validation_phase8/oos.json`. Bootstrap khối ngày1000 lần, seed7; p Bonferroni 4 phép so sánh × cấu hình/dataset đã ghi; CI95 mô tả chưa chỉnh multiple testing. Mua-giữ cùng mã báo riêng theo kỳ OOS, không dùng khác kỳ để suy ra alpha.

## Giới hạn còn lại

- Universe lịch sử, quyền, calendar và giá RAW chưa đủ; survivorship bias chưa giải quyết/định lượng. 5.323 sự kiện legacy không được tự coi là dữ liệu quyền đã xác nhận.
- Engine T+2/fees/ticks/volume/quyền đã test bằng fixture; chưa đối chiếu broker hoặc dữ liệu giao dịch thật. Chưa nối mô hình OOS vào engine end-to-end.
- Chưa có rulebook hiệu lực lịch sử, xử lý đổi mã/vị thế, recovery khi hủy niêm yết, quyền phức tạp/cash-in-lieu đầy đủ.
- Tốc độ đo ở máy Linux này, OS cache không xóa, không gồm network/startup/audit. Không cam kết mọi máy Windows đều <5 giây.
- So điểm407 mã có một thay đổi VSI50→37,5: bỏ điểm flow dương giả do sai số1,98e-14. Các chỉ báo số đối chiếu ở sai số ~1e-11 hoặc nhỏ hơn.

## Phase 9 ưu tiên

Nguồn licensed/vintage đầy đủ → model OOS nối execution engine và đối chứng cùng ràng buộc → rulebook/rights/delisting hoàn chỉnh → Windows CI và cache suffix. Không thêm giao diện hào nhoáng trước khi dữ liệu và bằng chứng đủ.

Đây là phân tích thuật toán, không phải lời khuyên đầu tư.
