# QuantumTrade AI — Phase 7

Bản phát hành nghiên cứu ngày 26/10/2026, nâng cấp trực tiếp từ Phase 6. Ưu tiên khả năng kiểm tra và quyền từ chối kết luận. **Chưa có bằng chứng dự báo chính xác hơn hoặc thắng VN-Index ngoài mẫu.**

## 1. Chạy trên Windows

1. Giải nén **toàn bộ ZIP** vào một thư mục mới, ví dụ `C:\QTA_Phase7`. Không chạy BAT ngay bên trong cửa sổ ZIP. Cùng cấp với BAT phải có `requirements.txt`, `web_app.py`, `src` và `data`.
2. Cần Python 3.11 trở lên; khuyến nghị Python 3.12 64-bit. Khi cài Python chọn Add python.exe to PATH, mở lại CMD. `FIND_PYTHON.bat` thử `.venv`, `py -3.12`, `py -3`, rồi `python` và kiểm tra phiên bản thực sự; không chỉ kiểm tra tên lệnh.
3. Lần đầu bấm `SETUP_QTA.bat`. Script tạo môi trường `.venv`, cài requirements rồi gọi START. Cần Internet cho bước cài thư viện. Không có Python installer trong ZIP.
4. Những lần sau bấm `START_QTA.bat`. Script kiểm tra database trước khi mở web. Giữ cửa sổ console đang chạy. Đóng các tiến trình đang ghi database trong lúc audit.
5. Mở `http://127.0.0.1:8000/phase7`. Khi chưa đăng nhập sẽ chuyển đến trang đăng nhập. Tạo tài khoản nếu dùng thư mục mới; **không có tài khoản/mật khẩu mặc định**. Sau đăng nhập có thể mở link Phase 7 từ giao diện cũ.
6. Nút **Giao diện cũ** quay về `/`, giữ các chức năng Phase 6. Oracle chỉ dùng luồng cũ; API Phase 7 hiện yêu cầu SQLite.

Nếu phải nhập lệnh trong CMD, mỗi dòng là một lệnh riêng:

```bat
cd /d C:\QTA_Phase7
SETUP_QTA.bat
```

PowerShell:

```powershell
cd C:\QTA_Phase7
.\SETUP_QTA.bat
```

Chạy thủ công sau khi cài:

```bat
.venv\Scripts\python.exe web_app.py --price-db data\state\qta_phase3_test.db --no-browser
```

BAT đã được rà soát, **chưa chạy trên Windows thật trong phiên kiểm thử này**. Backend và trình duyệt đã chạy trên Linux/Python 3.12.

## 2. Bảo toàn dữ liệu và nâng cấp

ZIP có `data/state/qta_phase3_test.db`, 198.737.920 byte, giữ nguyên nội dung database giá từ Phase 6. SHA-256:

```
2aaa3f476377b76d3abb1cdffbe03ebfba0b134ef3ed1934407f6db500c14768
```

Phase 7 đọc giá bằng kết nối read-only. Không ALTER/DROP hoặc migrate database giá. Nhật ký, watchlist, trạng thái cảnh báo và bộ lọc nằm riêng ở `data/state/qta_phase7_users.db`, tạo khi cần. Tài khoản/phiên đăng nhập vẫn dùng cơ chế cũ, `qta_accounts.db`. Không kèm tài khoản kiểm thử trong ZIP.

Để giữ tài khoản hoặc dữ liệu cá nhân đã có, dừng ứng dụng cũ rồi sao lưu/copy các database tương ứng sang thư mục mới. Nếu database giá trên máy đã mới hơn bản ZIP, giữ database của bạn và dùng `--price-db` trỏ tới bản đó; đừng giải nén đè lên thư mục đang dùng. Biến môi trường: `QTA_PRICE_DB`, `QTA_AUTH_DB`, `QTA_USER_DB`, `QTA_REFERENCE_DIR`.

## 3. Các màn hình

