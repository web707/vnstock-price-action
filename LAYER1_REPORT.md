> Bổ sung schema output: xem LAYER1_SCHEMA_CHANGELOG.md. Bản 1.1.0 đổi tên cột và metadata;
> bảng so sánh/269 tests dưới đây là báo cáo thuật toán ở bản trước. Kiểm chứng schema mới
> được báo riêng, không cộng dồn số test hai lượt.

# Báo cáo sửa Layer 1 — QTA Phase 8

Ngày lập: 29/10/2026, giờ Việt Nam. Kết quả dưới đây được chạy lại trên bản code đóng gói
trong ZIP này sau khi môi trường phiên trước bị mất. Không sử dụng lại các số 270 tests,
351/333 swings hoặc kết quả so sánh của lần làm trước.

## 1. Đã thay đổi và giữ nguyên

- Viết lại `swing_detector/atr.py`, `detector.py`, `__init__.py`; thêm `config.py`, `io.py`.
- Giữ code cũ tại `swing_detector_old/`; chỉ đổi import nội bộ sang package cũ để giữ ATR cũ.
- Thêm `layer1_cli.py`, 3 công cụ fetch/compare/prefix trong `tools/`, 34 ca test mới,
  README, báo cáo, CSV nguồn/kết quả, trace và biểu đồ.
- Chỉ sửa test kiến trúc số 11 để đối chiếu **detector lưu trữ** với legacy monolithic.
  Không ép detector mới phải cho cùng kết quả thuật toán cũ; các test Layer 2 giữ nguyên.
- Toàn bộ `structure_builder/`, `common/`, `src/strategy/`, database và BAT giữ nguyên hash.
  Chi tiết: `reports/layer1/scope_integrity.json`. Không migration hay ghi database.
- `run_pipeline.py` dùng package mới qua adapter tương thích. Web/`inspect_swings.py`
  còn gọi thuật toán monolithic cũ thì **chưa chuyển sang detector mới**; không sửa ngoài phạm vi.

## 2. Nguồn và độ đầy đủ dữ liệu

Tải thực tế từ yfinance HPG.VN, FPT.VN, VNM.VN, VCB.VN, SSI.VN với period=60d,
interval=15m, auto_adjust=False. CSV nguồn, thời điểm tải, hash SHA256 và lỗi/warning ở
`reports/layer1/fetched/` và `fetch.log`. Không dùng dữ liệu giả cho so sánh thị trường.
Dữ liệu giả chỉ dùng unit test.

Provider trả về từ 07/08/2026 đến 29/10/2026 10:45+07. Phép so sánh cắt ở
**28/10/2026 15:00+07** để loại phiên ngày 29 đang chạy: 56 ngày có dữ liệu/mã.
Khoảng ngày trả về không tương đương chính xác 60 ngày lịch; chưa xác minh độc lập phạm vi
retention hay từng nến với sở giao dịch. `auto_adjust=False` không chứng minh giá hoàn toàn
chưa điều chỉnh: nguồn có giá lẻ, không có hồ sơ quyền đầy đủ để kiểm tra.

| Mã | Dòng tải về | Nến sạch dùng so sánh | Dòng lỗi bị loại trước cutoff | Slot có thể thiếu theo template |
|---|---:|---:|---:|---:|
| HPG | 903 | 896 | 0 | 165 |
| FPT | 905 | 896 | 2 | 165 |
| VNM | 903 | 896 | 0 | 165 |
| VCB | 904 | 897 | 0 | 164 |
| SSI | 906 | 897 | 2 | 164 |

Mỗi mã còn 7 nến ngày 29/10 bị loại bởi cutoff, không tính là nến lỗi. FPT và SSI mỗi mã
có 1 dòng thiếu/nonfinite và 1 dòng ngoài phiên bị loại có log. Tổng dùng so sánh: 4.482 nến.
Slot thiếu dựa trên template thứ Hai–thứ Sáu, 09:00–11:30/13:00–15:00, **không phải lịch
sở giao dịch**, nên không thể khẳng định 164–165 slot thực sự bị mất. Không tự lấp nến.
Snapshot HPG gốc đi kèm có 912 nến, 28/07–19/10/2026, so sánh riêng: cũ 64, mới 61.
Không cộng snapshot trùng mã này vào bảng pooled 5 mã.

## 3. Cấu hình cơ sở và quyết định triển khai

