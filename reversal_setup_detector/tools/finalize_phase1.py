import hashlib,json,re,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/layer3_phase1'
source=Path(sys.argv[1]).resolve()
results=json.loads((OUT/'test_results.json').read_text())
log=(ROOT/'LAYER3_PHASE1_TEST_LOG.txt').read_text()
m=re.search(r'RESULT tests=(\d+) passed=(\d+) failures=(\d+) errors=(\d+) skipped=(\d+)',log)
assert m and m[3]=='0' and m[4]=='0' and m[5]=='0'
assert int(m[1])==len(results) and all(x['status']=='PASS' for x in results)
manifest=[]
with zipfile.ZipFile(source) as z:
 for name in z.namelist():
  a=z.read(name);b=(ROOT/name).read_bytes()
  assert a==b,name
  manifest.append(dict(path=name,sha256=hashlib.sha256(b).hexdigest(),unchanged=True))
(OUT/'UPSTREAM_INTEGRITY.json').write_text(json.dumps(dict(source_name=source.name,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),unchanged_files=len(manifest),files=manifest),indent=2)+'\n')
source_prompt=(ROOT/'reversal_setup_detector/source/PROMPT_LAYER3_VA_SPEC.md').read_bytes()
partb=source_prompt[source_prompt.index('# PHẦN B'.encode()):]
assert (ROOT/'docs/SPEC_LAYER3_v1.0.md').read_bytes()==partb
provenance=dict(spec_part_B_sha256=hashlib.sha256(partb).hexdigest(),spec_copy_exact=True,inputs={})
for t in ['HPG','FPT','VNM','VCB','SSI']:
 p=ROOT/f'reports/layer1/{t}_clean.csv';provenance['inputs'][str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
(OUT/'INPUT_PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
decisions=[
 dict(id='L3-D01',status='PROPOSED',proposal='EVER_CONFIRMED: lấy đúng hai Major liền kề gần nhất, rồi kiểm tra DOWN + CONFIRMED tại T; không nhảy qua BROKEN.',reason='ACTIVE hiện lọc status=CONFIRMED trước khi lấy hai cuối: [A CONFIRMED, B BROKEN, C CONFIRMED] trả A,C; EVER_CONFIRMED trả B,C. Test read-only xác nhận. Context adapter chưa triển khai (Phase 2).'),
 dict(id='L3-D02',status='PROPOSED',proposal='Layer 3 sở hữu Long-context; giữ Layer 2 NULL + LONG_CONTEXT_NOT_EVALUATED.',reason='Không sửa Layer 2. Phase 1 chưa đánh giá Long-context.'),
 dict(id='L3-D03',status='PROPOSED',proposal='candle_time là thời điểm mở nến; available_at=max(thời điểm đóng nến theo calendar, thời điểm nguồn thực sự available). Thiếu available_at thì derive close.',reason='Layer 1 config timestamp_label=open; extreme_time lấy Datetime và confirmed_at lấy available_time; dữ liệu hiện tại +15 phút. Lưu availability_derived; cần xác minh nhãn nến ATO/ATC của nguồn.'),
 dict(id='L3-D04',status='PROPOSED',proposal='allow_cross_session_sequences=true nếu hai slot liền nhau trong lịch chuẩn; false chỉ là biến thể version riêng. Nến lỗi/thiếu luôn chặn ghép.',reason='Dữ liệu thật thiếu verified calendar; báo cáo dùng template L1 UNVERIFIED và chặn gap nghi vấn, không tự bỏ 09:00/14:30 hoặc suy ngày nghỉ. Cần owner duyệt xuyên phiên và thống nhất lịch chuẩn của nguồn.'),
 dict(id='L3-D05',status='PROPOSED',proposal='Không giới hạn độ cũ context; context_age_bars chỉ phục vụ nghiên cứu, không lọc.',reason='max_context_age_bars=null, record_context_age_bars=true được dành sẵn trong cấu hình. Chưa tính context_age_bars trong Phase 1 vì chưa chọn context; sẽ nối vào output ở phase tương ứng.')]
(OUT/'decisions.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2)+'\n')
summary=json.loads((OUT/'summary.json').read_text())
def table(rows,columns):
 return '| '+' | '.join(columns)+' |\n|'+'|'.join(['---']*len(columns))+'|\n'+''.join('| '+' | '.join(str(r[k]).replace('|','\\|') for k in columns)+' |\n' for r in rows)
at=[]
for i in range(1,23):
 key=f'AT{i:02d}';found=[x for x in results if 'test_'+key+'_' in x['test']]
 at.append(dict(AT=key,test='; '.join(x['test'] for x in found) if found else 'Chưa triển khai — Phase '+('2' if i in (8,9) else '3' if i in range(10,19) else '4'),status='PASS' if found and all(x['status']=='PASS' for x in found) else 'NOT_IMPLEMENTED'))
assert sum(x['status']=='PASS' for x in at)==8
(OUT/'acceptance_matrix.json').write_text(json.dumps(at,ensure_ascii=False,indent=2)+'\n')
original={x['path'] for x in manifest}
new_files=sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and str(p.relative_to(ROOT)) not in original and '__pycache__' not in p.parts and p.suffix!='.pyc' and not any(part.startswith('.') for part in p.relative_to(ROOT).parts))
(OUT/'ADDED_FILES.json').write_text(json.dumps(sorted(set(new_files+['reports/layer3_phase1/ADDED_FILES.json','LAYER3_PHASE1_REPORT.md'])),indent=2)+'\n')
report=f'''# Layer 3 Phase 1 — báo cáo bàn giao

Phạm vi hoàn thành: validation OHLCV, body/wick, RED/GREEN/DOJI, bộ ba R1/R2/R3 và kiểm tra adjacency/gap bằng calendar. Đã sao chép **nguyên byte phần B** vào docs/SPEC_LAYER3_v1.0.md. Đây là baseline của dự án, chưa khẳng định phương pháp gốc Gianluca Bruni.

## Kiểm thử

**{m[2]}/{m[1]} test đạt; {m[3]} failures, {m[4]} errors, {m[5]} skipped.**
Log stdout/stderr nguyên văn: LAYER3_PHASE1_TEST_LOG.txt. Kết quả từng test: reports/layer3_phase1/test_results.json.
Có 8 acceptance tests riêng AT01–AT07, AT21, cùng các test edge case, duplicate, invalid barrier, strict equality, timeframes, calendar, availability, prefix, config version và đối chiếu ACTIVE của Layer 2.
Các AT chưa thuộc Phase 1 được đánh NOT_IMPLEMENTED, không tính là PASS hay skipped test.

{table(at,['AT','test','status'])}

## Dữ liệu thật — thống kê có điều kiện theo mẫu lịch

{table(summary,['ticker','known_candles','invalid_candles','valid_red_triplets','cross_session_triplets','no_cross_session_triplets','gaps','missing_slots'])}

Tổng 4.482 nến, **25 bộ ba đỏ** với allow_cross_session_sequences=true; **23** với biến thể false. Hai bộ xuyên nghỉ trưa (HPG/FPT); không có bộ xuyên ngày theo template hiện tại. Đây không phải 25 candidate hay LONG_SETUP: context chưa được áp dụng.

**Calendar thật chưa được xác minh.** Layer 1 dùng mẫu ngày thường 09:00–11:30 và 13:00–15:00. Data có 56 ngày; cả 5 mã không có nến 09:00, 14:30 chỉ có một hàng ở VCB và SSI. Không tự xem những slot vắng mặt hay các ngày trống là ngày nghỉ hợp lệ. Gap trong bảng là **UNVERIFIED_CALENDAR_GAP**, chưa khẳng định nến thực sự thiếu theo lịch sở. Các gap nghi vấn chặn ghép; con số 25 vì vậy chỉ đúng theo mẫu lịch đã ghi cấu hình, chưa là thống kê cuối với lịch chuẩn.

AT21 kiểm tra DATA_GAP_IN_CANDLE_SEQUENCE trên calendar fixture được khai báo đầy đủ. API nhận expected slots độc lập với input candles, có coverage, calendar_id/hash và cờ verified. Mẫu ngày thường không được tự gắn verified=true. Không suy calendar từ timestamp hiện có để che dữ liệu thiếu. Không xác nhận completeness trước/sau timestamp đầu/cuối dữ liệu.

## Ranh giới phiên của 5 slot sau R3 — chỉ chẩn đoán

{table(summary,['ticker','diagnostic_windows','windows_cross_session','windows_cross_date','windows_complete','complete_windows_cross_session'])}

Cross-session tính cả ranh giới R3 → slot đầu, nghỉ trưa và chuyển ngày; cross-date là tập con. Có 12/25 cửa sổ dự kiến qua phiên, trong đó 5 qua ngày; chỉ 15/25 cửa sổ đủ 5 slot có nến hợp lệ trong snapshot, trong số này 7 qua phiên. Chi tiết ở five_slot_window_diagnostics.csv. Cửa sổ thiếu nến không được tính hoàn chỉnh. Chưa kiểm tra màu/ratio G, chưa chạy lifecycle và chưa có thống kê FOUND/EXPIRED/INVALIDATED. Số này nhằm hỗ trợ quyết L3-D04, không kết luận chất lượng mô hình.

## Point-in-time và timestamp

L3-D03 đề xuất candle_time=open, khớp Layer 1. available_at=max(calendar close, nguồn available); nếu thiếu nguồn thì derive close. Trên data hiện tại, Layer 1 đặt close=Datetime+15 phút. Không tự coi việc ánh xạ này là bằng chứng nhãn ATO/ATC của nhà cung cấp đã verified. Calendar explicit có thể cung cấp close thực tế của slot ngắn.

Nến chưa đóng/chưa available bị loại trước khi validation/duplicate ảnh hưởng snapshot. Test gồm mutation/append nến tương lai, dữ liệu đến trễ và 15 so sánh raw-prefix (3 cutoff × 5 mã). Đây là bằng chứng candle scanner trên snapshot cố định, chưa phải nghiệm thu AT18 của lifecycle FOUND, chưa kiểm thử context/cấu trúc tương lai hay dữ liệu as-received. Các phần đó giữ cho phase tiếp theo.

## Quyết định chờ duyệt

{table(decisions,['id','status','proposal','reason'])}

L3-D01 được kiểm tra bằng lời gọi read-only vào code Layer 2 hiện tại: ACTIVE có thể bỏ qua BROKEN ở giữa. Không thay mode mặc định Layer 2; D08/D10 của Layer 2 vẫn DEFERRED theo bàn giao trước.

## File và tính toàn vẹn

Chỉ thêm module reversal_setup_detector/ (config, source prompt, API, tests và scripts), docs/SPEC_LAYER3_v1.0.md, reports/layer3_phase1/, LAYER3_PHASE1_REPORT.md và LAYER3_PHASE1_TEST_LOG.txt. Danh sách file mới ở reports/layer3_phase1/ADDED_FILES.json.

**{len(manifest)} file gốc giữ nguyên byte**, gồm toàn bộ Layer 1/Layer 2 và database. Manifest hash từng file và hash ZIP nguồn nằm trong UPSTREAM_INTEGRITY.json. Không sửa database, không có migration. Không chạy lại 154 test Phase 5 trong lượt thay module độc lập này; log cũ được giữ nguyên, không gán chúng là test mới.

Chưa làm Phase 2–5: context adapter, context_age_bars output, candidate/lifecycle, persistence/event và LONG_SETUP. Không đặt lệnh, không giá khớp, FVG, SL/TP, volume filter hay chỉ báo bổ sung. Dừng sau Phase 1 chờ owner duyệt.
'''
(ROOT/'LAYER3_PHASE1_REPORT.md').write_text(report,encoding='utf-8')
print(m.group(0));print('Original files unchanged',len(manifest));print('Part B exact copy PASS')