- **Thị trường:** độ rộng MA50/MA200, số mã có/thiếu giá, chế độ chỉ số khi có OHLCV VN-Index, bảng điểm có lọc/sắp xếp/lưu bộ lọc theo tài khoản; ngành mạnh/yếu khi có phân ngành.
- **Hồ sơ mã:** biểu đồ nến 60/120/180 phiên, zoom bằng con lăn, hover OHLCV; MA20/MA50, hỗ trợ/kháng cự; điểm B/S của danh mục vừa chạy nếu nằm trong cửa sổ. Chỉ báo ngày và tuần đã đóng, so sánh 2–10 mã, tương quan Pearson và mức giá chuẩn hóa gốc 100.
- **Kiểm chứng OOS:** logistic L2, các fold, Brier raw/calibrated/prior, AUC, log loss, tần suất theo bin, Wilson 95%, đóng góp log-odds khi có dự báo đủ điều kiện. Mã lấy từ Hồ sơ mã.
- **Danh mục:** nhiều mã, vốn, trần tỷ trọng, rủi ro/lệnh và danh mục, bội ATR, chu kỳ thay tập mã, phí/thuế/trượt giá và trần thanh khoản. STRICT mặc định chặn thiếu tham chiếu; lựa chọn xấp xỉ phải bật rõ ràng.
- **Theo dõi & nhật ký:** thêm/bỏ watchlist, cảnh báo thay đổi regime/breakout/nhóm điểm. Poll mỗi 60 giây khi tab đang mở và trang hiển thị; không chạy nền khi đóng trình duyệt. Lần đầu chỉ ghi trạng thái, không tạo cảnh báo giả. Nhật ký nhập lệnh thật, lãi/lỗ ròng sau chi phí tự nhập và điểm trước ngày vào lệnh. Không gửi lệnh đến broker. Hiện ghi từng lệnh/roundtrip, chưa hỗ trợ sửa, khớp nhiều phần hay hạch toán tồn kho FIFO.
- **Sức khỏe dữ liệu:** OHLCV sai, zero volume, nguồn/nhãn, dữ liệu cũ, giá nhảy trên 20%, sự kiện cổ tức/chia tách. Chỉ xác định thiếu phiên nếu có calendar chính thức do người dùng cung cấp.

Xuất PDF/CSV cho mã hoặc toàn bộ bảng quét. “Toàn bộ” là tất cả mã có giá trong snapshot, **không áp dụng bộ lọc giao diện**; không phải toàn bộ thị trường Việt Nam. PDF có font Unicode Việt Nam đi kèm, không phụ thuộc CDN.

## 4. Định nghĩa thuật toán

### Chế độ, điểm kỹ thuật và cấu trúc

ADX sử dụng directional movement và Wilder smoothing; độ dốc MA50 là thay đổi trong 5 phiên. ATR14/close được xếp percentile trong 252 phiên (tối thiểu 60). HIGH_VOL khi percentile ≥90, UPTREND/DOWNTREND khi ADX ≥25 và slope50 vượt ±0,2%; còn lại SIDEWAYS. Thiếu lịch sử trả INSUFFICIENT. Bộ trọng số `[trend, momentum, flow, setup]`:

| Chế độ của mã | Trend | Momentum | Flow | Setup |
|---|---:|---:|---:|---:|
| UPTREND | 45% | 20% | 20% | 15% |
| DOWNTREND | 20% | 15% | 25% | 40% |
| SIDEWAYS | 15% | 30% | 25% | 30% |
| HIGH_VOL | 20% | 15% | 35% | 30% |

Điểm 0–100 là đồng thuận quy tắc, **không phải xác suất**. ADX khởi tạo theo chuỗi DX với giá trị thiếu ban đầu bằng 0; không cam kết giống từng chữ số với mọi nền tảng. Điểm thích nghi hiện dùng chế độ **từng mã**, chưa học trọng số theo chế độ chỉ số toàn thị trường. Khi có OHLCV VN-Index cùng ngày, dashboard tính regime chỉ số và gắn MIXED_INDEX_BREADTH nếu xu hướng chỉ số mâu thuẫn độ rộng trên MA50. Chưa dùng lịch sử breadth làm biến mô hình vì thiếu universe point-in-time.

