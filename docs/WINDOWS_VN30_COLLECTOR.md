# Windows Task Scheduler cho QTA VN30

## Chuẩn bị

1. Clone repository vào một thư mục cố định, ví dụ `C:\QTA`. Đặt thư mục ở nơi tài khoản chạy task có quyền đọc, ghi và truy cập Internet. Lệnh `schtasks` bên dưới dùng đúng đường dẫn ví dụ không có khoảng trắng.
2. Mở Command Prompt và tạo venv bằng Python 3.12. Các phiên bản dưới đây đã chạy trong lần kiểm chứng.

   ```bat
   cd /d C:\QTA
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install yfinance==1.8.0 tzdata==2026.6
   ```

3. Kiểm tra múi giờ Windows bằng `tzutil /g`. Lịch 15:15 bên dưới giả định giờ máy là UTC+07:00, ví dụ `SE Asia Standard Time`.
4. Dùng launcher VN30 mới, tại `C:\QTA\extensions\daily_15m_collector\vn30\RUN_AFTER_CLOSE.bat`. Launcher dùng đường dẫn theo vị trí cài đặt và venv ở thư mục gốc. Cấu hình 30 mã là `extensions\daily_15m_collector\config.vn30.2026-07.json`. SQLite độc lập ở `extensions\daily_15m_collector\data\collector_15m.sqlite`.
5. Collector tự bỏ qua thứ Bảy, Chủ nhật và ngày nghỉ trong `hose_holidays.json`. Hiện tệp có lịch năm 2026. Khi có lịch HOSE năm kế tiếp, thêm năm và ngày nghỉ vào tệp này. Nếu thiếu năm của ngày chạy, chương trình ghi `HOSE_CALENDAR_YEAR_MISSING` và trả mã 4 để lỗi hiện trên Task Scheduler. [Lịch nghỉ HOSE](https://www.hsx.vn/vi/tin-tuc/hose-thong-bao-lich-nghi-giao-dich-nam-2026/2437411)

## Tạo lịch bằng giao diện

1. Mở `taskschd.msc` → **Task Scheduler Library** → **Create Task**.
2. **General** → đặt tên `QTA-VN30-15m`. Chọn tài khoản Windows có quyền với thư mục QTA và mạng. Chọn **Run whether user is logged on or not**. Nhập mật khẩu vào hộp thoại của Windows khi được yêu cầu.
3. **Triggers** → **New** → **Weekly**, lặp mỗi tuần, chọn Monday đến Friday, lúc **15:15**.
4. **Actions** → **Start a program**. **Program/script** điền `C:\Windows\System32\cmd.exe`. **Add arguments** điền `/d /c C:\QTA\extensions\daily_15m_collector\vn30\RUN_AFTER_CLOSE.bat`. **Start in** điền `C:\QTA`. Nếu thư mục có khoảng trắng, dùng `/d /s /c ""C:\đường dẫn\QTA\extensions\daily_15m_collector\vn30\RUN_AFTER_CLOSE.bat""`.
5. **Settings** → bật **Run task as soon as possible after a scheduled start is missed**. Bật chạy lại sau **15 phút**, tối đa **2 lần**. Chọn **Do not start a new instance** nếu đang chạy. Có thể bật **Wake the computer to run this task** trong **Conditions** nếu máy hỗ trợ và cần chạy từ chế độ ngủ.

## Tạo bằng schtasks

Chạy các lệnh sau trong **Command Prompt**, với đường dẫn ví dụ ở trên. Chọn một trong hai cách tạo lịch. Sau khi tạo bằng lệnh, mở **Properties** để bổ sung các tùy chọn chạy bù, retry và chống chạy trùng ở bước 5. `/rp *` yêu cầu nhập mật khẩu qua prompt. [Tài liệu Microsoft về schtasks create](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create)

```bat
schtasks /Create /TN "QTA-VN30-15m" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:15 /TR "%SystemRoot%\System32\cmd.exe /d /c C:\QTA\extensions\daily_15m_collector\vn30\RUN_AFTER_CLOSE.bat" /RU "%USERDOMAIN%\%USERNAME%" /RP *
schtasks /Run /TN "QTA-VN30-15m"
schtasks /Query /TN "QTA-VN30-15m" /V /FO LIST
```

## Kiểm tra và đọc log

- Trong Task Scheduler, xem **Last Run Time**, **Last Run Result** và **History**. Có thể bật **Enable All Tasks History**. `0x0` là lần chạy thành công hoặc ngày nghỉ được bỏ qua. `0x1` báo ít nhất một mã lỗi, không có nến hợp lệ hoặc thiếu phiên dự kiến. `0x3` là collector khác đang chạy. `0x4` là lỗi cấu hình môi trường hoặc thiếu lịch năm.
- Mở `extensions\daily_15m_collector\logs\scheduler_console.log` để xem START/EXIT, lỗi khởi động và kết quả từng mã. `logs\fetch_runs.jsonl` có 30 dòng theo mã mỗi lượt giao dịch, với hậu tố `.VN`, khoảng ngày, lỗi Yahoo, số nến thêm/trùng/bị loại và trạng thái `LATEST_SESSION_MISSING` khi thiếu phiên dự kiến. Ngày nghỉ ghi `SKIPPED`.
- Khi máy tắt, task không thể chạy. Nếu bật chạy bù, Windows có thể chạy sau khi máy khởi động. Collector thử lại cả 30 mã với cửa sổ 60d, thử 59d khi 60d lỗi, chỉ chèn khóa mới. Nếu chạy bù trước 15:15, collector dùng phiên hoàn thành gần nhất và giữ lại dữ liệu phiên đang diễn ra cho lượt sau. Khoảng thiếu ngoài dữ liệu Yahoo còn trả được cần nguồn backfill riêng.
- Launcher được chạy thủ công từ thư mục khác trên Windows, với đủ 30 mã. Task chưa được đăng ký hoặc chạy dưới tài khoản Task Scheduler.
