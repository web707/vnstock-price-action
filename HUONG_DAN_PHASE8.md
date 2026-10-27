# QuantumTrade AI — Phase 8

Bản nâng cấp từ Phase 7, ưu tiên kiểm chứng và minh bạch. Đây là công cụ nghiên cứu, chưa chứng minh dự báo chính xác hơn hay có lợi nhuận sau thực thi. Kết quả chạy thật nằm trong `validation_phase8/` và `PHASE8_VALIDATION.json`. Không dùng các số liệu thử nghiệm từ lượt làm việc cũ.

## 1. Cài đặt Windows

1. Giải nén **toàn bộ** `vnstock-qta-phase8-full.zip` vào thư mục mới, ví dụ `C:\QTA\Phase8`. ZIP có `requirements.txt`, `SETUP_QTA.bat`, `START_QTA.bat`, `web_app.py` ngay cấp gốc, không lồng thêm thư mục.
2. Cần Python 3.12 64-bit, bật Add Python to PATH. Nếu `python --version` mở Microsoft Store, cài Python thật và tắt alias giả trong App execution aliases.
3. Chạy `SETUP_QTA.bat` lần đầu. Script tạo `.venv`, cài requirements, rồi gọi START. Lần sau chạy `START_QTA.bat`.
4. Mở `http://127.0.0.1:8000/phase8` (hoặc cổng hiển thị trong terminal). Đăng ký tài khoản nếu chưa có; không có tài khoản/mật khẩu mặc định.
5. Giao diện `/phase7` và `/` vẫn giữ chức năng cũ: biểu đồ, danh mục, watchlist, cảnh báo, nhật ký, PDF/CSV, so sánh mã, nhiều khung thời gian.

PowerShell, mỗi lệnh một dòng:

```powershell
cd C:\QTA\Phase8
.\SETUP_QTA.bat
# Các lần sau:
.\START_QTA.bat
```

Nếu dùng database cá nhân mới hơn gói: dừng QTA và mọi tiến trình ghi, sao lưu thư mục cũ, chép database đó vào `data\state\qta_phase3_test.db` trong thư mục mới **trước khi START**. Giữ nguyên `.env`, auth DB và user DB cũ theo đường dẫn cấu hình; không chép đè chúng bằng dữ liệu test. Gói không chứa tài khoản cá nhân hay mật khẩu.

**Đã chạy Python/Linux và Chromium headless. Chưa chạy SETUP/START trên Windows thật.** BAT được giữ CRLF, tìm Python bằng FIND_PYTHON, dùng môi trường ảo và dừng khi migration/audit lỗi.

## 2. Bảo toàn database

Database kèm ZIP là bản Phase 7 **nguyên byte, chưa migration**, gồm 1.253.257 dòng giá, 1.579 mã danh mục, 5.323 sự kiện. SHA-256:

`2aaa3f476377b76d3abb1cdffbe03ebfba0b134ef3ed1934407f6db500c14768`

START gọi `phase8_data.py` trước audit. Migration giữ khóa ghi `BEGIN IMMEDIATE`, tạo snapshot SQLite backup, kiểm tra integrity, rồi mới thêm bảng `QTA8_*` trong transaction. Không xóa/đổi tên bảng cũ. Lỗi giữa chừng rollback. Chạy lại không lặp schema. Backup ở `data/state/backups/`. Backup được kiểm tra logic/nội dung; SQLite có thể thay đổi header nên không đòi backup giống byte với file nguồn.

Importer tạo backup trước mỗi đợt thay đổi; dòng giống hệt được bỏ qua. Không ghi đè một khóa có dữ liệu khác trừ khi truyền `--allow-revisions`. Tính đúng của nguồn CSV vẫn là trách nhiệm kiểm tra nguồn; schema validation không chứng minh nguồn đáng tin.

Khôi phục: dừng server, đóng mọi kết nối ghi; giữ riêng file hiện tại và các sidecar `-wal`/`-shm` nếu có; dùng bản backup đã kiểm tra để thay database khi không còn tiến trình sử dụng. Không ghi đè database đang mở. Cache `qta8_cache.db` và registry `qta8_research.db` tách khỏi database giá.

## 3. Nhập dữ liệu có nguồn, tăng dần

CSV UTF-8, ngày `YYYY-MM-DD`, tiêu đề đúng mẫu trong `data/reference8/templates/`.