- Dry-up: volume trung bình 5 phiên <60% trung bình 20 phiên trước 5 phiên đó.
- OBV theo dấu thay đổi close; A/D theo vị trí close trong high-low; high=low cho money flow 0. Flow chuẩn hóa theo tổng volume 20 phiên.
- Swing trái/phải 3 nến: xác nhận ở ngày có đủ 3 nến phải, không dời tín hiệu về ngày đỉnh/đáy. Trường hợp plateau có thể có nhiều xác nhận bằng nhau.
- Breakout: close vượt kháng cự đã biết, phiên trước chưa vượt, volume ≥1,5 lần TB20 trước phiên. Pullback: low chạm MA20, close lấy lại MA20 và nằm trên MA50.
- VCP là heuristic: độ rộng giá ba đoạn 10 phiên liên tiếp thu hẹp, không phải mẫu VCP chuyên gia xác nhận. Phân kỳ RSI/MACD so hai pivot đã xác nhận; không là điểm mua/bán bảo đảm.
- RS 20 phiên = lợi suất mã trừ lợi suất VN-Index trên đúng hai ngày; percentile trong tập mã cùng phiên có dữ liệu. Ngành dùng lợi suất bình quân đều của nhóm ít nhất hai mã, mapping ngành hiệu lực theo ngày. Không phải chỉ số ngành vốn hóa/thanh khoản chính thức.
- Khung tuần loại toàn bộ tuần đang diễn ra. Dữ liệu ngày hiện tại bị loại để tránh coi nến chưa đóng là dữ liệu hoàn chỉnh.

### Mô hình, calibration và kiểm chứng

12 biến trong `FEATURES`: return20, ma_gap, slope50, ADX, ATR fraction, volume ratio, OBV flow, A/D flow, RSI14, MACD/close, contraction, breakout. Logistic regularization L2; median imputer và scaler **fit train mà thôi**. Calibrator logistic chỉ fit validation, không fit test.

Sau warm-up 200 phiên: train ban đầu khoảng 800, validation 250, test 250; train mở rộng, test bước 250. Purge theo horizon 5/10/20 giữa train–validation và validation–test; ngày cuối nhãn phần trước nằm trước phần sau. Mẫu tín hiệu cách nhau horizon để tránh chồng lấn cùng fold.

Nhãn là lợi suất dương từ open phiên kế tiếp đến close H phiên, với giả định phí mỗi chiều 0,15%, thuế bán 0,1%, trượt giá mỗi chiều 0,1%. **Đây là nghiên cứu nhãn, không phải lệnh đã chạy qua engine danh mục.** Eligibility chỉ dựa trên thông tin tại ngày tín hiệu: 20 dòng VALID liên tiếp, volume dương, có MA200. Không bỏ mẫu OOS dựa vào volume tương lai; các mẫu có volume thực hiện bằng 0 vẫn được giữ và gắn cờ, nên lợi suất nhãn có thể không giao dịch được.

Cần tối thiểu 60 mẫu train, 20 validation, 5 test và hai lớp ở train/validation. Mẫu thiếu/one-class bị từ chối. Dự báo hiện tại bị từ chối nếu dữ liệu mới không đủ điều kiện hoặc mô hình cuối quá 252 phiên kể từ cuối validation. Không âm thầm dùng mô hình năm 2017 để đưa ra xác suất hôm nay.

Bins rộng 0,2, hiển thị xác suất TB, tần suất thật và Wilson 95%. Đây là khoảng bất định của **tần suất trong nhóm mẫu**, không phải khoảng dự báo riêng cho cổ phiếu. Ít hơn 30 mẫu trong bin hoặc tổng OOS <60 gắn LOW. Đóng góp là hệ số × biến chuẩn hóa × hệ số calibration, cộng intercept cho ra log-odds; không chứng minh nhân quả.

Sensitivity dùng C=0,1/1/10 trên cùng OOS, không tự chọn bộ có kết quả đẹp nhất. Monte Carlo resample theo block, 300 lượt, seed 7; cần ít nhất 20 lợi suất. Đây là chẩn đoán phân bố theo dữ liệu đã thấy, **chưa phải kiểm định thống kê loại trừ chiến lược ăn may**.

Tất cả kết quả hiện giữ nhãn **“chưa có bằng chứng hiệu quả”**. Trung bình vượt benchmark dương, nếu có, cũng chưa đủ để bỏ nhãn này. Chưa có universe point-in-time gồm mã hủy niêm yết và total return đã xác minh để loại trừ survivorship/corporate-action bias.

## 5. Giả định engine danh mục

Tín hiệu tạo sau close, lệnh chỉ có hiệu lực phiên kế tiếp. Không lấy giá close tương lai để tạo lệnh. Số cổ phiếu làm tròn lô 100, bị giới hạn bởi tiền mặt, trần tỷ trọng, rủi ro ATR + ước tính chi phí và volume. Trần volume = participation × min(TB20 đã biết, volume phiên thực hiện); volume thực hiện là kiểm tra khả năng khớp, không phải chứng minh khớp intraday.

