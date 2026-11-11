# PHẦN A — LỆNH CHO AI (đọc phần này trước, rồi đọc PHẦN B là tài liệu đặc tả Layer 3)

Triển khai LAYER 3 (Reversal Setup Detector) theo tài liệu "TÀI LIỆU ĐẶC TẢ TRIỂN KHAI LAYER 3" phiên bản 1.0, dự án NCKH-BIGDATA-STOCK-2026. Toàn văn tài liệu nằm ở PHẦN B của file này. Lưu một bản sao PHẦN B vào docs/SPEC_LAYER3_v1.0.md trong dự án.

BỐI CẢNH HIỆN TẠI
- Layer 1 (swing) và Layer 2 (Market Structure Builder) đã hoàn thành. Bản chốt nằm trong QTA_LAYER2_FINAL_FULL.zip, quyết định Layer 2 nằm ở docs/LAYER2_FINAL_DECISIONS.md.
- Layer 2 xuất chuỗi Major Structure (giữ cả UP và DOWN), hai chế độ truy vấn riêng biệt EVER_CONFIRMED và ACTIVE (D08 chưa chọn mặc định), và is_long_candidate = NULL (D10 chưa quyết). Layer 3 sẽ là nơi quyết hai việc này (xem mục "QUYẾT ĐỊNH CẦN DUYỆT").
- Layer 3 là module MỚI, độc lập, đặt trong thư mục riêng. KHÔNG sửa code Layer 1/Layer 2, KHÔNG sửa database gốc. Khi đóng gói phải đối chiếu hash để chứng minh các file gốc giữ nguyên byte.
- Layer 3 chỉ PHÁT HIỆN SETUP. Không đặt lệnh, không giá khớp, không FVG, không Stop Loss/Take Profit, không thêm bộ lọc volume/RSI/MA (xem mục 15 của tài liệu).

QUY TRÌNH LÀM VIỆC
Tài liệu không chia phase, hãy làm theo 5 phase dưới đây. Hết mỗi phase: chạy test, ĐÓNG GÓI NGAY thành ZIP kèm file LAYER3_PHASEn_TEST_LOG.txt (log thật, không tóm tắt bằng lời), báo cáo ngắn rồi DỪNG chờ tôi duyệt mới làm phase tiếp.
- Phase 1 — Nến và mô hình ba nến đỏ: kiểm tra dữ liệu nến, công thức body/wick, nhận diện đỏ/xanh/doji, bộ ba R1-R2-R3 liên tiếp, phát hiện khoảng trống dữ liệu. Test AT01–AT07, AT21.
- Phase 2 — Bối cảnh Layer 2: đọc đầu ra Layer 2 theo thời điểm T (chỉ available_at <= T), chọn hai Major liền kề gần nhất, kiểm tra DOWN + CONFIRMED + chưa BROKEN tại T. Test AT08, AT09. Báo cáo "phễu" (funnel): bao nhiêu thời điểm có bối cảnh hợp lệ.
- Phase 3 — Cửa sổ nến xanh và vòng đời: WAITING_REVERSAL / FOUND / EXPIRED / INVALIDATED, quy tắc 5 nến, tỷ lệ thân 1.0–2.0 (inclusive), thứ tự xử lý ở bước 4 mục 11. Test AT10–AT18.
- Phase 4 — Lưu trữ và đầu ra: bảng reversal_setup, reversal_setup_event, đầu ra LONG_SETUP, idempotency (khóa chống trùng mục 8), reason code, log và metrics mục 13, cấu hình có rule_version mục 14. Test AT19, AT20, AT22.
- Phase 5 — Kiểm chứng: point-in-time replay trên 5 mã (HPG, FPT, VNM, VCB, SSI) và toàn bộ dữ liệu 15 phút hiện có; so sánh chạy từng nến với chạy batch; chạy lại hai lần kiểm tra không trùng; báo cáo phễu đầy đủ (nến → bộ ba đỏ hợp lệ → có bối cảnh → candidate → FOUND/EXPIRED/INVALIDATED); bảng quyết định cuối; chứng minh truy vết mỗi LONG_SETUP đến hai cấu trúc và bốn nến (R1, R2, R3, G).