Giữ nguyên: 15m, Wilder ATR14, pivot 3/3, k=2.0, floor=0.5% giá,
min_bars_between_swings=0, volume_lookback=20, tie_rule=first.

Các lựa chọn đã ghi rõ trong config/docstring/README:

1. ATR_i là ATR của **nến cực trị**; ứng viên và T không thay theo ATR tương lai.
2. First-tie trong toàn cửa sổ trái, không chỉ cụm liền nhau. Chỉ theo dõi ứng viên đạt
   điều kiện trái; phải chờ đủ cửa sổ phải mới xác nhận.
3. Khi pivot sẵn sàng, nến hiện tại vẫn phải đạt ngưỡng đảo chiều; không hồi tố lần chạm cũ.
4. Outside bar đủ lớn hoặc INIT hai hướng cùng đạt: hoãn xác nhận. Tối đa 1 swing/nến.
5. `volume_ratio` dùng tổng volume nhịp đảo chiều / median 20 nến trước cực trị; chỉ xếp hạng.
6. Timestamp mặc định là nhãn đầu nến; `confirm_time` là nhãn +15 phút. Đây là giả định
   cấu hình cần đối chiếu provider, không phải xác minh rằng Yahoo chắc chắn dùng nhãn đầu.

Đọc README trước khi đổi timestamp_label, phiên hoặc quy tắc tie. Hai thời gian canonical
được giữ riêng; không dùng giá cực trị để giả định khớp lệnh tại confirm_time.

## 4. Bảng cũ/mới — cùng dữ liệu sạch, cùng k và cửa sổ

| symbol | version | count | swings_per_session | median_leg_ATR | median_delay_bars | median_spacing_bars | noise_legs_lt1ATR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HPG | old | 62 | 1.107 | 3.693 | 5.000 | 14.000 | 0 |
| HPG | new | 57 | 1.018 | 3.717 | 5.000 | 15.000 | 1 |
| FPT | old | 63 | 1.125 | 4.995 | 3.000 | 13.500 | 0 |
| FPT | new | 57 | 1.018 | 5.070 | 3.000 | 15.000 | 0 |
| VNM | old | 82 | 1.464 | 3.029 | 4.000 | 8.000 | 0 |
| VNM | new | 81 | 1.446 | 2.940 | 4.000 | 8.000 | 0 |
| VCB | old | 71 | 1.268 | 3.558 | 4.000 | 9.000 | 0 |
| VCB | new | 73 | 1.304 | 3.688 | 4.000 | 10.000 | 0 |
| SSI | old | 60 | 1.071 | 4.068 | 5.000 | 11.000 | 0 |
| SSI | new | 56 | 1.000 | 4.079 | 4.500 | 14.000 | 0 |

Tổng 5 mã: **338 → 324 swings (−4,14%)**. VCB tăng 71→73 do thay chuỗi ứng viên/trạng thái,
không phải mọi mã đều giảm. Số lượng ít hơn không chứng minh chất lượng tốt hơn.

Định nghĩa chỉ tiêu:

- Số swing/phiên đếm theo phiên **xác nhận**, gồm cả phiên 0 swing. Chi tiết từng ngày:
  `swings_per_session.csv`.
- Độ lớn nhịp = |giá cực trị hiện tại − giá cực trị trước| / Wilder ATR chuẩn tại cực trị
  trước. Cùng một ATR chuẩn dùng cho cả hai detector. Mẫu thiếu ATR/ATR=0 không được tính;
  số mẫu hợp lệ trong `eligible_noise_legs`.
- Độ trễ = số nến hợp lệ giữa cực trị và xác nhận. Spacing = số nến giữa hai cực trị.
- Nhịp nhiễu theo yêu cầu = nhịp <1 ATR. Đây chỉ là tiêu chí mô tả, chưa chứng minh ý nghĩa
  giao dịch. Base mới có **1** nhịp, cũ **0**. Không thêm bộ lọc ẩn để làm số liệu đẹp.
- Nhịp giữa hai swing khác `reversal_size_in_ATR` (giá cực trị đến High/Low nến xác nhận).
  Vì vậy một swing đạt T=2ATR vẫn có thể tạo nhịp giữa hai cực trị <1ATR.
- Timestamp xác nhận cũ được chuẩn hóa +15 phút khi so sánh với nhãn đầu nến; không coi
  nhãn timestamp cũ là thời điểm nến đóng. Độ trễ tính theo index không đổi.

## 5. Độ nhạy cấu hình và giai đoạn thị trường