Trailing stop cập nhật sau khi xử lý giao dịch ngày đó; không dùng close hôm nay để đặt stop cho low trước đó trong cùng phiên. Khi thiếu thanh khoản có thể bán từng phần. Giá khóa trần chặn mua, khóa sàn chặn bán theo quy tắc mô phỏng. Không giả định luôn khớp stop.

T+2 được mô phỏng **bảo thủ**: bán chứng khoán và tái dùng tiền ở open T+3; chưa mô phỏng buổi chiều T+2. Cash chờ thanh toán tính vào NAV nhưng không dùng để mua. Không tự đóng vị thế cuối dữ liệu. Vị thế thiếu giá giữ mark gần nhất nên NAV có thể cũ.

Rebalance hiện thay tập mã theo điểm, không bán/mua ép mọi vị thế về tỷ trọng mục tiêu. Trần tỷ trọng và rủi ro áp dụng lúc mở; có thể vượt sau biến động/gap. Tương quan được xem ở công cụ so sánh, chưa là ràng buộc tối ưu danh mục.

STRICT cần calendar, limits theo từng ngày/mã và khai báo units RAW/VND. Không có limits đúng ngày sẽ bỏ khớp lệnh. Đây là **strict về tham chiếu đã cung cấp**, không là chứng nhận khớp đúng mọi quy chế sở/broker. Chưa tick size, room, ATO/ATC, margin, listing exception, quyền/cổ tức/chia tách hoặc tiền thuế khác.

APPROXIMATE dùng close trước × biên độ giả định HOSE 7%, HNX 10%, UPCoM 15%; có thể sai tham chiếu UPCoM/ngày quyền/ngày niêm yết mới. Phải chọn rõ chế độ này. Phí/thuế trên màn hình là giả định chỉnh được, không tự nhận là biểu phí hiện hành của mọi tài khoản.

Chỉ số: total return, CAGR (chỉ khi đủ 1 năm), Sharpe/Sortino annualize 252, risk-free=0; max drawdown; profit factor/expectancy/win rate/thời gian giữ theo các lần đóng lệnh, kể cả bán phần. Không có lệnh lỗ thì profit factor là null, không tạo vô cực. Benchmark là VN-Index price index close-to-close chưa phí/cổ tức, chỉ hiện khi đủ ngày; không dùng VN-Index giả thay dữ liệu thiếu. Danh mục quy tắc không được gọi là OOS của logistic.

## 6. Bổ sung dữ liệu tham chiếu

Trong ZIP chỉ có **template rỗng**, không có số liệu benchmark/sector giả. Đặt CSV thật vào đường dẫn riêng rồi chạy importer, ví dụ:

```bat
.venv\Scripts\python.exe import_phase7_reference.py benchmark C:\DuLieu\benchmark.csv
.venv\Scripts\python.exe import_phase7_reference.py calendar C:\DuLieu\calendar.csv
.venv\Scripts\python.exe import_phase7_reference.py limits C:\DuLieu\limits.csv
.venv\Scripts\python.exe import_phase7_reference.py sectors C:\DuLieu\sectors.csv
.venv\Scripts\python.exe import_phase7_reference.py units C:\DuLieu\units.csv
```

| File | Cột bắt buộc | Ghi chú |
|---|---|---|
| benchmark.csv | DATE,CLOSE,SOURCE | VN-Index; thêm OPEN,HIGH,LOW,VOLUME để nhận diện regime chỉ số |
| calendar.csv | DATE,SOURCE | Ngày giao dịch thực tế, không phải lịch weekday tự sinh |
| limits.csv | DATE,SYMBOL,FLOOR,CEILING,SOURCE | Giá sàn/trần thực tế theo ngày, gồm ngoại lệ |
| sectors.csv | SYMBOL,SECTOR,VALID_FROM,VALID_TO,SOURCE | Khoảng hiệu lực không chồng lấn; VALID_TO trống = còn hiệu lực |
| units.csv | SYMBOL,UNIT,BASIS,SOURCE | UNIT=VND, BASIS=RAW; chỉ khai báo sau khi đối chiếu thật |

Ngày ISO YYYY-MM-DD. SOURCE không được trống, nên ghi nguồn và ngày truy xuất. Importer kiểm tra cấu trúc, số hữu hạn, trùng khóa, giới hạn và khoảng ngành trước khi ghi vào `data/reference`. Khai báo SOURCE **không đồng nghĩa QTA đã xác minh nhà cung cấp**. Không đổi nhãn giá để vượt cổng STRICT khi chưa có cơ sở.

