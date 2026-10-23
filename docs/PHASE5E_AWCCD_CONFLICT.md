# Giai đoạn 5E — xác định controller cạnh tranh `awccd`

Ngày: 2026-10-10. Máy: Alienware x17 R1, BIOS 1.27.0, kernel
`7.0.0-38-generic`.

## Kết luận

Profile `Balanced` đã được ghi lại bởi một daemon bên ngoài workspace:
`awccd.service`, chạy root từ `/opt/awcc` với entry point
`/usr/bin/python3 -m awccd.main`. Đây là đúng process đã xuất hiện trong
Phase 5C/5D, không phải firmware, EC, `power-profiles-daemon`, UI GTK hiện tại
hay helper của project này.

Daemon được enable ở boot qua
`/etc/systemd/system/multi-user.target.wants/awccd.service`. Source của nó gọi
`self.hw.set_profile(self.cfg.profile)` ở mỗi control tick, kể cả khi fan mode
là Manual/Custom. Vì config hiện hành là `profile=balanced`, mọi yêu cầu Quiet
từ phép thử sẽ bị ghi đè từ daemon này.

Do đó các kết quả trước đây về việc Quiet quay lại Balanced **không thể dùng để
kết luận firmware BIOS 1.27.0 từ chối Quiet**. Chúng vẫn không phải bằng chứng
Quiet ổn định khi daemon dừng; chỉ là nguyên nhân cạnh tranh đã được xác định.

## Bằng chứng runtime

Phép thử logging v3 có watchdog đã được người dùng cấp phép một lần:

| Mốc | Bằng chứng |
| --- | --- |
| Preflight | stock driver, Balanced, PPD active, CPU/GPU 42/37 °C |
| Quiet write | `0xA3` trả thành công; profile là Quiet ở mẫu 262 ms |
| 568 ms sau write | profile đã Balanced dù PPD vẫn dừng |
| Kernel marker | `pid=2350 tgid=2337 ppid=1 uid=0 comm=python3`, request `0xA0` |
| Process read-only | TGID 2337 là `/usr/bin/python3 -m awccd.main` |
| Restore | stock `28A4134FBF8432C66D7C668`, Balanced, PPD active, CPU/GPU 42/37 °C |

`awcc-cli status` được đọc qua socket của daemon (chỉ `get_state`) cũng cho
thấy daemon đang ở `mode=manual`, `profile=balanced`, target boost CPU 100% và
GPU 98%. Source `/opt/awcc/awccd/engine.py` cho thấy mode Manual ghi fan boost
theo config, còn profile Balanced vẫn bị enforce trên mỗi tick.

Không suy ra các target boost này tạo manual fan control ổn định/safe cho x17
R1: source daemon chỉ ghi chú verification boost trên m18 R1, telemetry
`fan_max` hiện không nhất quán với RPM, và chưa có thử nghiệm takeover vật lý
có rollback phù hợp.

Log sự kiện đã chuẩn hóa từ output root runner và attribution process:
[hardware-test-awcc-profile-attribution-v3-2026-10-10.jsonl](../research/results/hardware-test-awcc-profile-attribution-v3-2026-10-10.jsonl).

## Bảo vệ trong ứng dụng này

Backend hiện chỉ đọc sự tồn tại của `/run/awcc/awccd.sock`; không kết nối socket
và không thay đổi daemon. Khi socket hiện diện, UI hiển thị xung đột controller
và chặn mọi write profile mới (trừ lựa chọn hiện tại chỉ lưu preferences). Điều
này ngăn ứng dụng tạo thêm writer cạnh tranh hoặc hứa một read-back sai.

## Bước tiếp theo cần quyết định người dùng

Không tự dừng `awccd`: `systemctl stop` là thay đổi trạng thái hệ thống, và
daemon đang giữ boost manual cao. Chỉ stop có thể để lại boost cuối cùng trên
phần cứng, vì hàm stop của daemon không có cleanup rõ ràng.

Nếu người dùng muốn cô lập nó một cách có rollback, phương án an toàn là:

1. Qua chính daemon, chuyển sang `mode=profile` và `profile=balanced` để nó ghi
   target boost về 0; xác nhận RPM/profile/read-back.
2. Dừng `awccd.service` tạm thời, **không disable** ở bước đầu; xác nhận socket
   biến mất, PPD active, driver stock và Balanced.
3. Chỉ sau đó chạy một lần Quiet có watchdog bằng driver stock để kiểm chứng
   profile không còn bị writer cạnh tranh ghi đè.

Ba bước này đổi config/service và gửi write boost/profile; cần cấp phép riêng.
Không dùng mode Manual/Custom của daemon, không viết PWM/SMM, và không disable
unit ở lần cô lập đầu tiên.

## Kết quả cô lập được cấp phép

Người dùng đã cấp phép quy trình cô lập ngày 2026-10-10. Qua socket của chính
daemon, `mode=profile` đã được áp dụng trước khi dừng service. Read-only status
xác nhận `profile=balanced`, bốn target boost đều 0%, CPU/EC GPU 45/37 °C.

Sau đó `systemctl stop awccd.service` gửi SIGTERM. Source của daemon có lỗi
shutdown: signal handler gọi `shutdown()` trong chính thread đang chạy
`serve_forever()`, nên systemd ghi nhận timeout 90 giây và tự SIGKILL process
2337. Đây là hậu quả tự động của `systemctl stop`, không phải kill cưỡng bức thủ
công. Journal kết thúc bằng `Stopped awccd.service`; socket `/run/awcc/awccd.sock`
đã biến mất.

Xác nhận cuối chỉ đọc:

- backend của project không còn phát hiện controller `awccd`;
- stock `alienware_wmi` srcversion `28A4134FBF8432C66D7C668` và profile
  `balanced`;
- bốn AWCC fan boost là `0, 0, 0, 0`;
- `power-profiles-daemon.service` là `active`.

Sau đó, theo permission riêng để dọn writer lúc boot, `awccd.service` đã được
`disable --now` và `reset-failed`; không còn socket hay process `awccd`.
`i8kmon.service` (daemon Dell phụ, hiện không thể chạy vì thiếu `/proc/i8k`)
cũng đã được `disable --now`. Không có file `/opt/awcc`, config daemon, package
hay unit nào bị xóa/sửa; hai service có thể được enable lại có chủ đích nếu cần.
Desktop autostart `awcc --hidden` vốn đã có
`X-GNOME-Autostart-enabled=false`. Tùy chọn module phục vụ telemetry/profile
được giữ nguyên.

Log sự kiện: [awccd-isolation-2026-10-10.jsonl](../research/results/awccd-isolation-2026-10-10.jsonl).

## Phép kiểm tiếp theo đã chuẩn bị, chưa chạy

`research/isolated_quiet_profile_test_runner.py` chỉ dùng stock driver, yêu cầu
`awccd` inactive/socket absent, dừng PPD tạm thời, gửi đúng một write Quiet,
quan sát 2,5 giây và tự khôi phục Balanced/PPD qua watchdog 30 giây. Nó không
nạp/unload module, không gọi Game Shift/SMM/PWM/boost. Phép ghi Quiet mới này
cần một permission riêng trước khi chạy.

Phép kiểm đó sau đó đã hoàn tất theo permission riêng: Quiet giữ cả 10 mẫu khi
PPD dừng, rồi runner khôi phục đầy đủ. Xem
[PHASE5F_QUIET_WITHOUT_AWCCD.md](PHASE5F_QUIET_WITHOUT_AWCCD.md).