| k | pivot | count | swings_per_session | median_leg_ATR | median_delay_bars | median_spacing_bars | noise_legs_lt1ATR | eligible_noise_legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.500 | 3 | 458 | 1.636 | 2.917 | 3.000 | 8.000 | 5 | 453 |
| 2.000 | 3 | 324 | 1.157 | 3.664 | 4.000 | 12.000 | 1 | 319 |
| 2.500 | 3 | 207 | 0.739 | 4.665 | 6.000 | 18.000 | 0 | 202 |
| 1.500 | 5 | 350 | 1.250 | 3.303 | 5.000 | 10.000 | 4 | 345 |
| 2.000 | 5 | 284 | 1.014 | 3.798 | 5.000 | 13.000 | 1 | 279 |
| 2.500 | 5 | 192 | 0.686 | 4.708 | 7.000 | 18.000 | 0 | 187 |

Bảng này pooled **detector mới**, 5 mã ×56 phiên. `comparison_summary.csv` chứa cả cũ/mới
cho đủ 6 cấu hình. Giữ cấu hình cơ sở 2.0 /3/3: 1.5 tạo nhiều swing hơn nhưng tăng nhịp
<1ATR; 2.5 và/hoặc5/5 giảm swing và thường tăng độ trễ. Chưa có căn cứ tối ưu ngoài mẫu
để tự đổi default hoặc khẳng định cấu hình nào sinh lợi hơn.

Đã tách UP/DOWN/SIDEWAYS/HIGH_VOL trong `comparison_regimes.csv`. Đây là phân nhóm
**chỉ dùng cho báo cáo Layer 1**, không thay Layer 2: biến động ATR/Close có rolling
percentile100 nến (tối thiểu40), >=90% là HIGH_VOL; còn lại biến động Close20 nến/ATR
>=3 là UP, <=−3 DOWN, còn lại SIDEWAYS; chưa đủ warmup là UNCLASSIFIED. Chỉ dùng dữ liệu
đến thời điểm đó. Cả 5 mã có swing trong đủ 4 nhóm, nhưng mẫu khoảng 3 tháng không đại
 diện các chu kỳ tăng/giảm dài. Phiên có thể chứa nhiều nhóm; không cộng số phiên của
các nhóm để suy ra tổng thời gian. SSI có 1 swing UNCLASSIFIED.

## 6. Swing khác nhau và ví dụ biểu đồ

`differences.csv`: 5 mã có **25 old_only, 11 new_only, 4 confirmation_changed**.
Snapshot HPG được ghi riêng. Mỗi dòng có ngày/giá/cũ-mới, điều kiện trái/phải, và trace
ứng viên/T/reversal/trạng thái liên quan. Các lệch do chuỗi trạng thái có dẫn chứng tại
bar cụ thể; đây không phải phép ablation để khẳng định một nguyên nhân duy nhất.

Ví dụ:

- HPG LOW 29/09 10:00 giá20.150: 3 Low bên trái là20.150/20.200/20.200. Quy tắc first-tie
  không chọn nến bằng giá đến sau; detector mới đang giữ ứng viên sớm hơn.
- FPT LOW17/09 09:15 giá66.000: Low trái65.545,453/66.000/67.090,906; không đạt pivot trái.
  Việc bỏ đáy này làm chuỗi luân phiên tiếp theo khác bản cũ.
- VNM HIGH28/10 13:00 giá58.000: nến xác nhận cũ bị ambiguous_defer; sau đó xuất hiện ứng
  viên cao hơn. Không thể suy đoán thứ tự intrabar từ OHLC.
- HPG LOW21/10 13:15 giá21.150 tạo nhịp <1ATR so với HIGH trước21.200 trong bản mới;
  xem `HPG_leg_lt1ATR.png`. Điểm X trên chart là nến xác nhận, không phải lệnh giao dịch.

Mở `reports/layer1/comparison.html` để xem bảng và **11 biểu đồ nến/volume** cũ/mới,
bao gồm 4 nhóm thị trường. Tam giác tím=cũ; vòng cam=mới; đoạn chấm nối đến nến xác nhận.

![HPG: nhịp dưới 1 ATR](reports/layer1/HPG_leg_lt1ATR.png)

![FPT: swing khác nhau](reports/layer1/FPT_difference.png)

## 7. Kiểm thử và lỗi phát hiện ở code cũ