QUYẾT ĐỊNH CẦN DUYỆT (đừng tự chốt âm thầm; triển khai thành tham số cấu hình, ghi trạng thái PROPOSED, cuối mỗi phase liệt kê để tôi duyệt)
- L3-D01 (tương ứng D08 của Layer 2): chọn hai cấu trúc bối cảnh bằng cách nào. Đề xuất: lấy hai Major liền kề gần nhất theo chuỗi EVER_CONFIRMED (không nhảy qua cấu trúc nào), sau đó kiểm tra trạng thái của từng cấu trúc TẠI THỜI ĐIỂM T phải là CONFIRMED (không BROKEN) và hướng DOWN. Không dùng chế độ ACTIVE nếu nó bỏ qua cấu trúc BROKEN để chọn hai cấu trúc cũ hơn, vì tài liệu cấm bỏ qua cấu trúc MAJOR ở giữa. Hãy kiểm tra cách chế độ ACTIVE của Layer 2 xử lý cấu trúc BROKEN và báo cho tôi.
- L3-D02 (tương ứng D10 của Layer 2): Layer 3 sở hữu logic Long-context. Layer 2 giữ is_long_candidate = NULL với LONG_CONTEXT_NOT_EVALUATED, không sửa.
- L3-D03: quy ước timestamp nến và available_at. Đề xuất thống nhất với Layer 1 (cách Layer 1 đặt extreme_time và confirmed_at). Nêu rõ candle_time là thời điểm bắt đầu hay kết thúc nến và available_at = ? (ví dụ thời điểm đóng nến). Ghi vào cấu hình.
- L3-D04: "liên tiếp" có tính xuyên phiên không (nghỉ trưa 11:30–13:00, qua đêm, phiên ATO/ATC). Tài liệu chỉ cấm khoảng trống dữ liệu thiếu nến so với lịch giao dịch chuẩn hóa. Hãy triển khai theo đúng chữ của tài liệu (nến liền nhau trong chuỗi nến hợp lệ), thêm tham số allow_cross_session_sequences, và báo cáo bao nhiêu bộ ba R1-R3 và cửa sổ 5 nến vắt qua ranh giới phiên để tôi quyết. Không tự đổi hành vi.
- L3-D05: tài liệu không giới hạn "độ cũ" của bối cảnh (hai cấu trúc DOWN có thể kết thúc từ lâu). V1 không giới hạn, nhưng hãy lưu thêm số nến từ lúc cấu trúc thứ hai kết thúc đến R3 (context_age_bars) trong output để nghiên cứu sau; KHÔNG dùng nó làm bộ lọc.

NGUYÊN TẮC CHẤT LƯỢNG
- Không look-ahead: tại thời điểm T chỉ dùng nến đã đóng và available, và cấu trúc có available_at <= T. Có test chứng minh thêm nến/cấu trúc tương lai không làm đổi kết quả đã biết.
- Mọi quy tắc nằm trong cấu hình có rule_version (L3_REVERSAL_V1), không hard-code rải rác. Biến thể kiểm thử phải là rule_version mới, không thay đổi kết quả V1.
- Viết test riêng cho từng AT01–AT22; tôi muốn thấy bảng AT → tên test → đạt/không đạt trong báo cáo.
- Không đánh giá lợi nhuận hay hiệu quả chiến lược (tài liệu mục 13 nói rõ). Số FOUND chỉ là thống kê tín hiệu.
- Nếu số setup rất ít (có thể chỉ vài cái, vì cần hai cấu trúc DOWN liền kề rồi mới ba nến đỏ và nến xanh), hãy nói thẳng con số và nêu rõ giới hạn của mẫu; đừng kết luận gì về chất lượng mô hình.
- Không khẳng định đây là phương pháp gốc của Gianluca Bruni; ghi là baseline của dự án như tài liệu đã nêu.

