# Giai đoạn 3 — driver research và offline patch

Ngày thực hiện: 2026-10-09.

## Source được đối chiếu

- Installed package: `linux-modules-7.0.0-38-generic`, source package
  `linux-hwe-7.0 7.0.0-38.38~24.04.4`.
- Official Ubuntu source diff đã lưu tại
  `research/sources/ubuntu-hwe-7.0/linux-hwe-7.0.diff.gz`.
- Upstream Linux v7.0 driver đã lưu tại
  `research/sources/upstream-v7.0/dell-smm-hwmon.c`.

Ubuntu diff không có file header cho `drivers/hwmon/dell-smm-hwmon.c`, nghĩa là
package không mang Ubuntu-specific patch cho driver này. Runtime sysfs layout
cũng khớp upstream.

## Bằng chứng command pair

### `0x34a3 / 0x35a3`

Một boot log công khai từ đúng model Alienware x17 R1 cho thấy
`dell-bios-fan-control` được chạy cùng `i8kmon`. Source của utility đó dùng
`0x34a3` để disable và `0x35a3` để enable BIOS control.

Đây chưa phải xác nhận: utility bỏ qua return code của `i8k_smm()` và luôn in
thông báo thành công. Log không chứng minh EC ngừng giành lại quyền.

### `0x30a3 / 0x31a3`

Upstream đã whitelist Dell G15 5511 và G15 5510 với pair này dựa trên báo cáo
manual fan control thực tế. Đây là máy gaming Dell cùng giai đoạn với x17 R1,
nhưng không đủ để suy ra SMM ABI giống nhau.

Chi tiết phân loại bằng chứng nằm trong
`research/notes/COMMAND_PAIR_EVIDENCE.md`.

## RFC patch

Đã tạo candidate:

```text
research/patches/0001-EXPERIMENTAL-dell-smm-add-alienware-x17-r1-34a3.patch
```

Patch chỉ thêm một exact DMI match:

```text
sys_vendor   = Alienware
product_name = Alienware x17 R1
pair         = I8K_FAN_34A3_35A3
```

Đây là lựa chọn thử nghiệm vì có bằng chứng trực tiếp theo model, dù bằng chứng
đó yếu. Patch được đánh dấu `RFC DO NOT MERGE`.

## Build result

Candidate đã build thành công với headers của kernel đang chạy:

```text
name:      dell_smm_hwmon_x17r1
vermagic:  7.0.0-38-generic SMP preempt mod_unload modversions
SHA-256:   0362b17f8241eac0fd1e0a82982a55b6549496ff70c5177c0846983af7c4a1f8
```

Đây là hash của artifact hiện tại; debug/build metadata có thể làm hash đổi khi
build lại trong một temporary path khác. Compiler version khớp kernel compiler.
BTF bị bỏ qua vì headers không cung cấp `vmlinux`, nhưng điều này không làm build
thất bại. Candidate chưa ký; Secure Boot hiện disabled.

## Kết quả hardware test

Candidate đã được thử trên máy thật sau khi người dùng cho phép. Firmware trả
`EINVAL` ngay tại global disable command `0x34a3`; `0x35a3` trong emergency
restore và watchdog cũng trả `EINVAL`. Test dừng trước khi yêu cầu giảm tốc bất
kỳ fan nào. Driver Ubuntu gốc sau đó đã được khôi phục và cả bốn
`pwm*_enable` được xác minh bằng `2`.

Vì vậy cặp `0x34a3/0x35a3` bị bác bỏ trên x17 R1 BIOS 1.27.0 và patch này không
đủ điều kiện để merge hoặc dùng làm backend. Xem báo cáo chi tiết tại
[PHASE3_HARDWARE_TEST_34A3.md](PHASE3_HARDWARE_TEST_34A3.md).

## Những gì không được thực hiện trong giai đoạn build offline

- không unload module Ubuntu;
- không load candidate;
- không chạy raw SMM utility;
- không ghi `pwm` hoặc `pwm_enable`;
- không thay initramfs, modules tree hoặc boot configuration.

Module đang chạy sau build vẫn là:

```text
/lib/modules/7.0.0-38-generic/kernel/drivers/hwmon/dell-smm-hwmon.ko.zst
```

## Gate đã dùng cho hardware test

Một test thật chỉ nên tiến hành sau khi có kế hoạch riêng bao gồm:

1. workload bằng 0, nhiệt độ thấp và nguồn AC ổn định;
2. telemetry watcher độc lập với ứng dụng thử nghiệm;
3. thử global manual command rồi đặt tất cả fan ở maximum state trước;
4. xác minh fan command giữ hiệu lực qua nhiều khoảng thời gian;
5. global auto command trong `finally`/watchdog và giới hạn timeout;
6. đường phục hồi bằng reboot/power cycle nếu auto command thất bại;
7. chỉ thử một command pair mỗi phiên để kết quả không bị lẫn.

Do firmware không công bố trạng thái global manual/auto, việc xuất hiện một
write-only `pwm1_enable` sau patch chỉ xác nhận DMI match, không xác nhận command
pair hoạt động.

Read-only preflight được triển khai tại `research/preflight.py`; hardware test
plan và rollback order nằm trong `docs/HARDWARE_TEST_PLAN.md`. Các gate đã pass
trước test thật. Kết quả đã bác bỏ candidate thay vì mở khóa giai đoạn 4.

## Nguồn

- Linux v7.0 `drivers/hwmon/dell-smm-hwmon.c`
- Linux kernel documentation `hwmon/dell-smm-hwmon`
- Ubuntu `linux-hwe-7.0` source package
- Upstream patches thêm Dell G15 5510/5511
- TomFreudenberg `dell-bios-fan-control` source
- Arch Linux x17 R1 boot log
