# Giai đoạn 5C — profile thường được nhận, rồi có yêu cầu Balanced khác

Ngày: 2026-10-10. Máy: Alienware x17 R1, BIOS 1.27.0, kernel
`7.0.0-38-generic`.

## Kết luận

`quiet` (`0xA3`) **không bị firmware từ chối đồng bộ**. Lệnh AWCC
`WMAX(method=0x15, operation=0x01, arg1=0xA3)` trả raw `0x00000000`; sysfs
đọc lại `quiet` ngay lập tức và giữ trong ít nhất 1,33 giây.

Tuy nhiên, khi `power-profiles-daemon` vẫn đã dừng, kernel log ghi một lệnh
profile thứ hai `WMAX 0x15/0x01/0xA0` (Balanced) sau khoảng 1,43 giây. Lệnh
này hoàn thành sau khoảng 18,09 giây; các getter WMAX serialized phía sau nó
bị chặn, nên mẫu kế tiếp mới thấy `balanced`.

Điều này bác bỏ giả thuyết *"Quiet trả EBADRQC / profile ID không hợp lệ"*.
Nó **chưa** chứng minh EC tự gửi lệnh Balanced: v1 logging không ghi PID/comm
của caller. Nói cách khác, nguồn của yêu cầu `0xA0` là chưa xác định, dù PPD
đã được loại khỏi lần chạy này. Vì profile không giữ ổn định, UI vẫn khóa Quiet
và mọi mode/control phụ thuộc nó.

## Phạm vi và an toàn

Runner mới: `research/diagnostic_profile_test_runner.py`.

- kiểm tra DMI chính xác, BIOS 1.27.0, AC online, Balanced, PPD active, không
  có module holder, nhiệt độ dưới 60 °C;
- SHA-256 candidate đúng `05f405…f878`, ABI đúng `7.0.0-38-generic`;
- copy artefact đã hash vào `/run` root-only, tạm nạp nó với
  `force_gmode=0`, không thay `/lib/modules`, không `depmod`/initramfs;
- dừng PPD, gửi đúng **một** write `quiet`, lấy 10 mẫu mỗi 250 ms;
- watchdog độc lập 30 giây; khi kết thúc (hoặc lỗi) nạp lại module Ubuntu,
  ghi Balanced và khởi động PPD.

Candidate chỉ logging 2 lớp gọi sẵn có. Không thêm WMI call, SMM, PWM, boost,
fan-control, fallback hay bypass Game Shift. Secure Boot của máy đang tắt;
candidate unsigned chỉ tồn tại trong RAM của phép thử.

## Bằng chứng runtime

| Mốc | Kết quả |
| --- | --- |
| Baseline | stock `28A4134…C668`, Balanced, PPD active, CPU/GPU 41/35 °C |
| 09:00:33.631 | logging module `9CD2136…209` vào profile activation `A3` |
| 09:00:33.684 | raw `0x00000000`, write sysfs thành công, profile Quiet |
| đến 09:00:35.014 | năm mẫu tiếp tục là Quiet, PPD inactive |
| 09:00:35.119 | `AWCC_DIAG` ghi activation `A0` không thuộc write Quiet ban đầu |
| 09:00:53.209 | lệnh `A0` trả raw `0x00000000`; mẫu bị serialize sau nó thấy Balanced |
| Khôi phục | stock `28A4134…C668`, Balanced, PPD active; CPU/GPU 41/35 °C |

Kernel driver v7.0 chỉ gọi `awcc_op_activate_profile()` từ callback
`awcc_platform_profile_set()`. Không có worker rollback riêng trong
`alienware-wmi-wmax.c`; nhưng log hiện tại chưa đủ dữ liệu để xác định caller
của callback platform-profile đó. Không suy diễn nguyên nhân từ riêng sự kiện
`A0`.

Log JSON nguyên gốc: [hardware-test-awcc-profile-diagnostic-2026-10-10.jsonl](../research/results/hardware-test-awcc-profile-diagnostic-2026-10-10.jsonl).

## AML offline liên quan

DSDT đã xác nhận `WMAX` có case `0x15`; operation `1` đi vào nhánh ACPI/CSMI,
không rơi vào default `0xFFFFFFFF` như `0x25`. Đây nhất quán với raw runtime
`0` của `A3`. Parser hiện có không diễn giải mailbox CSMI hoặc EC behavior,
nên không dùng AML để gán tác nhân cho request `A0`.

## Cập nhật sau attribution 5D

Candidate v2 đã xác nhận setter `A0` có `pid=2350 comm=python3`, khác runner;
PPD đã dừng trước cả hai request. Candidate v3 sau đó bổ sung
`tgid=2337 ppid=1 uid=0` và kiểm tra process chỉ đọc đã nhận diện
`/usr/bin/python3 -m awccd.main`. Vì vậy đây là root daemon `awccd.service`,
không phải EC/firmware tự gọi WMAX. Chi tiết và phương án cô lập daemon:
[PHASE5D_PROFILE_CALLER_ATTRIBUTION.md](PHASE5D_PROFILE_CALLER_ATTRIBUTION.md)
và [PHASE5E_AWCCD_CONFLICT.md](PHASE5E_AWCCD_CONFLICT.md).
