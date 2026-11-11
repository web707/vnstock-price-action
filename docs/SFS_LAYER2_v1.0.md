 — TÀI LIỆU SFS LAYER 2 v1.0 (nguyên văn)

```
SYSTEM FUNCTIONAL SPECIFICATION (SFS)
LAYER 2 — MARKET STRUCTURE BUILDER
Dự án: NCKH-BIGDATA-STOCK-2026
Phiên bản tài liệu: 1.0
Trạng thái: Draft for implementation review
Thị trường: Chứng khoán Việt Nam, Long-only ở tầng chiến lược
Khung dữ liệu đầu vào hiện tại: OHLCV 15 phút

======================================================================
0. MỤC ĐÍCH VÀ PHẠM VI
======================================================================

0.1. Mục tiêu
Layer 2 chuyển chuỗi swing do Layer 1 phát hiện thành chuỗi cấu trúc thị trường
được chuẩn hóa, có thể giải thích và tái lập khi backtest.

Layer 2 phải:
- Chuẩn hóa và kiểm tra đầu vào từ Layer 1.
- Giữ đúng trình tự thời gian của các điểm cực trị.
- Gắn nhãn mô tả HH, HL, LH, LL.
- Phân loại nhịp sóng và xác định Major Structure / Internal Move.
- Quản lý trạng thái FORMING, CONFIRMED, BROKEN, UNCLEAR.
- Trích xuất hai Major Structure gần nhất theo đúng thứ tự hình thành.
- Cung cấp bối cảnh cho Layer 3 mà không tự phát sinh lệnh mua/bán.
- Lưu dấu vết quy tắc và thời điểm thông tin có thể được sử dụng.

0.2. Không thuộc phạm vi
Layer 2 không:
- Phát hiện swing mới thay Layer 1.
- Xác định mẫu hình nến giao dịch cuối cùng của Layer 3.
- Mô phỏng khớp lệnh, phí giao dịch hoặc tính PnL.
- Xóa cấu trúc giảm vì hệ thống chỉ giao dịch Long.
- Khẳng định các quy tắc kỹ thuật dưới đây chính là quy tắc gốc của Gianluca Bruni.
  Những quy tắc chưa được đối chiếu nguồn phải được coi là giả thuyết nghiên cứu.

0.3. Nguyên tắc thiết kế
- Không look-ahead: tại thời điểm mô phỏng T, chỉ dùng dữ liệu có thể biết tại T.
- Tách dữ liệu gốc, phân loại hình học, trạng thái vòng đời và điều kiện Long.
- Có thể giải thích vì sao một swing/cấu trúc được giữ, loại, xác nhận hoặc phá vỡ.
- Có versioning để kết quả cũ có thể được tái tạo.
- Không dùng kết quả Layer 3 để thay đổi cách phân loại cấu trúc ở Layer 2.

======================================================================
1. ĐỊNH NGHĨA THUẬT NGỮ
======================================================================

1.1. Swing
Điểm HIGH hoặc LOW được Layer 1 phát hiện.
Các trường quan trọng:
- swing_id
- swing_type: HIGH / LOW
- extreme_price
- extreme_time: thời điểm xảy ra cực trị
- confirmed_at: thời điểm hệ thống có đủ dữ liệu xác nhận swing
- atr_at_extreme
- source_version / version

1.2. Swing Leg
Một nhịp nối hai swing liên tiếp trong chuỗi swing đã chuẩn hóa.
Ví dụ:
LOW -> HIGH là nhịp hướng lên.
HIGH -> LOW là nhịp hướng xuống.
Một Swing Leg không mặc nhiên là một Market Structure.

1.3. Mechanical Label
Nhãn mô tả quan hệ giữa swing cùng loại:
- HH: HIGH hiện tại cao hơn HIGH hợp lệ trước đó.
- LH: HIGH hiện tại thấp hơn HIGH hợp lệ trước đó.
- EQH: hai HIGH được xem là ngang bằng trong tolerance cấu hình.
- HL: LOW hiện tại cao hơn LOW hợp lệ trước đó.
- LL: LOW hiện tại thấp hơn LOW hợp lệ trước đó.
- EQL: hai LOW được xem là ngang bằng trong tolerance cấu hình.
- FIRST_HIGH / FIRST_LOW: chưa có swing cùng loại trước đó.

Nhãn này chỉ mô tả hình học, không tự nó xác nhận xu hướng.

1.4. Market Structure
Một đơn vị cấu trúc được tạo từ chuỗi swing theo quy tắc cấu trúc được cấu hình.
Cấu trúc phải có:
- swing bắt đầu và kết thúc;
- hướng UP / DOWN / UNCLEAR;
- điều kiện xác nhận cụ thể;
- mức giá bảo vệ / phá vỡ nếu quy tắc yêu cầu;
- thời điểm cấu trúc có thể được biết;
- trạng thái và reason code.

LƯU Ý: Không được tự động coi mọi Swing Leg vượt 3 ATR là một Market Structure.
Trước khi release, nhóm dự án phải chốt quy tắc cấu trúc định lượng tại mục 5.
Mục 5 cung cấp baseline có thể kiểm thử, không tuyên bố đó là quy tắc nguyên bản của Bruni.

1.5. Major Structure / Internal Move
- MAJOR: cấu trúc vượt qua quy tắc cấu trúc và các bộ lọc đã cấu hình.
- INTERNAL: nhịp/swing nằm bên trong cấu trúc lớn hơn hoặc không đạt điều kiện MAJOR.
- UNCLASSIFIED: chưa đủ thông tin để phân loại.

Không xóa Internal Move khỏi dữ liệu nguồn. Chỉ không đưa nó vào chuỗi Major Structure.

1.6. Event Time và Available Time
- event_time: khi sự kiện giá xảy ra, ví dụ extreme_time hoặc thời điểm nến phá vỡ.
- available_at: thời điểm hệ thống thực sự có thể biết sự kiện đó.
Một cấu trúc chỉ được sử dụng cho quyết định tại T nếu available_at <= T.

======================================================================
2. INPUT CONTRACT
======================================================================

2.1. Nguồn đầu vào
Danh sách swing đã được Layer 1 xác nhận, cùng dữ liệu OHLCV cần thiết để kiểm tra
phá vỡ cấu trúc.

2.2. Bắt buộc
- swing_id: định danh duy nhất.
- ticker.
- timeframe.
- swing_type: HIGH / LOW.
- extreme_price: số dương.
- extreme_time.
- confirmed_at.
- atr_at_extreme: số dương hoặc NULL nếu Layer 1 chưa có giá trị hợp lệ.
- rule_version / source_version.

2.3. Kiểm tra đầu vào
- swing_id không NULL và không trùng trong cùng source/version.
- swing_type thuộc HIGH, LOW.
- extreme_price > 0.
- extreme_time và confirmed_at hợp lệ.
- confirmed_at không được sớm hơn thời điểm cần thiết để xác nhận swing theo
  quy tắc Layer 1.
- atr_at_extreme phải > 0 để áp dụng lọc ATR; nếu thiếu thì không tự gán 0.
- ticker và timeframe phải nhất quán trong một batch.
- Một swing chỉ được đưa vào mô phỏng sau confirmed_at.
- Bản ghi bị sửa/thay thế phải có version hoặc change event; không âm thầm ghi đè
  khiến kết quả lịch sử không thể tái lập.

2.4. Hai trục thời gian
- Để dựng thứ tự giá: sắp xếp theo extreme_time, sau đó theo quy tắc tie-break
  xác định rõ.
- Để mô phỏng tại thời điểm T: chỉ sử dụng swing có confirmed_at <= T.
Không được sắp xếp toàn bộ lịch sử theo confirmed_at rồi mặc nhiên dùng thứ tự đó
làm trình tự cực trị của giá.

2.5. Tie-break và dữ liệu bất thường
Nếu hai swing có extreme_time bằng nhau hoặc không thể xác định trình tự:
- Không tự đoán thứ tự.
- Đánh dấu DATA_ORDER_AMBIGUOUS.
- Ghi log và đưa vào hàng chờ kiểm tra hoặc xử lý theo quy tắc tie-break đã được
  phê duyệt trong cấu hình.
Không được tự ý sửa dữ liệu giá gốc.

======================================================================
3. QUY TRÌNH XỬ LÝ TỔNG THỂ
======================================================================

STEP 1 — INGEST & VALIDATE
1. Đọc swing từ Layer 1.
2. Kiểm tra schema, giá trị, định danh, phiên bản và tính nhất quán.
3. Loại bản ghi trùng lặp kỹ thuật theo idempotency key; không gộp hai swing
   khác nhau chỉ vì giá giống nhau.
4. Ghi lỗi vào bảng audit/quarantine cùng reason code.
5. Chỉ tiếp tục với bản ghi hợp lệ.

STEP 2 — BUILD PRICE-ORDERED SWING SEQUENCE
1. Chỉ đưa vào tập dữ liệu được phép sử dụng những swing đã confirmed tại thời điểm
   mô phỏng.
2. Sắp xếp các swing đủ điều kiện theo extreme_time.
3. Kiểm tra chuỗi HIGH/LOW luân phiên.
4. Nếu hai swing cùng loại đứng liền nhau:
   - Không tự động loại một swing chỉ vì vi phạm luân phiên.
   - Xử lý theo quy tắc chuẩn hóa đã được phê duyệt:
     a) Nếu là các ứng viên HIGH liên tiếp trước khi có LOW hợp lệ, có thể giữ ứng
        viên cực trị cao nhất làm pivot đại diện khi Layer 1/versioning cho phép;
     b) tương tự với LOW, giữ ứng viên thấp nhất;
     c) nếu không thể chứng minh đây là cập nhật/thay thế cùng một pivot, đánh dấu
        INVALID_SWING_SEQUENCE để kiểm tra.
   - Lưu cả bản ghi gốc và quan hệ thay thế; không xóa dấu vết.
5. Không sử dụng pivot chưa được xác nhận tại thời điểm xử lý.

STEP 3 — MECHANICAL LABELING
1. Duyệt chuỗi swing theo extreme_time.
2. Với HIGH, so sánh với HIGH hợp lệ trước đó.
3. Với LOW, so sánh với LOW hợp lệ trước đó.
4. Dùng tolerance cấu hình để tránh so sánh số thực tuyệt đối:
   price_tolerance = max(min_tick_tolerance, price * equal_price_pct)
   Giá trị mặc định phải được cấu hình theo mã/thị trường; không hard-code ngầm.
5. Kết quả:
   - HIGH hiện tại > HIGH trước + tolerance => HH
   - HIGH hiện tại < HIGH trước - tolerance => LH
   - nằm trong tolerance => EQH
   - LOW hiện tại > LOW trước + tolerance => HL
   - LOW hiện tại < LOW trước - tolerance => LL
   - nằm trong tolerance => EQL
6. Lưu reference_swing_id dùng để so sánh.
7. Nhãn không quyết định độc lập cấu trúc tăng/giảm.

STEP 4 — BUILD SWING LEGS
Với mỗi cặp swing hợp lệ liên tiếp:
- leg_id
- start_swing_id
- end_swing_id
- direction: UP nếu LOW -> HIGH; DOWN nếu HIGH -> LOW
- start_time, end_time
- start_price, end_price
- absolute_amplitude = abs(end_price - start_price)
- pct_amplitude = abs(end_price - start_price) / start_price
- atr_reference = atr_at_start_swing
- amplitude_atr = absolute_amplitude / atr_reference nếu ATR hợp lệ
- duration_bars / duration_minutes nếu tính được chính xác
- available_at = max(confirmed_at của các swing dùng để tạo leg)

Swing Leg chỉ là đơn vị mô tả nhịp, chưa phải Major Structure.

STEP 5 — STRUCTURE CANDIDATE GENERATION
Tạo ứng viên cấu trúc từ chuỗi swing/legs theo một bộ quy tắc cấu trúc được version hóa.
Bộ quy tắc phải định nghĩa:
- điểm bắt đầu và kết thúc;
- tối thiểu bao nhiêu swing/legs;
- quan hệ giá nào tạo thành cấu trúc;
- sự kiện nào bắt đầu FORMING;
- điều kiện nào xác nhận;
- mức giá nào làm cấu trúc mất hiệu lực;
- cách xử lý khi có pivot mới hoặc pivot bị thay thế.

Không được tạo cấu trúc chỉ dựa vào amplitude >= ngưỡng ATR.

STEP 6 — AMPLITUDE FILTER
Baseline nghiên cứu:
- amplitude_threshold = atr_multiplier * atr_at_start
- atr_multiplier mặc định thử nghiệm: 3.0
- atr_multiplier phải là tham số cấu hình có rule_version.
- Nếu ATR NULL/<=0: không thể xác nhận theo bộ lọc ATR; gán UNCLASSIFIED hoặc
  DATA_QUALITY_INSUFFICIENT, không thay ATR bằng 0.
- Nếu amplitude < threshold: candidate không đạt amplitude filter; phân loại
  INTERNAL hoặc UNCLASSIFIED tùy quy tắc cấu trúc.
- Nếu amplitude >= threshold: chỉ đạt amplitude filter, chưa tự động là MAJOR.
- Lưu amplitude, ATR tham chiếu, multiplier và kết quả bộ lọc để kiểm toán.

Nghiên cứu sensitivity tối thiểu: 1.5, 2.0, 2.5, 3.0 ATR trên cùng dữ liệu.
Không lựa chọn ngưỡng chỉ vì nó làm tăng lợi nhuận trên một tập backtest duy nhất;
cần kiểm tra ngoài mẫu và theo nhiều mã/nhóm ngành/giai đoạn.

STEP 7 — STRUCTURE STATE MANAGEMENT
Các trạng thái vòng đời:
- FORMING: ứng viên đang phát triển, chưa đạt điều kiện xác nhận.
- CONFIRMED: mọi điều kiện bắt buộc đã được thỏa mãn và có available_at.
- BROKEN: một cấu trúc từng CONFIRMED bị vi phạm theo quy tắc phá vỡ.
- UNCLEAR: dữ liệu hoặc quan hệ swing không đủ rõ để phân loại.

Quy tắc:
- INTERNAL/MAJOR là classification riêng, không phải status.
- Một cấu trúc BROKEN vẫn được giữ trong lịch sử.
- Không sửa ngược trạng thái tại thời điểm quá khứ mà không lưu event/version.
- confirmed_at của cấu trúc là thời điểm điều kiện xác nhận có thể biết, không phải
  extreme_time của swing nếu hai thời điểm khác nhau.
- available_at của cấu trúc = thời điểm muộn nhất trong các dữ liệu cần thiết để
  xác nhận cấu trúc.
- Không được dùng cấu trúc trước available_at trong Layer 3.

STEP 8 — BREAK / INVALIDATION
Cấu hình bắt buộc phải chốt trước release:
- break_basis: CLOSE hoặc WICK.
- break_level: mốc giá được bảo vệ bởi cấu trúc.
- break_operator: ví dụ CLOSE < level đối với phá đáy; CLOSE > level đối với phá đỉnh.
- bar timeframe dùng xác định phá vỡ.
- quy tắc xử lý gap, giá trần/sàn, dữ liệu thiếu và nến bất thường.
- invalidated_at: thời điểm đầu tiên mà quy tắc phá vỡ có thể biết được.
- break_candle_time, break_price, break_reason_code.

Không dùng một quy tắc chung kiểu "giá vi phạm cấu trúc" mà không định nghĩa mức
giá cụ thể. Quy tắc CLOSE/WICK phải được lưu trong rule_version để backtest có thể
tái lập. Nếu chưa được phê duyệt, không tự suy diễn; đánh dấu cấu hình chưa hoàn tất.

STEP 9 — CLASSIFY MAJOR VS INTERNAL
Một candidate được gán MAJOR khi:
1. Được tạo theo quy tắc cấu trúc đã phê duyệt.
2. Có đủ dữ liệu và chuỗi swing hợp lệ.
3. Đạt bộ lọc biên độ cấu hình nếu bộ lọc này được bật.
4. Đạt điều kiện xác nhận của loại cấu trúc đó.
5. Không vi phạm điều kiện chất lượng dữ liệu.
Nếu không đạt biên độ: INTERNAL (nếu vẫn xác định được là nhịp nội bộ).
Nếu dữ liệu/quan hệ không đủ rõ: UNCLASSIFIED.
Không gán MAJOR chỉ vì amplitude >= 3 ATR.

STEP 10 — BUILD MAJOR STRUCTURE SEQUENCE
- Tạo một chuỗi riêng gồm các structure candidate được phân loại MAJOR.
- Giữ cả UP và DOWN.
- Internal Move không tạo thêm phần tử trong chuỗi Major Structure.
- Mỗi Major Structure phải có sequence_no hoặc previous_major_structure_id.
- Liền kề nghĩa là đứng liên tiếp trong chuỗi Major Structure theo event time/available
  time đã được định nghĩa, không phải hai cấu trúc bất kỳ được chọn để có kết quả đẹp.
- Không bỏ qua một Major Structure hợp lệ ở giữa để ghép hai cấu trúc xa nhau.
- Nếu một cấu trúc bị sửa do dữ liệu nguồn/version mới, tính lại phần chuỗi bị ảnh
  hưởng và lưu lịch sử thay đổi.

STEP 11 — EXTRACT TWO NEAREST STRUCTURES
Tại thời điểm truy vấn T:
1. Chỉ xét cấu trúc có available_at <= T.
2. Theo quy tắc mặc định, lấy hai Major Structure gần nhất trong chuỗi đã xác nhận,
   bất kể hướng UP hay DOWN.
3. Không tự loại cấu trúc BROKEN khỏi lịch sử. Tuy nhiên, cấu hình truy vấn phải
   xác định rõ lấy:
   - hai cấu trúc CONFIRMED gần nhất để tái dựng lịch sử; hay
   - hai cấu trúc gần nhất đang còn hiệu lực tại T.
   Hai chế độ không được trộn lẫn trong cùng một kết quả.
4. Nếu cần hai cấu trúc còn hiệu lực, cấu trúc BROKEN không được coi là active,
   nhưng vẫn phải có trong lịch sử và không được nhảy qua cấu trúc khác một cách
   âm thầm.
5. Nếu không đủ hai cấu trúc theo đúng chế độ truy vấn: INSUFFICIENT_STRUCTURE.
6. Trả về older_structure_id và latest_structure_id theo đúng thứ tự thời gian.

STEP 12 — LONG CONTEXT FLAG
- Layer 2 không phát lệnh mua.
- is_long_candidate là cờ bối cảnh, không phải buy signal.
- Chỉ tính khi có đủ hai cấu trúc và quy tắc Long-context đã được định nghĩa.
- Chưa có quy tắc được phê duyệt: NULL/NOT_EVALUATED, không tự gán false như thể
  đã đánh giá đầy đủ.
- Nếu quy tắc đã được phê duyệt nhưng không thỏa: false + NOT_LONG_ELIGIBLE.
- Nếu thỏa: true + LONG_CONTEXT_ELIGIBLE.
- Layer 3 chịu trách nhiệm kết hợp context với mẫu hình và các điều kiện giao dịch.

======================================================================
4. QUY TẮC THỜI GIAN / CHỐNG LOOK-AHEAD
======================================================================

4.1. Mỗi record/event cần phân biệt:
- event_time: lúc sự kiện giá xảy ra.
- available_at: lúc hệ thống có thể biết sự kiện.
- created_at: lúc record được ghi vào hệ thống.
- rule_version: phiên bản logic áp dụng.

4.2. Tại mỗi thời điểm mô phỏng T:
- Chỉ sử dụng swing confirmed_at <= T.
- Chỉ sử dụng structure available_at <= T.
- Chỉ dùng nến OHLCV đã đóng tại T nếu logic yêu cầu Close.
- Không sử dụng swing được xác nhận sau T dù extreme_time của nó nằm trước T.
- Không sử dụng dữ liệu phiên bản mới để thay đổi quyết định đã mô phỏng trong quá khứ,
  trừ khi đang chạy một lần backfill/rebuild riêng biệt có version rõ ràng.

4.3. Kiểm thử look-ahead
Test phải chứng minh:
- Thêm các nến tương lai không làm thay đổi output có available_at trước thời điểm
  tương lai đó.
- Một pivot chỉ được đưa vào chuỗi khi confirmed_at đã tới.
- Một break chỉ được ghi nhận tại thời điểm break rule có thể được đánh giá.
- Backtest chạy từng nến và chạy batch cho cùng một snapshot/version phải cho kết quả
  nhất quán về các event đã biết tại cùng thời điểm.

======================================================================
5. QUY TẮC CẤU TRÚC — CẦN PHÊ DUYỆT TRƯỚC RELEASE
======================================================================

Đây là phần nghiệp vụ cốt lõi. Không nên để Developer tự quyết định.

5.1. Phương án baseline để thử nghiệm
Dự án có thể triển khai một Structure Rule Provider với các tham số:
- swing_sequence_rule_version
- min_swing_count
- structure_direction_rule
- amplitude_filter_enabled
- atr_multiplier
- confirmation_rule
- break_rule
- equal_high_low_tolerance

Không hard-code các quy tắc vào nhiều nơi trong code. Đưa chúng vào cấu hình có
version để so sánh các phương án nghiên cứu.

5.2. Baseline cấu trúc UP (đề xuất thử nghiệm, không phải quy tắc gốc đã xác minh)
Một cấu trúc UP candidate cần được mô tả bằng một chuỗi swing hợp lệ, trong đó có
bằng chứng về đáy cao hơn và/hoặc đỉnh cao hơn theo quy tắc được phê duyệt.
Chỉ khi thỏa cấu trúc hình học, bộ lọc biên độ và điều kiện xác nhận thì mới gán
structure_direction=UP, classification=MAJOR, status=CONFIRMED.

5.3. Baseline cấu trúc DOWN (đề xuất thử nghiệm, không phải quy tắc gốc đã xác minh)
Tương tự UP nhưng phản ánh các quan hệ đỉnh thấp hơn và/hoặc đáy thấp hơn theo quy
tắc được phê duyệt. Phải giữ lại DOWN trong lịch sử, kể cả khi Long-only không dùng
nó làm ứng viên mua.

5.4. Không đủ bằng chứng
Nếu chuỗi swing không thể được phân loại rõ ràng:
- structure_direction=UNCLEAR;
- classification=UNCLASSIFIED;
- status=UNCLEAR;
- reason_code tương ứng.
Không ép mọi candidate thành UP hoặc DOWN.

5.5. Quyết định cần BA/Quant owner ký duyệt
- Một structure có tối thiểu bao nhiêu swing?
- Dùng quan hệ HH/HL/LH/LL nào để xác nhận UP/DOWN?
- Có cho phép cấu trúc kết thúc ngay tại swing đầu tiên phá đỉnh/đáy trước không?
- Mức giá bảo vệ cấu trúc là swing nào?
- Ngưỡng ATR dùng như điều kiện bắt buộc hay chỉ là bộ lọc phân loại?
- EQH/EQL được xử lý như thế nào?
- Cấu trúc BROKEN có còn được dùng trong cặp context của Layer 3 không?
- Quy tắc phá vỡ dựa Close hay Wick?
- Nếu Layer 1 cập nhật pivot đã phát hành, chính sách rebuild ra sao?

Không release production/backtest chính thức nếu các quyết định ảnh hưởng trực tiếp
đến kết quả chưa được chốt trong rule_version.

======================================================================
6. OUTPUT DATA MODEL
======================================================================

6.1. Bảng swing_label
- ticker
- timeframe
- swing_id
- swing_type
- extreme_time
- confirmed_at
- mechanical_label
- reference_swing_id
- price_difference
- price_tolerance
- rule_version
- created_at

6.2. Bảng swing_leg
- leg_id
- ticker
- timeframe
- start_swing_id
- end_swing_id
- direction: UP / DOWN
- start_time
- end_time
- start_price
- end_price
- absolute_amplitude
- pct_amplitude
- atr_reference
- amplitude_atr
- available_at
- classification: MAJOR / INTERNAL / UNCLASSIFIED (nếu cần)
- reason_code
- rule_version

6.3. Bảng market_structure
- structure_id
- ticker
- timeframe
- structure_sequence_no
- previous_major_structure_id
- start_swing_id
- end_swing_id
- start_time
- end_time
- structure_direction: UP / DOWN / UNCLEAR
- classification: MAJOR / INTERNAL / UNCLASSIFIED
- status: FORMING / CONFIRMED / BROKEN / UNCLEAR
- amplitude
- amplitude_atr
- atr_reference
- atr_multiplier
- protected_level
- break_basis
- break_level
- confirmed_at
- available_at
- invalidated_at
- break_candle_time
- break_price
- reason_code
- rule_version
- source_version
- created_at
- updated_at

6.4. Bảng market_structure_event (khuyến nghị)
Lưu các thay đổi trạng thái thay vì chỉ ghi đè:
- event_id
- structure_id
- old_status
- new_status
- event_type
- event_time
- available_at
- reason_code
- source_version
- rule_version
- payload_json

6.5. Bảng structure_context_snapshot
- ticker
- timeframe
- as_of_time
- older_structure_id
- latest_structure_id
- context_status
- is_long_candidate: TRUE / FALSE / NULL
- reason_code
- rule_version
- generated_at

6.6. Nguyên tắc lưu trữ
- Lưu nguyên bản swing từ Layer 1.
- Các bảng Layer 2 tham chiếu swing_id; không xóa dữ liệu nguồn.
- Dùng unique key phù hợp với ticker/timeframe/source/version để tránh insert trùng.
- Các lần chạy lặp lại cùng input + rule_version phải idempotent.
- Khi logic hoặc dữ liệu nguồn thay đổi, tạo version/event mới hoặc rebuild có kiểm soát.
- Không âm thầm sửa lịch sử đã dùng trong backtest.

======================================================================
7. REASON CODES
======================================================================

Input/data:
- INVALID_SWING_ID
- DUPLICATE_SWING
- INVALID_SWING_TYPE
- INVALID_PRICE
- INVALID_TIMESTAMP
- ATR_MISSING_OR_INVALID
- DATA_ORDER_AMBIGUOUS
- INVALID_SWING_SEQUENCE
- SOURCE_VERSION_CHANGED

Label/leg:
- FIRST_HIGH
- FIRST_LOW
- LABEL_HH
- LABEL_HL
- LABEL_LH
- LABEL_LL
- LABEL_EQH
- LABEL_EQL
- LEG_CREATED

Structure:
- STRUCTURE_CANDIDATE_CREATED
- STRUCTURE_RULE_NOT_MET
- AMPLITUDE_TOO_SMALL_INTERNAL
- AMPLITUDE_FILTER_PASSED
- STRUCTURE_CONFIRMED
- STRUCTURE_BROKEN
- STRUCTURE_UNCLEAR
- STRUCTURE_REBUILT
- INSUFFICIENT_STRUCTURE
- LONG_CONTEXT_ELIGIBLE
- NOT_LONG_ELIGIBLE
- LONG_CONTEXT_NOT_EVALUATED
- BREAK_RULE_NOT_CONFIGURED

Reason code phải thể hiện nguyên nhân chính. Chi tiết bổ sung lưu trong payload/log,
không nhồi nhiều lý do khác nhau vào một chuỗi tự do.

======================================================================
8. ACCEPTANCE CRITERIA / TEST CASES
======================================================================

TC01 — Swing trùng ID
Given hai bản ghi có cùng swing_id trong cùng source/version
When Layer 2 validate input
Then không xử lý trùng hai lần; ghi DUPLICATE_SWING và audit.

TC02 — Swing chưa được xác nhận
Given swing có confirmed_at > as_of_time
When Layer 2 dựng context tại as_of_time
Then swing không được sử dụng.

TC03 — Trình tự extreme_time khác confirmed_at
Given thứ tự xác nhận khác thứ tự cực trị
When Layer 2 dựng chuỗi swing
Then chuỗi giá theo extreme_time; khả năng sử dụng vẫn bị giới hạn bởi confirmed_at.

TC04 — Hai swing cùng loại liên tiếp
Given HIGH-HIGH hoặc LOW-LOW
When chuẩn hóa chuỗi
Then áp dụng chính sách đã phê duyệt; không âm thầm xóa bản ghi; nếu không thể giải
thích thì INVALID_SWING_SEQUENCE.

TC05 — Gắn nhãn HH/HL/LH/LL
Given có swing cùng loại trước đó
When giá chênh lệch vượt tolerance
Then nhãn được gán đúng và lưu reference_swing_id.

TC06 — EQH/EQL
Given chênh lệch giá nằm trong tolerance
When labeling
Then gán EQH/EQL, không ép thành HH/LH hoặc HL/LL.

TC07 — Biên độ nhỏ
Given amplitude < atr_multiplier * atr_reference
When áp dụng amplitude filter
Then candidate không được công nhận MAJOR chỉ từ amplitude; gán INTERNAL hoặc
UNCLASSIFIED theo quy tắc đã phê duyệt.

TC08 — Biên độ đủ lớn nhưng cấu trúc không hợp lệ
Given amplitude >= ngưỡng nhưng không đạt structure rule
When classification
Then không gán MAJOR.

TC09 — ATR thiếu
Given ATR NULL hoặc <= 0
When áp dụng amplitude filter
Then không chia cho 0, không tự gán ATR=0; trả reason code dữ liệu.

TC10 — Xác nhận cấu trúc
Given mọi điều kiện cấu trúc đã thỏa
When thời điểm xác nhận đến
Then status=CONFIRMED, available_at được ghi chính xác.

TC11 — Phá vỡ cấu trúc
Given cấu trúc CONFIRMED và nến vi phạm break rule đã cấu hình
When kiểm tra nến
Then status=BROKEN, ghi invalidated_at, break candle, break price và reason code.

TC12 — Hai Major Structure
Given chuỗi Major Structure S1, S2, S3
When truy vấn hai cấu trúc gần nhất tại T
Then trả S2 và S3 nếu cả hai đã available tại T; không bỏ qua S3 để chọn cấu trúc
cũ hơn.

TC13 — Không đủ hai cấu trúc
Given chỉ có một Major Structure hợp lệ tại T
When extract context
Then trả INSUFFICIENT_STRUCTURE; không tạo cấu trúc giả.

TC14 — Bảo toàn DOWN
Given cấu trúc DOWN đã được xác nhận
When tạo chuỗi Major Structure
Then cấu trúc DOWN vẫn được lưu và có thể được trả về làm context.

TC15 — Không look-ahead
Given dữ liệu lịch sử đến T và sau đó bổ sung các nến tương lai
When chạy lại chế độ point-in-time
Then kết quả có available_at <= T không bị thay đổi bởi thông tin tương lai.

TC16 — Idempotency
Given cùng input snapshot và rule_version chạy hai lần
When pipeline hoàn tất
Then không sinh thêm cấu trúc/swing leg trùng.

TC17 — Rule version
Given cùng input nhưng hai rule_version khác nhau
When chạy hai phiên bản
Then kết quả được phân biệt rõ, có thể so sánh và không ghi đè lẫn nhau.

TC18 — Long flag chưa cấu hình
Given chưa phê duyệt quy tắc Long-context
When tạo context
Then is_long_candidate=NULL và reason_code=LONG_CONTEXT_NOT_EVALUATED.

======================================================================
9. LOGGING, MONITORING VÀ HIỆU NĂNG
======================================================================

Mỗi batch nên log:
- ticker, timeframe, as_of_time, source_version, rule_version;
- số swing đầu vào / hợp lệ / bị quarantine;
- số swing được gắn nhãn;
- số Swing Leg được tạo;
- số candidate, MAJOR, INTERNAL, UNCLASSIFIED;
- số cấu trúc CONFIRMED / BROKEN / UNCLEAR;
- số ticker thiếu hai cấu trúc;
- thời gian xử lý và lỗi.

Yêu cầu vận hành:
- Pipeline chạy lại được và có tính idempotent.
- Có thể rebuild theo ticker, timeframe, khoảng thời gian và rule_version.
- Ưu tiên xử lý incremental; khi pivot cũ bị thay đổi, tính lại vùng phụ thuộc cần thiết.
- Không cho phép cấu hình ngưỡng/logic thay đổi giữa một batch đang chạy.
- Có audit trail cho mọi lần thay đổi trạng thái cấu trúc.

======================================================================
10. KẾ HOẠCH TRIỂN KHAI
======================================================================

Phase 1 — Input & Labeling
- Validate input.
- Chuẩn hóa chuỗi swing.
- Gắn nhãn HH/HL/LH/LL/EQH/EQL.
- Unit test cho timestamp, trùng lặp, chuỗi không luân phiên.

Phase 2 — Swing Legs & Amplitude
- Tạo Swing Leg.
- Tính amplitude, percentage amplitude và amplitude/ATR.
- Chạy báo cáo sensitivity theo nhiều ATR multiplier.
- Chưa kết luận mọi leg đạt ngưỡng là Major.

Phase 3 — Structure Rule Provider
- BA/Quant owner phê duyệt quy tắc cấu trúc UP/DOWN.
- Implement FORMING/CONFIRMED/BROKEN.
- Chốt protected level và break rule.
- Version hóa quy tắc.

Phase 4 — Major Sequence & Context
- Xây chuỗi Major Structure.
- Lấy hai cấu trúc liền kề tại as_of_time.
- Bảo toàn cấu trúc DOWN.
- Xuất context cho Layer 3.

Phase 5 — Backtest Validation
- Point-in-time replay.
- Kiểm tra look-ahead.
- So sánh batch và incremental.
- Kiểm thử nhiều ticker, ngành, giai đoạn thị trường.
- Báo cáo số lượng cấu trúc, tỷ lệ cấu trúc bị phá, thời gian tồn tại và ảnh hưởng
  của tham số. Chỉ sau đó mới đánh giá hiệu quả chiến lược kết hợp Layer 3.

======================================================================
11. QUYẾT ĐỊNH NGHIỆP VỤ CẦN OWNER PHÊ DUYỆT
======================================================================

Các mục sau là blocker trước khi coi Layer 2 là hoàn chỉnh:

D01. Định nghĩa chính xác một cấu trúc gồm chuỗi swing nào.
D02. Điều kiện định lượng để xác nhận cấu trúc UP và DOWN.
D03. Số swing/leg tối thiểu.
D04. Vai trò của ngưỡng ATR: bắt buộc hay bộ lọc bổ sung.
D05. Chính sách EQH/EQL và tolerance.
D06. Protected level và điều kiện phá vỡ.
D07. Break basis: CLOSE hay WICK.
D08. Lấy hai cấu trúc CONFIRMED gần nhất hay hai cấu trúc còn active.
D09. Chính sách khi Layer 1 thay thế/cập nhật swing cũ.
D10. Định nghĩa Long-context thuộc Layer 2 hay Layer 3.
D11. Đối chiếu các quy tắc với nguồn phương pháp Gianluca Bruni; ghi rõ phần nào là
     quy tắc gốc, phần nào là giả thuyết kỹ thuật do dự án bổ sung.

Tiêu chí hoàn thành Layer 2:
- Mọi quyết định D01-D11 có trạng thái APPROVED / DEFERRED rõ ràng.
- Các quy tắc được phê duyệt được lưu trong rule_version.
- Acceptance tests đạt.
- Có bằng chứng point-in-time replay không look-ahead.
- Có thể giải thích vì sao mỗi candidate được phân loại MAJOR, INTERNAL hoặc
  UNCLASSIFIED.
- Output cung cấp đúng hai cấu trúc liền kề hoặc trả INSUFFICIENT_STRUCTURE.
- Cấu trúc UP/DOWN và toàn bộ event lịch sử được bảo toàn.

KẾT THÚC TÀI LIỆU
```
