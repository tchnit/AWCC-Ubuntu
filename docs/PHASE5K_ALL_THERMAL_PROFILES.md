# Phase 5K — mở thermal profiles, 2026-10-13

App/helper đã cài: **0.1.2**. Giao diện cho phép chọn sáu thermal profile trên
Alienware x17 R1 / BIOS 1.27.0. Đây không phải sáu chế độ điều khiển quạt thủ
công; RPM/PWM/boost/curve vẫn chưa có actuator production được kiểm chứng.

## Bằng chứng phần cứng và giới hạn

| Profile mới mở | Đường kiểm tra | Kết quả |
| --- | --- | --- |
| Low Power | PPD CLI, sau đó installed app client 0.1.2 | Giữ `power-saver` + platform `low-power`; phục hồi Performance đạt |
| Balanced+ | Root diagnostic, sau đó installed helper/client 0.1.2 | Diagnostic giữ tám mẫu; run4 production client giữ đủ bốn mẫu, thử từ cả Performance và Balanced, chuyển lại mode chuẩn đạt |
| Custom (thermal) | Root diagnostic, sau đó installed helper/client 0.1.2 | Diagnostic giữ tám mẫu; run4 production client giữ đủ bốn mẫu, CPU 46–49 °C/GPU 42 °C, fan BIOS-auto; Custom → Low Power rồi Balanced và restore Performance đạt |

Các profile Quiet/Balanced/Performance và recovery có bằng chứng trước đó trong
[Phase 5J](PHASE5J_INSTALLED_APP_HARDWARE_WRITES.md), không thử lại raw SMM.
Không đổi kernel/driver, ghi fan boost/PWM hay bật lại awccd/i8kmon.

Lần đầu ACAD/online=0 nên guardian dừng trước write. Sau khi người dùng cắm
sạc, trạng thái AC được đọc lại bằng sysfs, không giả định từ báo cáo cũ.

Evidence giữ nguyên từng lần:

- `research/results/hardware-test-remaining-profiles-2026-10-13.jsonl`: AC offline, abort trước write.
- `research/results/hardware-test-remaining-profiles-2026-10-13-run2.jsonl`: Low Power/Balanced+ đạt, Custom bỏ qua vì CPU 57 °C.
- `research/results/hardware-test-custom-cooled-2026-10-13.jsonl`: Custom diagnostic đạt sau làm mát, restore đạt.
- `research/results/hardware-test-unlocked-app-e2e-2026-10-13.jsonl`: Low Power và Balanced+ production client trả thành công. Runner giả định PPD sẽ thành balanced sau helper, nhưng daemon thực tế giữ power-saver; runner dừng và restore đạt. Không phải firmware từ chối Balanced+.
- `research/results/hardware-test-unlocked-app-e2e-2026-10-13-run2.jsonl`: sửa giả định trên; Low Power đạt, helper Balanced+ timeout 75 giây, platform vẫn low-power. Restore Performance đạt. Journal PolicyKit đọc sau đó xác nhận FAILED to authenticate cho đúng process 217941, 16:34:42.
- `research/results/hardware-test-unlocked-app-e2e-2026-10-13-run3.jsonl`: PPD set power-saver timeout 20 giây, app recovery Performance và guardian restore đều đạt. PPD action cho active session được phép không cần prompt; người dùng không thấy prompt. Nguyên nhân timeout lần này chưa được xác định, không coi là firmware từ chối.
- `research/results/hardware-test-unlocked-app-e2e-2026-10-13-run4.jsonl`: đặt helper trước để tách xác thực khỏi PPD, người dùng đã sẵn sàng tại máy. Toàn bộ chuỗi đạt, process exit 0, sự kiện `unlocked-profiles-e2e-passed`, `restore-original.ok=true`.

Chuỗi production-client cuối **đã đạt** sau xác thực tại máy. Trình tự:
Performance → Balanced+ → Low Power → Balanced → Balanced+ → Balanced →
Low Power → Custom → Low Power → Balanced → Performance. Mỗi request được
client xác minh, sau đó guardian đọc thêm bốn mẫu độc lập trong cửa sổ hai giây.
Balanced+ → Balanced và Custom → Low Power xác minh cả xử lý same-value alias.
Không có write manual fan. Không tiếp tục lặp các phép thử đã đạt.

Các lần timeout cũ vẫn là giới hạn độ tin cậy đã quan sát: run4 đạt không chứng
minh đã loại bỏ mọi timeout tương lai. Recovery khi timeout vẫn phải giữ bật;
không nâng timeout vô hạn hoặc báo thành công dựa riêng trên coarse PPD mode.

## Thay đổi production

- Low Power/Performance dùng PPD, không mở fallback ghi trực tiếp qua helper.
- Quiet/Balanced+/Custom dùng helper root-owned khớp fingerprint nguồn.
- Custom chỉ mở trên đúng model/BIOS đã thử; cần AC, đủ CPU/GPU hợp lệ, mọi
  nhiệt độ không quá 50 °C, bốn fan `pwm_enable=2`, không awccd socket tại apply.
  Chọn Low Power trước để hạ nhiệt; Custom không phải custom fan curve.
- Khi PPD đã có cùng coarse mode nhưng physical profile đang là helper profile,
  bridge qua Balanced trước khi áp dụng standard profile; xác minh cả hai trạng
  thái. Bao phủ trường hợp Custom → Low Power và Balanced+ → Balanced.
- Recovery lưu cả coarse PPD mode và physical profile. Khôi phục helper baseline
  giữ đúng CPU policy; Custom đã nóng/không còn đủ guard sẽ fallback Balanced và
  báo không thể phục hồi đúng baseline, không báo thành công giả.
- Không tự áp dụng preset khi mở app. Settings người dùng được giữ nguyên.

## Kiểm tra phần mềm và triển khai

- 159 tests đạt, gồm GTK với display thật; transport giả không ghi phần cứng.
- Render GTK cards đã xem: đủ sáu profile, badge/lý do và nút không bị cắt chữ.
  PNG: `research/results/ui-reliability-2026-10-13/ui-profiles-status.png`.
- Wheel `dist/alienware_control_center_linux-0.1.2-py3-none-any.whl` đã build
  offline. Từng Python module trong wheel và user install khớp nguồn bằng cmp.
- `python3 -B tools/check-helper.py` xác nhận helper root-owned khớp nguồn.
- Smoke read-only qua interpreter đã cài: cả sáu profile có `enabled=true`,
  manual capability false; CPU 55 °C AWCC, GPU 44 °C NVML, bốn fan BIOS-auto.
- Kiểm tra cuối chỉ đọc: PPD/platform cùng Performance, AC online,
  awccd/i8kmon inactive/disabled, không còn probe/helper test đang chạy.

Backup trước khi mở profile:

- App/desktop/settings: `~/.local/share/alienware-control-center-backups/0.1.1-before-profile-unlock-2026-10-13.PHePaL`.
- Helper trước cập nhật cuối: `/var/backups/awcc-helper.EKk5Yd`.
- Các backup 0.1.0 và Phase 5J vẫn giữ nguyên; không ghi đè báo cáo ban đầu.

## Phần chưa mở được một cách trung thực

Manual RPM/PWM, AWCC boost có hiệu lực vật lý, fan curves và Game Shift chưa
có đường production đã chứng minh. UI fan modes Phase 5B đã gỡ theo yêu cầu;
không đưa trở lại hoặc đặt capability giả để biến chức năng chưa có thành nút
bấm. Thermal profiles chỉ trao quyền cho BIOS/EC chọn chính sách nhiệt.