| Kind | Cột bắt buộc | Ý nghĩa |
|---|---|---|
| prices | symbol,date,open,high,low,close,volume,basis,source,known_at | Chỉ chấp nhận `basis=RAW_VND`; giá gốc đồng/cổ phiếu, volume cổ phiếu |
| universe | security_id,symbol,exchange,sector,valid_from,valid_to,known_at,source | Mã định danh ổn định; mỗi khoảng hiệu lực một dòng; valid_to rỗng = mở; sector rỗng = chưa phân loại |
| actions | symbol,ex_date,kind,value,subscription_price,available_date,known_at,source | CASH/BONUS/SPLIT/RIGHTS; ngày tiền/cổ phiếu thực sự khả dụng |
| benchmarks | symbol,date,close,source,known_at | VNINDEX, VN30, HNXINDEX; close tính bằng điểm |
| calendar | date,source | Lịch phiên/settlement đã kiểm chứng, gồm cả ngày đến hạn sau giao dịch |
| limits | symbol,date,floor,ceiling,source | Giá sàn/trần thực tế từng ngày; không tự suy ra từ giá điều chỉnh |
| coverage | scope,symbol,start,end,source | Khai báo độ phủ ACTIONS cho từng mã; UNIVERSE/ALL cho toàn universe |

`known_at` là ngày thông tin thực sự sẵn có, **không được lùi ngày giả** để vượt kiểm soát. Nghiên cứu RAW chỉ dùng dòng `known_at <= date`; dữ liệu chỉ biết muộn bị loại để tránh dùng bản sửa hồi tố như giá đã biết. Benchmark tải lại hôm nay chưa chứng minh có cùng vintage như lịch sử.

```powershell
.\.venv\Scripts\python.exe phase8_data.py --db data\state\qta_phase3_test.db --kind prices --csv prices.csv
.\.venv\Scripts\python.exe phase8_data.py --kind universe --csv universe.csv
.\.venv\Scripts\python.exe phase8_data.py --kind actions --csv actions.csv
.\.venv\Scripts\python.exe phase8_data.py --kind benchmarks --csv benchmarks.csv
.\.venv\Scripts\python.exe phase8_data.py --plan
```

Nhập chỉ những dòng mới. Kế hoạch cập nhật xuất ngày bắt đầu = ngày cuối + 1; chưa tự động tìm và lấp mọi lỗ lịch sử. Khi có quyền hoặc revision, cần tải/kiểm tra lại vùng bị ảnh hưởng rồi dùng `--allow-revisions`. Giá RAW nằm riêng, không nối tùy tiện với giá legacy chưa rõ đơn vị. Có RAW cho một mã thì module mới sử dụng riêng lịch sử RAW của mã đó; lịch sử quá ngắn sẽ thiếu mẫu, không âm thầm trộn nguồn.