## 7. Kiểm thử và kết quả thực tế

Xem `PHASE7_VALIDATION.json`, `PHASE7_CHANGELOG.md` và `validation_phase7/` cho kết quả. Bộ test mới gồm kiểm tra causal prefix/pivot, no-Inf khi zero volume/flat price, tuần đóng, purge/frozen OOS, contribution sum, abstention, settlement, locked ceiling, limits thiếu, NAV prefix, metrics/Monte Carlo, phân tách user, alert dedup, references, PDF/CSV, RS/ngành/breadth/health, auth/CSRF, dry-up/breakout và OHLCV hỏng.

Lượt kiểm thử toàn bộ ban đầu thiếu database fixture: 174 đạt, 4 fail, 7 error. Sau trỏ `QTA_PRICE_DB` đến **bản sao database đi kèm**, 185/185 đạt. Sau bổ sung ba test mới, lượt toàn bộ cuối cùng đạt **188/188 trong 28,30 giây**, tổng test Phase 7 17/17. Không sửa assert để che lỗi dữ liệu fixture.

Playwright Chromium headless đã chạy thật: đăng nhập API, quét, filter/persistence, nến/zoom, watchlist, walk-forward + sensitivity, STRICT gate, approximate portfolio, nhật ký, poll alerts, health, so sánh, PDF download, đổi theme, không tràn ngang mobile. Desktop 1440×1000, mobile 390×844; không có page error. Đã xem ảnh giao diện và render PDF kiểm tra tiếng Việt/bố cục. Không thay thế kiểm thử trên Windows hoặc mọi trình duyệt.

Đo một lượt riêng trên snapshot 407 mã: cold 21,83 giây; warm cache 0,0032 giây. Lượt chạy trình duyệt song song tác vụ khác khoảng 26,7 giây. **Chưa đạt quét cold toàn thị trường trong vài giây.** Cache theo revision file, TTL 120 giây và thay đổi CSV; không đồng nghĩa dữ liệu live. Không cắt lịch sử để làm đẹp benchmark tốc độ.

HPG và FPT mỗi mã có 16 mẫu OOS đạt điều kiện; Brier lần lượt khoảng 0,2860 và 0,2707. Model đủ điều kiện cuối ở validation tháng 01/2017; hiện từ chối xuất xác suất. AAV thiếu mẫu đủ chuẩn. Nhiều nhãn zero-volume làm các cửa sổ sạch không đủ mẫu calibration; hệ thống không hạ điều kiện chỉ để tạo kết quả. Backtest HPG/FPT xấp xỉ có 134 lần đóng lệnh, không là bằng chứng hiệu quả.

Database có 1.579 mã danh mục, 407 mã có giá, phiên mới nhất 21/10/2026. Thiếu VN-Index, lịch ngành/universe lịch sử và bộ tham chiếu chuẩn. Những mục cần chúng hiển thị thiếu dữ liệu, không tự suy đoán.

Để tự kiểm thử (dùng **bản sao** DB vì một số test cũ có ghi dữ liệu):

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy data\state\qta_phase3_test.db data\state\qta_test_copy.db
set QTA_PRICE_DB=data\state\qta_test_copy.db
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe tests\browser\phase7_smoke.py
```

## 8. Phase 8 đề xuất

1. Ưu tiên dữ liệu: VN-Index và total return, lịch phiên/giá tham chiếu chính thức, corporate actions được đối chiếu, universe point-in-time kể cả mã hủy niêm yết. Giải quyết zero-volume/nguồn hỗn hợp trước khi tăng độ phức tạp mô hình.
2. Nested walk-forward chọn tham số bên trong train; kiểm định benchmark với block bootstrap/deflated Sharpe hoặc phương pháp có kiểm soát multiple testing; đánh giá calibration theo thời kỳ và regime.
3. Đồng bộ cùng một policy từ dự báo → quyết định → engine danh mục OOS; thực thi intraday T+2, tick size, settlement calendar, quyền và partial fills.
4. Cache incremental/persisted features, xử lý theo cột toàn thị trường và background jobs; đo cold/warm trên Windows chuẩn với ngân sách thời gian cụ thể.
5. Portfolio constraints theo ngành/tương quan, rebalance về target weights, nhật ký sửa/đóng từng phần, import sao kê broker và cảnh báo nền có opt-in.

Đây là phân tích thuật toán, không phải lời khuyên đầu tư.
