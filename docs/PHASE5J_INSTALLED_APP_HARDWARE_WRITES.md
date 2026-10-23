# Phase 5J — ghi profile và kiểm chứng recovery trên máy thật

Ngày 2026-10-13. Alienware x17 R1, BIOS 1.27.0, kernel 7.0.0-38-generic.
Người dùng cho phép thực hiện ghi thật sau khi cài app/helper 0.1.1.

## Kết quả đã xác nhận

| Phép thử | Kết quả vật lý / đọc lại |
| --- | --- |
| PPD: Performance → Balanced | Cả PPD/platform giữ Balanced qua đủ bốn mẫu |
| Installed helper: Balanced → Quiet | Helper xác minh ba mẫu; quan sát thêm bốn mẫu giữ Quiet |
| PPD: Quiet → Balanced | Giữ Balanced, không rollback Quiet ngoài ý muốn |
| PPD ghi Balanced thật, bỏ một mẫu xác minh bằng phần mềm | Request báo lỗi, tự khôi phục Performance, bốn mẫu độc lập xác nhận |
| PPD ghi Balanced thật từ Quiet, bỏ một mẫu xác minh | Request báo lỗi, khôi phục Quiet qua helper; PPD power-saver/platform Quiet giữ đúng baseline |
| Root-owned ProfileController ghi Quiet thật từ Performance, thay một mẫu bằng lỗi phần mềm | persistent false, restored true; Performance được phục hồi qua PPD và xác minh cả bên trong helper lẫn runner độc lập |

Lỗi xác minh ở các ca recovery là **fault injection tại lớp đọc phần mềm**.
Log ghi cả giá trị vật lý (`balanced` hoặc `quiet`) và giá trị lỗi được cung
cấp cho bước kiểm tra. Không khẳng định firmware từ chối các profile này.

RPM thay đổi theo profile: trong run app, Performance khoảng 6300/4400/6400/3300,
Balanced khoảng 2000/0/1800/0; Quiet có lúc cả bốn fan dừng ở CPU 43–44 °C.
Sau khi khôi phục Quiet, hai fan vẫn có thể quay 1800–2000 RPM. Các giá trị là
quan sát tức thời, không phải target RPM hay tốc độ bị khóa. Mọi `pwm_enable`
đã ghi log đều là 2: BIOS/EC vẫn quản lý quạt.

## Phát hiện và sửa trong quá trình thử

1. Run đầu kỳ vọng PPD giữ Balanced trong khi platform Quiet. Thực tế PPD tự
   công bố **power-saver** khi platform vẫn **quiet**. Runner dừng và khôi
   phục Performance thành công. Đây không phải việc agent ghi Low Power.
2. Nhánh recovery Quiet được sửa để gọi trực tiếp helper Quiet rồi kiểm tra
   cặp PPD/platform ban đầu. Không gọi `set power-saver` để phục hồi Quiet,
   vì lệnh đó sẽ yêu cầu profile Low Power khác với Quiet đang hoạt động.
3. Ca root-helper đầu có `set performance` vượt timeout 5 giây, nhưng platform
   đã trở lại Performance. Runner ngoài xác nhận và phục hồi baseline; nguyên
   nhân độ trễ chưa được xác định, journal đọc trong cửa sổ đó không có entry.
   Không kết luận đây là firmware từ chối hoặc lỗi đã được giải thích hoàn toàn.
4. Recovery PPD nay chờ setter 20 giây và vẫn đọc đủ bốn mẫu sau timeout.
   Recovery được xác nhận bằng trạng thái PPD/platform thực tế. Client helper
   và bước phục hồi Quiet cho phép 75 giây để bao gồm xác thực và recovery.
5. Root-helper run2 đạt: setter Performance mất 0,244 giây, bốn get trả
   Performance. Kết quả này xác nhận recovery mới trên máy; không chứng minh
   nguyên nhân lần timeout trước đã biến mất vĩnh viễn.

Các sửa đổi đã được cài lại. Helper được sao lưu trước lần cập nhật cuối ở
`/var/backups/awcc-helper.ltdWG4`; app ngay trước sửa timeout ở
`~/.local/share/alienware-control-center-backups/0.1.1-before-recovery-timeout-2026-10-13.9WQ1v3`.
Backup 0.1.0 và helper ban đầu vẫn được giữ.

## Điều kiện và phạm vi

Runner chạy bằng interpreter của **app đã cài**, không lấy client từ checkout.
Quiet bình thường đi qua `ProfileClient`/PolicyKit; fault test nội bộ helper
dùng đúng root-owned `ProfileController` đã cài và wrapper đọc một mẫu để
tạo lỗi phần mềm. Root-owned controller có path trong log để đối chiếu.

AC online, `awccd` và `i8kmon` inactive; đúng stock module/srcversion; CPU/GPU
phải có telemetry hợp lệ, baseline tối đa 60 °C. Ngưỡng dừng là 85 °C.
App được tạm đóng để tránh thao tác cạnh tranh. Watchdog độc lập 180 giây
(ca root-helper đầu 120 giây) giữ baseline và phục hồi khi parent bị gián đoạn.
Watchdog không hết hạn trong các run; nhánh timeout watchdog chưa được cố tình
gây trên hardware. Baseline cuối cả bốn run đều trở lại Performance.

Run app thành công kéo dài 46,71 giây, CPU 41–45 °C/GPU 37–39 °C.
Root-helper run2 CPU 51–55 °C/GPU 41–42 °C. PPD cảnh báo
`high-operating-temperature` được giữ nguyên và ghi log; test chỉ yêu cầu
Balanced/Quiet và phục hồi Performance đã chạy từ đầu.

Không ghi PWM/boost, gọi Game Shift/raw SMM, thay driver/service, reboot hoặc
mở Low Power/Balanced+/Custom. Các kết quả này là platform profile control và
recovery, không xác nhận manual fan takeover.

## Evidence

- [App run1: giả định PPD Quiet sai, restore đạt](../research/results/hardware-test-installed-app-profiles-2026-10-13.jsonl).
- [App run2: writes và hai recovery đạt](../research/results/hardware-test-installed-app-profiles-2026-10-13-run2.jsonl).
- [Root-helper run1: timeout, baseline được phục hồi](../research/results/hardware-test-installed-helper-recovery-2026-10-13.jsonl).
- [Root-helper run2: recovery đạt](../research/results/hardware-test-installed-helper-recovery-2026-10-13-run2.jsonl).

Sau sửa cuối: 148 unit/integration tests đạt, gồm 18 test GTK.