Adapter tùy chọn `fetch_phase8_benchmarks.py` theo tài liệu Vnstock v5, mặc định chỉ lưu CSV vào `data/inbox8`, `--apply` mới nhập có backup. Tải tăng dần từ ngày cuối của từng chỉ số. Không đưa thư viện này vào requirements bắt buộc vì môi trường kiểm thử không cài được vnstock>=5: **0 dòng benchmark mới đã tải**. Không khẳng định API live hoạt động.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-provider.txt
.\.venv\Scripts\python.exe fetch_phase8_benchmarks.py
# Đọc CSV và kiểm chứng trước khi nhập:
.\.venv\Scripts\python.exe fetch_phase8_benchmarks.py --apply
```

Nếu nhà cung cấp không khả dụng, nhận `PROVIDER_UNAVAILABLE`/`FETCH_FAILED`, không tạo giá thay thế. Có thể nhập CSV từ nguồn được cấp quyền. Vnstock mô tả giá cổ phiếu đã điều chỉnh và tính bằng nghìn đồng: **không được đổi tên cột rồi nhập làm RAW_VND**.

## 4. Điều chỉnh, universe và sức khỏe dữ liệu

- Cờ OHLC không hợp lệ, NaN/inf, volume âm; volume=0 được giữ để phản ánh không có giao dịch, nhưng cảnh báo và chặn suy luận khớp lệnh.
- Nhảy giá trên 20% chỉ là cờ rà soát. Không tự suy luận chia tách/cổ tức.
- `adjusted()` giữ giá gốc và thêm `adj_open/high/low/close`. Bản backward dùng để xem lịch sử theo as-of; không dùng bản backward đã biết tương lai để huấn luyện.
- Causal research rescale từ ex-date trở đi, không sửa prefix quá khứ: SPLIT hệ số 1/ratio; BONUS 1/(1+ratio); CASH (P−cash)/P; RIGHTS (P+ratio×subscription)/(P×(1+ratio)). Đây là chuẩn hóa nghiên cứu, không thay sổ dòng tiền quyền trong engine.
- CASH value = đồng/cổ phiếu; BONUS/RIGHTS value = cổ phiếu mới/cổ phiếu cũ; SPLIT value = tổng cổ phiếu mới/cổ phiếu cũ. Một sự kiện/mã/ex-date; quyền kết hợp cùng ngày chưa hỗ trợ, phải chuẩn hóa có kiểm chứng trước. Cổ phiếu lẻ/cash-in-lieu chưa hỗ trợ.
- Universe lọc `valid_from <= date <= valid_to` và `known_at <= date`. Có thể lưu mã hủy niêm yết/đổi tên/đổi sàn bằng cùng security_id. Không tự dựng lịch sử từ danh mục hiện tại, không tự đoán ngành.
- Universe chưa đủ: liệt kê mã, giai đoạn, số dòng chưa có PIT; ảnh hưởng survivorship bias **chưa lượng hóa**. Chưa tự chuyển vị thế qua đổi mã hay tính recovery hủy niêm yết.
- Sức khỏe dữ liệu có mã/năm, tuổi dữ liệu, volume=0, lỗi giá, nhảy giá, số RAW nhập, khoảng trống universe và preview điều chỉnh. Phiên thiếu là `null` nếu chưa có lịch; có lịch thì chỉ tính giữa phiên đầu/cuối quan sát, chưa chứng minh phủ cả thời gian niêm yết. Có CSV toàn bộ.
- RS thị trường yêu cầu hai ngày giá khớp VNINDEX; thiếu thì để trống. RS ngành là đối chiếu trung bình các mã cùng ngành/ngày có dữ liệu, chưa là chỉ số ngành đầy đủ. VN30/HNXINDEX có schema/adapter nhập, chưa có màn hình RS riêng cho cả ba benchmark.

## 5. Kiểm chứng OOS

Pooled Logistic Regression L2, 12 chỉ báo Phase 7; chuẩn hóa/impute chỉ fit train. Calibration logistic riêng fit validation, không fit test. Mỗi ngày có tổng trọng số như nhau để nhiều mã cùng ngày không lấn át hoàn toàn.

Mặc định: 6 mã HPG/FPT/VNM/VCB/SSI/MWG; horizon 10; C=1; ngưỡng .55; train 1260 phiên chung, validation/test 252; expanding hoặc rolling; embargo >= horizon. Purging dùng ngày kết thúc nhãn thực tế, không chỉ số dòng. Grid tín hiệu theo lịch chung cách horizon phiên; còn tương quan giữa mã, giữa ngày và nhãn kéo dài khi mã thiếu phiên. Không gọi số dòng OOS là số mẫu độc lập.

Eligibility giữ tiêu chuẩn Phase 7: 20 dòng liên tiếp QUALITY_STATUS=VALID và volume>0, MA200 sẵn có. Nhãn open phiên kế tiếp đến close H phiên, có giả định phí/trượt giá cố định của Phase 7. Giữ và đếm nhãn có volume vào/ra=0; đây không phải lợi nhuận khớp được. Module nhãn **chưa nối end-to-end với engine thực thi**.

Đối chứng: VNINDEX cùng cửa sổ nếu có; mua tất cả mã đủ điều kiện cùng cửa sổ; MA50 cùng ngày có vị thế; hoán vị chọn mã trong ngày giữ cùng số tín hiệu. Mua-giữ từng mã trong kỳ OOS và toàn lịch sử báo riêng, không đem khác kỳ làm kiểm định ngang bằng. VNINDEX mua-giữ close-to-close khác giả định vào open được gắn nhãn.

Bootstrap khối ngày vòng tròn (1000 lần, seed 7, block sqrt(N)) cho CI chênh lệch. CI95 là mô tả chưa chỉnh multiple testing; p-value điều chỉnh Bonferroni cho 4 phép so sánh × số cấu hình/dataset đã ghi registry. Hoán vị cần giả định các mã có thể hoán đổi có điều kiện; không phải kiểm định mọi giả thuyết về hiệu quả. Registry không biết những lần thử ngoài máy hay registry bị xóa.

Ba mức duy nhất: **Có bằng chứng / Chưa đủ bằng chứng / Bằng chứng ngược**. Điều kiện để đưa ra kết luận mạnh còn yêu cầu đủ dữ liệu RAW/PIT/quyền/benchmark và >=100 cụm ngày ở các phép so sánh. Báo strata theo chế độ, ngành, thanh khoản; nếu giá chưa rõ đơn vị thì thanh khoản ghi chưa rõ, không phân nhóm giả.

Không xuất xác suất nếu thiếu dữ liệu bắt buộc, <100 cụm ngày, bin calibration <30 cụm ngày, chỉ báo mới thiếu hoặc mô hình quá 252 phiên từ ngày cuối đã biết nhãn validation. Đóng góp log-odds là giải thích mô hình, không chứng minh nhân quả. Khoảng tần suất lịch sử không phải khoảng dự báo cá nhân.

Kết quả thực tế mặc định: **873 dòng OOS / 154 cụm ngày / 181 tín hiệu chọn**. Đối chứng VNINDEX có **0 ngày khớp**. Đối chứng eligible buy-hold 48 ngày, MA50 42 ngày, permutation 26 ngày: đều dưới ngưỡng 100. Có 98 nhãn volume thực thi bằng 0. Không đủ bằng chứng hiệu quả. Xem JSON để biết mốc đóng băng mô hình/tuổi chính xác và từng fold.

## 6. Engine thực thi

`src.phase8.execution.replay` nhận bars, lịch lệnh ngoại sinh, lịch phiên, universe và actions. `compare` chạy cùng lịch lệnh với hai chế độ lý tưởng/thực thi; không phải hai chiến lược tự tối ưu lại.

- Chỉ cho signal_date trước ngày thực hiện. Lô mua/bán 100. HOSE ticks 10/50/100 theo tầng giá, HNX/UPCOM 100; đây là profile hiện tại, **chưa phải rulebook lịch sử**. Trần/sàn phải được nhập thực tế từng ngày, không dùng ±7/10/15% thay trường hợp đặc biệt.
- T+2 PM theo lịch đã nhập. Nếu chỉ có nến ngày OPEN, bán tại open sớm nhất T+3; không giả giá open T+2 là sau settlement. Tiền bán là khoản phải thu, chưa dùng mua cho đến khi đến hạn.
- Không trộn OPEN cả ngày với AM/PM cùng mã/ngày. Khóa trần không mua/khóa sàn không bán; fill nằm trong OHLC và trần/sàn. Tick làm tròn bất lợi. Lệnh còn dư bị hủy, không tự treo qua ngày.
- Participation mặc định 1% volume phiên, tổng hợp nhiều lệnh cùng mã/phiên. Trượt giá = base + impact × sqrt(qty/volume). Dùng volume cuối phiên là giả định capacity, không phải mô phỏng hàng đợi intraday.
- `Costs` cấu hình fee, sell tax, custody/month/share, margin annual, margin limit, slip base/impact, participation. Mặc định fee .15%, sell tax .1%, margin tắt; chỉ là tham số giả định, không báo giá broker. Margin/custody tính trên NAV theo ngày lịch; profit factor lệnh chưa phân bổ toàn bộ các khoản này.
- CASH ghi khoản phải thu đến available_date; SPLIT đổi số lượng và cost; BONUS chờ khả dụng; RIGHTS lựa chọn thực hiện khi đủ tiền hoặc bỏ quyền có ghi nhận. Chưa xử lý cash-in-lieu, thuế cổ tức riêng, entitlement phức tạp, quyền kết hợp, vị thế qua đổi mã, recovery hủy niêm yết.
- UI kiểm tra dữ liệu rồi chạy lịch lệnh MA50 fixed100. Chi phí tùy chỉnh qua Python API, chưa có toàn bộ form cấu hình trên web.

Database kèm gói **chưa đủ đầu vào**, nên UI thực thi trả BLOCKED. Logic engine được kiểm thử bằng fixture, chưa xác minh với sao kê broker hoặc dữ liệu phiên chiều thực tế.

## 7. Hiệu năng và tương thích

Cùng máy Linux, 407 mã, 1,25 triệu dòng giá:

| Phép đo | Giây |
|---|---:|
| Phase 7 dashboard | 20,889 |
| Phase 8 chưa có cache ứng dụng | 2,837 |
| Phase 8 cache từng mã trên đĩa | 2,193 |

Không xóa OS file cache; không gồm download, startup, migration/audit. Không bảo đảm <5 giây trên mọi PC. Tính chỉ báo NumPy/SciPy; hash và cache theo mã + lịch sử + phiên bản thuật toán. Chỉ tính lại mã thay đổi; **chưa cập nhật riêng suffix của chuỗi chỉ báo**, vẫn đọc/hash toàn lịch sử khi cache tổng hết hiệu lực. Có cache bộ nhớ khi database không đổi; không dùng cache bộ nhớ khi SQLite WAL/journal đang có dữ liệu.

Đối chiếu 407 mã: sai số chỉ báo ở mức số thực ~1e-11 hoặc nhỏ hơn. Một thay đổi có chủ ý: VSI từ 50 xuống 37,5 vì Phase 7 nhận flow A/D ~1,98e-14 là dương; Phase 8 coi |flow|<1e-10 là 0. Phase 7 cũ giữ nguyên.

```powershell
.\.venv\Scripts\python.exe benchmark_phase8.py --db data\state\qta_phase3_test.db
```

## 8. Kiểm thử và giới hạn

Đọc số đếm cuối trong `PHASE8_VALIDATION.json`, log pytest, Chromium, migration, benchmark, OOS và provider trong `validation_phase8/`. Unit tests mới bao gồm migration/rollback/backup, revisions, PIT đổi mã/hủy niêm yết, điều chỉnh và bất biến prefix, purging/embargo, OOS window không đổi khi sửa tương lai, permutation, multiple testing, T+2/tiền về, ticks/khóa giá/volume cap, quyền, chi phí và cache.

Tests cũ cần database giá thật trong gói; chạy trên **bản sao**, không dùng database đang giao dịch:

```powershell
Copy-Item data\state\qta_phase3_test.db $env:TEMP\qta8-test.db
$env:QTA_PRICE_DB="$env:TEMP\qta8-test.db"
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe tests\browser\phase8_smoke.py
```

Browser test tạo tài khoản test tạm, kiểm tra 407 mã, filter persistence, dialog, OOS, health, CSV, strict block, light/dark và viewport390. Không phải kiểm thử mọi thiết bị hay mọi endpoint cũ. Scripts smoke dùng đường dẫn mặc định `/tmp` cho output trên Linux; trên Windows đặt `QTA_BROWSER_OUTPUT` thành thư mục tạm phù hợp.

Các khoảng trống còn lại quan trọng: chưa có lịch sử nguồn có license đầy đủ; chưa loại trừ survivorship bias; chưa có benchmark tải thành công; chưa có backtest model→engine hoàn chỉnh; chưa có rulebook lịch sử; chưa có Windows CI thực tế. Gói không tuyên bố đáp ứng hoàn toàn các mục này chỉ bằng schema/test fixture.

## 9. Phase 9 đề xuất

1. Kết nối nguồn được cấp quyền cho RAW, quyền, lịch niêm yết/đổi mã/hủy niêm yết, chỉ số; lưu vintage và kiểm tra chéo nguồn.
2. Nối pipeline model OOS → lệnh → engine, cùng giả định với VNINDEX/MA/random; nested walk-forward, risk-adjusted portfolio benchmark và CI sau chi phí.
3. Rulebook theo ngày hiệu lực, dữ liệu intraday/auction, corporate actions đầy đủ, xử lý đổi mã và hủy niêm yết.
4. Windows CI cài từ ZIP trên Python3.12, test restore/migration khi bị ngắt; cache suffix và benchmark trên máy yếu.

## Nguồn quy tắc/tài liệu đã tham khảo

- VSDC: https://vsdc.vn/vi/ad/152750 — thanh toán chiều T+2, hiệu lực từ 29/8/2022; không suy diễn cho toàn lịch sử trước đó.
- VNDIRECT: https://support.vndirect.com.vn/hc/vi/articles/360002192174-Quy-định-giao-dịch-tại-sàn-HSX — bước giá/lô và giao dịch; cần đối chiếu phiên bản hiệu lực khi backtest.
- Vnstock: https://vnstocks.com/docs/vnstock/thi-truong-market — Market.index OHLCV, đơn vị, adjusted equity và giới hạn lịch sử.

Đây là phân tích thuật toán, không phải lời khuyên đầu tư.
