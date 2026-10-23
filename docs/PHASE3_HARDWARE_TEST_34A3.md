# Giai đoạn 3 — kết quả thử phần cứng `0x34a3/0x35a3`

Ngày thực hiện: 2026-10-09.

## Kết luận

Giả thuyết Alienware x17 R1 BIOS 1.27.0 hỗ trợ cặp lệnh global fan-control
`0x34a3/0x35a3` bị bác bỏ. Candidate driver nạp đúng và expose đúng giao diện
thử nghiệm, nhưng firmware trả lỗi `EINVAL` ngay khi driver gửi lệnh
`0x34a3` để tắt BIOS fan control.

Phép thử dừng trước thao tác đặt fan 1 về mức giữa. Không có thử nghiệm tốc độ
thấp và không có giai đoạn điều khiển quạt thủ công.

## Môi trường và artifact

- Model: Alienware x17 R1
- BIOS: 1.27.0
- Kernel: `7.0.0-38-generic`
- Candidate: `dell_smm_hwmon_x17r1`
- Candidate SHA-256:
  `0362b17f8241eac0fd1e0a82982a55b6549496ff70c5177c0846983af7c4a1f8`
- DMI config thử nghiệm: `I8K_FAN_34A3_35A3`

## Quan sát theo thứ tự

1. Preflight pass: nguồn AC online, platform profile `balanced`, cả bốn fan ở
   BIOS auto, nhiệt độ 36–43 °C.
2. Driver Ubuntu gốc được unload; candidate được nạp bằng `insmod`.
3. Candidate expose bốn `pwm` node và đúng một global write-only
   `pwm1_enable` mode `0200`, xác nhận exact DMI match đã được chọn.
4. Cả bốn fan được yêu cầu maximum trước global command. RPM quan sát là
   6400/6800/6500/5000.
5. Ghi `1` vào `pwm1_enable`, tương ứng `0x34a3`, trả về
   `OSError(22, "Invalid argument")`.
6. Emergency restore bằng ghi `2`, tương ứng `0x35a3`, cũng trả `EINVAL`;
   watchdog độc lập thử lại sau 15 giây và nhận cùng kết quả.
7. Runner giữ candidate đang nạp theo fail-safe vì không xác nhận được auto
   command. Candidate sau đó được tháo bằng `rmmod` và driver Ubuntu gốc được
   nạp lại.

Vì lệnh disable đầu tiên bị firmware từ chối, BIOS gần như chắc chắn chưa
nhường quyền điều khiển quạt. Lỗi của lệnh enable vì vậy không có nghĩa máy bị
kẹt trong manual mode; nó cho thấy cả hai opcode đều không được firmware này
chấp nhận.

## Trạng thái sau khôi phục

- Module đang nạp: `dell_smm_hwmon` gốc từ
  `/lib/modules/7.0.0-38-generic/kernel/drivers/hwmon/dell-smm-hwmon.ko.zst`
- `pwm1_enable` đến `pwm4_enable`: đều bằng `2`
- Platform profile: `balanced`
- Nguồn AC: online
- Nhiệt độ xác minh: 39–44 °C
- RPM xác minh: 4100/2700/4100/2000

## Hệ quả đối với thiết kế

- Không merge hoặc phân phối patch `34a3/35a3`.
- Không mở khóa manual fan control trong ứng dụng.
- Boot log công khai chạy `dell-bios-fan-control` không phải bằng chứng command
  pair hoạt động, vì utility đó bỏ qua return status của SMM call.
- Không thử `0x30a3/0x31a3` trong cùng phiên. Pair khác chỉ được xem xét sau một
  vòng evidence review, kế hoạch thử riêng và sự cho phép rõ ràng của người
  dùng.

## Sửa lỗi test harness

Candidate được nạp trực tiếp bằng `insmod`, không được cài vào modules tree và
không có entry trong `modules.dep`. Vì vậy `modprobe -r
dell_smm_hwmon_x17r1` không tìm thấy module dù nó đang nạp. Runner đã được sửa
dùng `rmmod dell_smm_hwmon_x17r1`, sau đó mới `modprobe dell_smm_hwmon`.