BÁO CÁO CUỐI MỖI PHASE
File thêm/sửa, số test đạt/không đạt (log thật), AT nào đã phủ, phần chưa làm, quyết định L3-D01…D05 cần duyệt, và xác nhận các file Layer 1/Layer 2 gốc giữ nguyên byte.

---

# PHẦN B — TÀI LIỆU ĐẶC TẢ LAYER 3 v1.0 (nguyên văn)

```
TÀI LIỆU ĐẶC TẢ TRIỂN KHAI LAYER 3
HỆ THỐNG BACKTEST MÔ HÌNH ĐẢO CHIỀU – THỊ TRƯỜNG CHỨNG KHOÁN VIỆT NAM

Mã dự án: NCKH-BIGDATA-STOCK-2026
Tên module: Layer 3 – Reversal Setup Detector
Phiên bản: 1.0
Trạng thái: Đặc tả triển khai bản cơ sở (baseline)

============================================================
1. MỤC TIÊU
============================================================

Layer 3 sử dụng đầu ra Layer 2 để phát hiện setup mua (LONG_SETUP) dựa trên:
- Hai cấu trúc Major liền kề gần nhất đều là cấu trúc giảm đã CONFIRMED.
- Sau đó xuất hiện 3 nến đỏ liên tiếp thỏa điều kiện hình thái.
- Trong tối đa 5 nến tiếp theo sau nến đỏ số 3, xuất hiện nến xanh có thân lớn gấp 1–2 lần thân nến đỏ số 3.

Layer 3 chỉ phát hiện setup. Không thực hiện đặt lệnh, không xác định giá khớp lệnh, FVG, Stop Loss hoặc Take Profit trong phiên bản này.

LƯU Ý VỀ PHƯƠNG PHÁP:
Các quy tắc trong tài liệu là baseline được thống nhất để triển khai và kiểm định theo yêu cầu dự án. Chưa khẳng định đây là bản sao chính xác toàn bộ phương pháp gốc của Gianluca Bruni. Mọi quy tắc cần được thay đổi phải quản lý bằng rule_version/config, không sửa âm thầm trong code.

============================================================
2. PHẠM VI VÀ NGUYÊN TẮC
============================================================

2.1. Phạm vi
- Đầu vào: dữ liệu nến OHLCV và kết quả cấu trúc thị trường từ Layer 2.
- Đầu ra: lịch sử setup, trạng thái setup và lý do tạo/hủy setup.
- Thị trường: cổ phiếu Việt Nam, chỉ tìm cơ hội LONG.
- Timeframe mặc định: timeframe đang được Layer 1/Layer 2 sử dụng (hiện tại dự án dùng 15 phút). Không hard-code timeframe vào logic; lấy từ cấu hình.

2.2. Nguyên tắc bắt buộc
- Không look-ahead bias: tại thời điểm xử lý T chỉ sử dụng dữ liệu đã có thể biết tại T.
- Thứ tự nến theo thời gian tăng dần; một ticker/timeframe không được có hai nến cùng timestamp.
- Dùng giá OHLC đã được chuẩn hóa từ pipeline trước đó.
- Mỗi setup phải truy vết được đến hai cấu trúc Layer 2 và các nến cấu thành.
- Tách điều kiện bối cảnh, điều kiện mô hình và trạng thái vòng đời setup.
- Không tự thêm bộ lọc như volume, FVG, RSI, MA, vượt đỉnh hoặc ATR vào điều kiện baseline nếu chưa được phê duyệt.
- Xử lý idempotent: chạy lại cùng dữ liệu và cùng rule_version không tạo setup trùng lặp.

============================================================
3. ĐẦU VÀO
============================================================

3.1. Dữ liệu nến OHLCV
Các trường tối thiểu:
- ticker
- timeframe
- candle_time (thời điểm bắt đầu hoặc timestamp chuẩn của nến; thống nhất toàn hệ thống)
- open
- high
- low
- close
- volume
- available_at (thời điểm dữ liệu nến có thể được hệ thống sử dụng; nếu pipeline hiện tại không lưu trường này, cần xác định thời điểm tương đương)

Điều kiện hợp lệ cơ bản:
- ticker, timeframe, candle_time không NULL.
- open/high/low/close không NULL và > 0.
- high >= greatest(open, close).
- low <= least(open, close).
- high >= low.
- volume >= 0.
Nến lỗi phải bị loại hoặc đánh dấu invalid theo quy ước pipeline; không tự sửa trong Layer 3 nếu chưa có chính sách chuẩn hóa chung.

3.2. Đầu vào Layer 2
Layer 3 cần nhận được tối thiểu:
- structure_id
- ticker
- timeframe
- structure_sequence hoặc trường xác định thứ tự cấu trúc
- structure_direction: UP / DOWN / UNCLEAR
- structure_status: FORMING / CONFIRMED / BROKEN / UNCLEAR
- classification: MAJOR / INTERNAL / UNCLASSIFIED
- start_time
- end_time
- available_at (thời điểm cấu trúc được phép sử dụng)
- rule_version

Layer 3 chỉ dùng cấu trúc MAJOR, CONFIRMED, không bị BROKEN/UNCLEAR, với available_at <= thời điểm đang xử lý.

============================================================
4. ĐIỀU KIỆN BỐI CẢNH ĐƯỢC PHÉP TÌM SETUP
============================================================

Tại thời điểm bắt đầu đánh giá một setup:
1. Lấy hai cấu trúc MAJOR liền kề gần nhất theo thứ tự thời gian/sequence đã được Layer 2 xác định.
2. Không bỏ qua cấu trúc MAJOR ở giữa để chọn hai cấu trúc thuận lợi hơn.
3. Cả hai phải:
   - classification = MAJOR
   - structure_status = CONFIRMED
   - structure_direction = DOWN
   - available_at <= thời điểm xử lý
4. Nếu không đáp ứng đầy đủ, không khởi tạo setup mới.
5. Lưu ID của cả hai cấu trúc vào setup để truy vết.

Định nghĩa "liền kề":
Hai cấu trúc là hai bản ghi liền nhau trong chuỗi cấu trúc MAJOR do Layer 2 xuất ra, sau khi loại các bản ghi không được phân loại MAJOR. Không được tự ý bỏ qua một cấu trúc MAJOR hợp lệ chỉ vì nó không phù hợp điều kiện DOWN.

Cập nhật bối cảnh:
- Bối cảnh được kiểm tra tại thời điểm mô hình 3 nến đỏ hoàn tất.
- Hai cấu trúc dùng làm bối cảnh phải có hiệu lực tại thời điểm đó.
- Nếu một trong hai cấu trúc bị Layer 2 đánh dấu BROKEN/không còn hợp lệ trước thời điểm nến đỏ số 3 hoàn tất, không tạo setup từ bối cảnh đó.
- Nếu Layer 2 phát sinh cấu trúc mới sau khi mô hình đã bắt đầu, áp dụng chính sách phiên bản 1.0: đánh giá lại bối cảnh tại thời điểm nến đỏ số 3 hoàn tất; không hồi tố sử dụng thông tin chỉ được xác nhận sau thời điểm này.

============================================================
5. ĐỊNH NGHĨA NẾN VÀ CÔNG THỨC
============================================================

Với mỗi nến:
- body = abs(close - open)
- upper_wick = high - max(open, close)
- lower_wick = min(open, close) - low
- total_wick = upper_wick + lower_wick

Nến đỏ:
- close < open

Nến xanh:
- close > open

Nến doji:
- close = open
- Không được tính là nến đỏ hoặc nến xanh.

Nến đỏ mạnh theo yêu cầu baseline:
- body > total_wick
- So sánh nghiêm ngặt ">", không dùng ">=".

============================================================
6. ĐIỀU KIỆN MÔ HÌNH
============================================================

6.1. Ba nến đỏ liên tiếp
Tìm ba nến liên tiếp R1, R2, R3 của cùng ticker/timeframe:

R1:
- close < open
- body1 > upper_wick1 + lower_wick1

R2:
- close < open
- Không yêu cầu tỷ lệ thân/râu.

R3:
- close < open
- body3 > upper_wick3 + lower_wick3

"Liên tiếp" nghĩa là ba nến hợp lệ liền nhau trong chuỗi nến của ticker/timeframe. Không được bỏ qua một nến xanh, doji hoặc nến invalid để ghép thành bộ ba. Nếu thiếu dữ liệu giữa chuỗi, không xem hai nến hai bên khoảng trống là liên tiếp.

Tại thời điểm R3 đóng cửa và dữ liệu R3 đã available:
- Đánh giá bối cảnh Layer 2.
- Nếu bối cảnh hợp lệ, tạo một candidate setup ở trạng thái WAITING_REVERSAL.
- Lưu thời điểm và OHLC của R1/R2/R3.
- Bắt đầu cửa sổ tìm nến xanh từ 5 nến kế tiếp sau R3; không tính R3 vào giới hạn 5 nến.

6.2. Nến xanh đảo chiều
Sau R3, kiểm tra tối đa 5 nến kế tiếp theo thứ tự thời gian. Nến xanh G đạt tiêu chuẩn khi:
- close_G > open_G
- body_G > 0
- 1.0 <= body_G / body3 <= 2.0

Hai biên 1.0 và 2.0 được chấp nhận (inclusive).
Không bắt buộc G là nến ngay sau R3.
Không yêu cầu G phải đóng cửa vượt high của R3 trong baseline v1.0.
Không yêu cầu G phải vượt đỉnh cấu trúc giảm trong baseline v1.0.

6.3. Khi tìm được nến xanh đạt chuẩn
- Chuyển setup sang FOUND.
- Ghi reversal_candle_time, reversal candle OHLC, body_ratio.
- Ghi found_at/available_at bằng thời điểm nến G đóng cửa và dữ liệu nến G thực sự sẵn sàng.
- Không tạo nhiều setup FOUND cho cùng một candidate; chỉ nến xanh đầu tiên đạt điều kiện được chọn.
- Sau khi FOUND, kết thúc việc tìm kiếm nến xanh cho candidate đó.

6.4. Khi hết cửa sổ
- Nếu cả 5 nến kế tiếp đã hoàn tất mà không có nến xanh đạt chuẩn, chuyển trạng thái EXPIRED.
- Ghi reason_code = REVERSAL_NOT_FOUND_WITHIN_WINDOW.
- Không kéo dài cửa sổ quá 5 nến.

============================================================
7. QUY TẮC DỪNG / VÔ HIỆU HÓA
============================================================

Baseline v1.0:
- Không dừng tìm kiếm chỉ vì một swing mới được xác nhận.
- Không yêu cầu giá vượt đỉnh cấu trúc hiện tại.
- Không hủy setup chỉ vì giá vượt đỉnh cấu trúc; điều kiện này được lưu/kiểm định trong phiên bản thử nghiệm sau nếu cần.
- Setup kết thúc bằng một trong các trạng thái FOUND, EXPIRED hoặc INVALIDATED.

INVALIDATED được dùng khi có sự kiện dữ liệu/bối cảnh rõ ràng khiến setup không còn hợp lệ, ví dụ:
- Layer 2 thông báo một trong hai cấu trúc bối cảnh bị BROKEN trước thời điểm reversal candle được xác nhận.
- Dữ liệu đầu vào bị sửa/thu hồi làm bộ nến không còn hợp lệ.
- Một khoảng trống dữ liệu khiến không thể xác nhận cửa sổ 5 nến liên tiếp theo quy tắc dữ liệu.

Nếu hệ thống chạy lịch sử và Layer 2 có khả năng cập nhật lại cấu trúc:
- Không ghi đè âm thầm kết quả cũ.
- Ghi event/version mới, lý do invalidation và thời điểm sự kiện được hệ thống biết.
- Tách rõ "trạng thái theo thông tin biết tại thời điểm đó" và "trạng thái đã được tái tính sau khi dữ liệu sửa đổi".

Lưu ý: "Swing vượt đỉnh cấu trúc" chưa phải điều kiện hủy trong baseline. Hãy lưu thông tin sự kiện nếu có để phục vụ nghiên cứu, không dùng làm bộ lọc chính thức ở phiên bản này.

============================================================
8. QUẢN LÝ NHIỀU SETUP
============================================================

- Cho phép các candidate setup của cùng ticker có thể chồng lấn nếu chúng xuất phát từ các bộ ba nến đỏ khác nhau.
- Tuy nhiên, cùng một bộ ba R1/R2/R3 chỉ được tạo một candidate setup.
- Khóa chống trùng đề xuất:
  ticker + timeframe + red_candle_1_time + red_candle_2_time + red_candle_3_time + rule_version.
- Nếu hai bộ ba dùng chung một hoặc hai nến nhưng có timestamp R1 khác nhau, có thể là hai candidate khác nhau; không tự loại nếu chưa có quy tắc riêng.
- Lưu cấu hình max_wait_candles = 5; body_ratio_min = 1.0; body_ratio_max = 2.0 trong cấu hình có version.

============================================================
9. OUTPUT / DATA CONTRACT
============================================================

9.1. Bảng reversal_setup
Các trường đề xuất:
- setup_id (PK)
- ticker
- timeframe
- rule_version
- context_structure_id_1
- context_structure_id_2
- context_available_at
- red_candle_1_time
- red_candle_1_open/high/low/close
- red_candle_2_time
- red_candle_2_open/high/low/close
- red_candle_3_time
- red_candle_3_open/high/low/close
- body_1, total_wick_1
- body_3, total_wick_3
- status: WAITING_REVERSAL / FOUND / EXPIRED / INVALIDATED
- reversal_candle_time (nullable)
- reversal_candle_open/high/low/close (nullable)
- reversal_body (nullable)
- body_ratio (nullable)
- setup_detected_at
- available_at
- reason_code
- created_at
- updated_at

Có thể tách OHLCV chi tiết sang bảng con nếu thiết kế warehouse hiện tại yêu cầu chuẩn hóa. Đây là contract logic, không bắt buộc dùng đúng một bảng vật lý.

9.2. Bảng reversal_setup_event (khuyến nghị)
- event_id
- setup_id
- event_type: CREATED / REVERSAL_FOUND / EXPIRED / INVALIDATED / RECOMPUTED
- event_time
- available_at
- reason_code
- event_payload (JSON)
- rule_version

9.3. Output logic cho downstream
Khi status = FOUND, xuất một LONG_SETUP với:
- ticker
- timeframe
- setup_id
- signal_time = reversal_candle_time
- signal_available_at = thời điểm nến xanh đã đóng và dữ liệu đã sẵn sàng
- context_structure_id_1/2
- red_candle_1/2/3_time
- reversal_candle_time
- body_ratio
- rule_version
- reason_code = REVERSAL_PATTERN_FOUND

FOUND không đồng nghĩa đã khớp lệnh. Layer 4/backtest engine quyết định thời điểm vào lệnh và giá khớp theo chính sách thực thi, thường không được giả định mua tại giá đóng cửa của nến tín hiệu nếu chỉ biết tín hiệu sau khi nến đóng.

============================================================
10. REASON CODE
============================================================

Bối cảnh:
- CONTEXT_TWO_ADJACENT_MAJOR_DOWNS_CONFIRMED
- CONTEXT_NOT_ENOUGH_MAJOR_STRUCTURES
- CONTEXT_NOT_TWO_ADJACENT_DOWNS
- CONTEXT_STRUCTURE_NOT_AVAILABLE_YET
- CONTEXT_STRUCTURE_BROKEN

Mô hình:
- THREE_RED_CANDLE_PATTERN_FOUND
- REVERSAL_CANDLE_FOUND
- REVERSAL_NOT_FOUND_WITHIN_WINDOW
- REVERSAL_BODY_RATIO_TOO_SMALL
- REVERSAL_BODY_RATIO_TOO_LARGE
- INVALID_CANDLE_DATA
- DATA_GAP_IN_CANDLE_SEQUENCE

Vòng đời:
- SETUP_CREATED
- SETUP_EXPIRED
- SETUP_INVALIDATED
- SETUP_RECOMPUTED

Có thể ghi thêm các reason code cho các điều kiện không đạt trong log debug; không nhất thiết lưu mọi nến bị loại vào bảng chính.

============================================================
11. THUẬT TOÁN XỬ LÝ ĐỀ XUẤT
============================================================

Với từng ticker/timeframe:
1. Đọc nến theo candle_time tăng dần.
2. Kiểm tra dữ liệu hợp lệ và phát hiện khoảng trống nến theo lịch giao dịch đã chuẩn hóa.
3. Đọc các sự kiện/bản ghi Layer 2 có available_at <= thời điểm xử lý.
4. Với mỗi nến đóng:
   a. Cập nhật candidate đang WAITING_REVERSAL:
      - Nếu đã có đủ dữ liệu của nến kế tiếp thứ 1..5, kiểm tra nến hiện tại có phải nến xanh đạt tỷ lệ body hay không.
      - Nếu đạt: FOUND, lưu nến đầu tiên đạt điều kiện.
      - Nếu không đạt và đã là nến thứ 5: EXPIRED.
      - Trước khi tìm nến đảo chiều, kiểm tra setup còn hợp lệ theo thông tin Layer 2 đã biết tại thời điểm đó.
   b. Kiểm tra bộ ba nến gần nhất (n-2, n-1, n):
      - Nếu thỏa R1/R2/R3, kiểm tra hai cấu trúc Major liền kề gần nhất tại thời điểm nến n đóng.
      - Nếu bối cảnh hợp lệ, tạo candidate WAITING_REVERSAL.
   c. Đảm bảo không tạo candidate trùng theo khóa idempotency.
5. Ghi trạng thái và event bằng transaction/upsert.
6. Xuất LONG_SETUP khi candidate chuyển sang FOUND.
7. Ghi log số nến xử lý, số candidate tạo, FOUND, EXPIRED, INVALIDATED, dữ liệu lỗi.

Thứ tự ở bước 4 cần triển khai nhất quán: cập nhật các candidate đã tồn tại trước, sau đó tạo candidate mới từ bộ ba kết thúc ở nến hiện tại. Nến hiện tại không được đồng thời tính là nến đầu tiên trong cửa sổ 5 nến của chính candidate vừa tạo.

============================================================
12. ACCEPTANCE TESTS
============================================================

AT01 – Nến đỏ:
close < open => nhận diện nến đỏ.

AT02 – Nến xanh:
close > open => nhận diện nến xanh.

AT03 – Doji:
close = open => không được xem là đỏ hoặc xanh.

AT04 – Nến đỏ số 1 mạnh:
body1 > total_wick1 => đạt; bằng hoặc nhỏ hơn => không đạt.

AT05 – Nến đỏ số 2:
chỉ cần close2 < open2; không cần body2 > total_wick2.

AT06 – Nến đỏ số 3 mạnh:
body3 > total_wick3 => đạt; bằng hoặc nhỏ hơn => không đạt.

AT07 – Ba nến liên tiếp:
R1/R2/R3 liên tiếp đều đạt => tiếp tục kiểm tra context.
Nếu nến giữa là xanh/doji/invalid => không ghép thành bộ ba.

AT08 – Context hợp lệ:
hai Major liền kề gần nhất đều DOWN + CONFIRMED + available => được tạo candidate.

AT09 – Context không hợp lệ:
một cấu trúc UP/UNCLEAR/FORMING/BROKEN hoặc thiếu cấu trúc => không tạo candidate.

AT10 – Ratio dưới biên:
body_green/body3 < 1.0 => không đạt.

AT11 – Ratio tại biên dưới:
ratio = 1.0 => đạt.

AT12 – Ratio trong khoảng:
1.0 < ratio < 2.0 => đạt.

AT13 – Ratio tại biên trên:
ratio = 2.0 => đạt.

AT14 – Ratio trên biên:
ratio > 2.0 => không đạt.

AT15 – Nến xanh ngay sau R3:
nếu đạt ratio => FOUND.

AT16 – Nến xanh thứ 5:
nếu nến thứ 1–4 không đạt, nến thứ 5 đạt => FOUND.

AT17 – Hết 5 nến:
không có nến nào đạt => EXPIRED sau khi nến thứ 5 đóng và available.

AT18 – Không có look-ahead:
nến xanh chưa đóng hoặc chưa available không được dùng để tạo FOUND.

AT19 – Idempotency:
chạy lại cùng input và rule_version không tạo setup trùng.

AT20 – Tín hiệu:
FOUND chỉ xuất LONG_SETUP sau khi nến xanh đóng và dữ liệu đã available; không giả định giá khớp tại giá đóng cửa tín hiệu.

AT21 – Khoảng trống dữ liệu:
không được coi các nến ở hai phía khoảng trống là "liên tiếp" nếu lịch dữ liệu xác nhận thiếu nến hợp lệ.

AT22 – Setup chồng lấn:
hai bộ ba có R1 khác nhau có thể tạo hai candidate; cùng bộ ba không được tạo trùng.

============================================================
13. LOGGING VÀ METRICS
============================================================

Tối thiểu log:
- ticker/timeframe
- processing_time
- candle_time
- rule_version
- context_structure_ids
- setup_id
- status transition
- reason_code
- lỗi dữ liệu hoặc lỗi upsert

Metrics theo lần chạy:
- total candles processed
- invalid candles
- data gaps
- valid red triplets
- candidates created
- setups FOUND
- setups EXPIRED
- setups INVALIDATED
- duplicate candidates prevented
- tỷ lệ FOUND / candidates created

Không dùng tỷ lệ FOUND hoặc số tín hiệu làm kết luận chiến lược có lợi nhuận; đánh giá lợi nhuận thuộc backtest engine sau này.

============================================================
14. CẤU HÌNH
============================================================

Ví dụ cấu hình logic (tên trường có thể điều chỉnh theo coding convention):

rule_version: "L3_REVERSAL_V1"
timeframe: "15m"
max_wait_candles: 5
body_ratio_min: 1.0
body_ratio_max: 2.0
red_candle_1_requires_body_gt_total_wick: true
red_candle_2_requires_body_gt_total_wick: false
red_candle_3_requires_body_gt_total_wick: true
require_green_close_above_red3_high: false
require_break_above_current_structure_high: false
allow_overlapping_candidates: true
invalidate_if_context_structure_broken_before_found: true

Các trường require_green_close_above_red3_high và require_break_above_current_structure_high hiện đều false theo baseline. Khi kiểm định biến thể, hãy tạo rule_version mới thay vì thay đổi kết quả V1.

============================================================
15. NGOÀI PHẠM VI V1
============================================================

Không triển khai trong Layer 3 V1:
- FVG và vùng giá vào lệnh.
- Giá mua thực tế và mô phỏng khớp lệnh.
- Stop Loss / Take Profit.
- Bộ lọc volume.
- RSI, MA, MACD hoặc chỉ báo khác.
- Điều kiện nến xanh đóng cửa vượt đỉnh nến đỏ số 3.
- Điều kiện vượt đỉnh cấu trúc hiện tại để xác nhận/hủy setup.
- Tối ưu tham số dựa trên dữ liệu kiểm định.
Các mục này có thể được bổ sung thành các phiên bản/nhánh thử nghiệm sau.

============================================================
16. TIÊU CHÍ HOÀN THÀNH
============================================================

Layer 3 V1 được xem là hoàn thành khi:
1. Logic bối cảnh và mô hình được triển khai theo tài liệu.
2. Tất cả acceptance tests AT01–AT22 đạt.
3. Không look-ahead trong xử lý nến và cấu trúc.
4. Chạy lại dữ liệu không tạo duplicate.
5. Có thể truy vết từng LONG_SETUP đến hai cấu trúc và bốn nến (R1, R2, R3, G).
6. Có thống kê candidate FOUND/EXPIRED/INVALIDATED.
7. Rule version được lưu cùng mỗi setup.
8. Output có thể được Layer tiếp theo/backtest engine đọc mà không phụ thuộc cách triển khai nội bộ.

KẾT THÚC TÀI LIỆU
```