Bản cuối: **269 passed, 2 warnings, 41,69 giây** trên Linux/Python 3.12; trong đó 34 ca
Layer 1 mới. Log `tests_full.log`. Hai warning còn lại thuộc Starlette/httpx và parser
ngày của code cũ. Không bỏ qua/xfail test thất bại.

- 660 phép so sánh prefix tổng hợp (110 cutoff ×6 cấu hình), so sánh toàn bộ cột swing
  có confirm_time<=cutoff.
- Dữ liệu 5 mã thật: **1.050 cutoff/detector**, cả cũ và mới đều đạt. Chọn tại/trước/sau
  các xác nhận và các cutoff định kỳ. Chi tiết `prefix_real.json`.
- Kiểm tra Wilder bằng số tính tay, warmup14, dữ liệu lỗi/thiếu/trùng/timezone, tie/pivot,
  T cố định, thay ứng viên, luân phiên, spacing, outside/INIT hai ngưỡng, volume0 và
  không lọc theo volume, standalone import và CSV→Layer 2.
- CLI và `run_pipeline.py` chạy thành công với snapshot HPG; log riêng. Layer 2 trả
  INSUFFICIENT_STRUCTURE ở cuối dữ liệu là kết quả hợp lệ, không phải crash.
- Lượt full-suite đầu thất bại vì trỏ QTA_PRICE_DB tới file test chưa tạo. Đã tạo **bản sao**
  DB để test và chạy lại. Fixture test INIT ban đầu chưa thực sự tạo hai pivot đồng thời;
  đã sửa fixture, giữ quy tắc detector, chạy lại toàn suite. Chỉ số cuối ở trên là lượt cuối.
- Chưa chạy Windows thật, chưa kiểm thử browser (không đổi giao diện); không khẳng định đã
  thử hai môi trường này.

Phát hiện cũ:

1. ATR có giá trị trung bình tạm trong 13 nến đầu, trái đặc tả warmup. Từ nến14 trở đi
   seed và recurrence Wilder của code cũ đúng; không gọi toàn bộ ATR cũ là sai.
2. `swing_left` không được dùng; `swing_right` chỉ là độ chờ, không kiểm tra pivot3/3 đầy đủ.
3. Timestamp xác nhận ghi nhãn nến, nếu nhãn đầu thì sớm hơn lúc dữ liệu biết được15 phút.
   Prefix theo index không phát hiện lỗi diễn giải thời gian này.
4. Volume ratio cũ là volume nến cực trị /median chứa chính nến đó, min_periods=1;
   khác định nghĩa volume trong nhịp đảo chiều của bản này.
5. INIT khi cả hai hướng đủ thì chọn theo vị trí ứng viên; không áp dụng defer bảo thủ.
6. Chưa phát hiện vi phạm prefix theo index trong 1.050 cutoff thực nghiệm của detector cũ.
   Không kết luận cũ có look-ahead chỉ vì nó khác thuật toán mới.

## 8. Giới hạn và điểm cần quyết định

- Chưa kiểm chứng tính chính xác của từng nến, lịch phiên hoặc điều chỉnh quyền bằng nguồn
  sở giao dịch; không thể xác nhận mọi slot cảnh báo là nến mất.
- Dữ liệu ngắn, năm mã, có điều kiện đầu chuỗi/warmup; thay ngày bắt đầu có thể đổi chuỗi
  INIT. Không đủ để khẳng định swing đúng, có ý nghĩa hay dự báo chính xác hơn.
- Chưa có P&L sau phí/trượt giá và OOS giao dịch. Module chỉ phát hiện swing đã xác nhận;
  chừa giao diện confirm_time cho lớp thực thi sau này, chưa thêm mô phỏng chi phí.
- Các quy ước nên xác nhận trước dùng thật: nhãn open/close của nguồn; lịch giao dịch thực;
  first-tie toàn cửa sổ hay chỉ cụm liền; tổng volume nhịp hay volume trung bình; có cho
  phép nhớ lần chạm ngưỡng trước khi pivot đủ nến phải hay không. Bản hiện tại không nhớ
  lần chạm cũ, không tự đổi cấu hình cơ sở.
- Không tự nối detector mới vào mọi endpoint web/monolithic vì yêu cầu chỉ sửa module
  Layer 1 và giữ nguyên Layer 2. Nếu muốn thống nhất mọi đường chạy, cần rà soát adapter
  từng endpoint trong công việc riêng.

Đây là phân tích thuật toán, không phải lời khuyên đầu tư.
