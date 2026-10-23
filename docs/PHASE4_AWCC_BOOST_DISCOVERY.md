# Giai đoạn 4 — phát hiện AWCC fan boost native

Ngày thực hiện: 2026-10-09.

## Kết luận kiến trúc

`alienware_wmi` là nhánh điều khiển quạt ưu tiên mới. Kernel đang chạy đã expose
giao diện AWCC-native cho đúng máy này, nên không cần dựa vào global SMM takeover
đã thất bại của `dell_smm_hwmon`.

Đây là fan **boost**, không phải PWM tuyệt đối. Theo tài liệu kernel, quan hệ xấp
xỉ là:

```text
pwm = pwm_base + (fan_boost / 255) * (pwm_max - pwm_base)
```

Firmware vẫn giữ `pwm_base`, do đó mô hình an toàn khác với việc tắt hoàn toàn
BIOS fan control.

## Trạng thái read-only trên Alienware x17 R1

Provider `/sys/class/hwmon/.../name` là `alienware_wmi` và expose bốn kênh:

| Kênh | Nhãn | RPM / max lúc kiểm tra | Boost | Sensor |
|---|---|---:|---:|---:|
| 1 | CPU Fan | 4100 / 4100 | 255 | temp1 CPU |
| 2 | GPU Fan | 4100 / 4100 | 250 | temp2 GPU |
| 3 | CPU Fan | 2700 / 2700 | 255 | temp1 CPU |
| 4 | GPU Fan | 2000 / 2000 | 250 | temp2 GPU |

Các giá trị trên giữ nguyên trong sáu mẫu cách nhau hai giây, với CPU 45–46 °C
và GPU 40 °C. Platform profile là `balanced`.

Chưa biết boost cao này là trạng thái profile/firmware hay còn liên quan đến
trình tự thử nghiệm trước. Không tự ghi `0` vì đó sẽ là một thay đổi điều khiển
quạt mới cần gate riêng.

## Thay đổi ứng dụng

- Backend đọc riêng bốn AWCC fan channel, gồm RPM, min/max, boost và temperature
  channel mapping.
- Không merge theo số kênh với `dell_smm`: hai provider có thứ tự kênh khác nhau
  trên máy này.
- UI ưu tiên AWCC fan list; `dell_smm` chỉ là telemetry fallback.
- Capability report công bố AWCC boost có mặt nhưng vẫn giữ
  `stable_manual_fan_control = false` vì hiệu lực RPM chưa được kiểm chứng.

## Đánh giá `0x30a3/0x31a3`

Upstream dùng pair này cho Dell G15 5511 dựa trên báo cáo cần tắt BIOS fan
control, và sau đó cho G15 5510 vì cùng configuration. Không có bằng chứng trực
tiếp cho Alienware x17 R1. Khi AWCC-native boost đã hiện diện và được kernel mô
tả chính thức, thử thêm SMM opcode legacy có rủi ro cao hơn và ít giá trị hơn.

Quyết định hiện tại: không tạo hoặc nạp candidate `30a3/31a3`; giữ nhánh này làm
fallback research nếu AWCC boost được chứng minh không hoạt động trên x17 R1.

## Gate thử phần cứng tiếp theo

Một phép thử AWCC boost nên:

1. chụp lại cả bốn boost, RPM, nhiệt độ và profile;
2. chỉ thay đổi một kênh, vẫn giữ mức boost cao trong lần thử đầu;
3. xác minh sysfs read-back và RPM qua nhiều mẫu;
4. abort nếu sensor stale, nhiệt độ vượt trần hoặc RPM biến đổi ngoài dự kiến;
5. luôn khôi phục chính xác giá trị ban đầu trong `finally` và watchdog;
6. không đồng thời ghi `dell_smm` hoặc đổi platform profile.

Runner offline đã được chuẩn bị tại
`research/awcc_boost_test_runner.py`. Nó cố định lần thử đầu ở kênh 1,
`255 → 224` trong tám giây, không cho phép tăng boost, yêu cầu exact DMI/AC/
`balanced`, dùng watchdog 15 giây và khôi phục cả bốn giá trị ban đầu. Runner từ
chối chạy nếu thiếu cờ xác nhận dài dành riêng cho phép thử. Trước test, file
chỉ tồn tại offline; bản root-owned được cài tạm sau khi có authorization và đã
được dọn sau test.

## Kết quả thực thi

Sau khi được người dùng cho phép, runner đã được cài tạm root-owned và thực thi.
`fan1_boost=224` được giữ qua tám lần read-back nhưng fan 1 vẫn ở 4100 RPM. Cả
bốn boost sau đó được khôi phục đúng và artifact hệ thống tạm đã được dọn. Xem
[PHASE4_HARDWARE_TEST_AWCC_BOOST.md](PHASE4_HARDWARE_TEST_AWCC_BOOST.md).

## Nguồn chính

- Linux kernel documentation: `Documentation/admin-guide/laptops/alienware-wmi.rst`
- Linux sysfs ABI: `Documentation/ABI/testing/sysfs-platform-alienware-wmi`
- Linux `drivers/platform/x86/dell/alienware-wmi-wmax.c`
- Upstream G15 5511 whitelist patch and maintainer review
