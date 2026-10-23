# Nghiên cứu `dell-smm-hwmon`

Ngày kiểm tra: 2026-10-09.

## Trạng thái thực tế đã đọc

- kernel: `7.0.0-38-generic`, package source `linux-hwe-7.0`
  `7.0.0-38.38~24.04.4`;
- module `dell_smm_hwmon` và `alienware_wmi` đang nạp;
- bốn `pwm1_enable` … `pwm4_enable` đều tồn tại, mode `0644`, đọc là `2`;
- bốn thermal cooling device `dell-smm-fan1` … `fan4` có `max_state=2`;
- đọc `cur_state` trả `ENODATA` khi firmware báo automatic state.

Không có thao tác ghi nào được thực hiện để thu thập dữ liệu trên.

## Đường code giải thích hiện tượng

Trong upstream Linux 7.0, driver có hai phương pháp:

1. `auto_fan != 0`: dùng một cặp SMM command global từ
   `i8k_whitelist_fan_control[]`. Chỉ `pwm1_enable` xuất hiện và là write-only.
2. `auto_fan == 0`: fallback theo từng fan. `pwmX_enable=1` gọi
   `i8k_set_fan(channel, i8k_fan_max)`; `pwmX_enable=2` đặt special state
   `I8K_FAN_AUTO` (state 3).

Máy hiện có cả bốn `pwmX_enable` đọc/ghi và `max_state=2`, do đó khớp chính xác
với nhánh fallback thứ hai. Ở nhánh này, ghi `1` không gọi một lệnh “disable EC
automatic control” độc lập; nó chỉ gửi state 2 (max) cho fan đó. Hàm đọc trả
`2` khi firmware báo state 3. Đây là lời giải thích có căn cứ cho quan sát:

```text
write pwmX_enable=1 → fan đổi tạm thời → firmware trả state 3 → read = 2
```

## Whitelist

Upstream Linux 7.0 công bố hai cặp command:

```text
manual 0x30a3 / auto 0x31a3
manual 0x34a3 / auto 0x35a3
```

`Alienware x17 R1` không có trong `i8k_whitelist_fan_control[]`. Danh sách chỉ
cho phép các model đã biết dùng đúng một trong hai cặp. Việc thêm DMI entry mà
chưa biết cặp nào đúng sẽ biến một giả thuyết thành raw SMM call có rủi ro.

## Mức độ kết luận

### Đã xác nhận

- runtime layout của máy là per-fan fallback;
- firmware đang trả automatic state cho cả bốn fan;
- kết quả đọc sysfs phù hợp với logic upstream Linux 7.0;
- x17 R1 không nằm trong whitelist upstream Linux 7.0.

### Suy luận mạnh, chưa xác minh trên phần cứng

- một global command pair đúng có thể là điều kiện cần để giữ manual takeover;
- patch whitelist chỉ hữu ích nếu một trong hai pair thực sự được firmware x17
  R1 hỗ trợ.

### Chưa biết

- x17 R1 dùng `0x30a3/0x31a3`, `0x34a3/0x35a3`, cặp khác, hay chặn global
  takeover hoàn toàn;
- AWCC/EC có một arbitration layer khác sẽ giành quyền lại sau global command;
- Ubuntu có patch riêng ảnh hưởng driver hay không. Source package chính xác
  chưa được cài local; runtime ABI hiện khớp upstream 7.0 ở các nhánh liên quan.

## Bước tiếp theo an toàn

1. Lấy source package `linux-hwe-7.0` đúng version và diff với upstream 7.0.
2. Tìm bằng chứng model gần cùng thế hệ/EC dùng command pair nào; không probe
   ngẫu nhiên.
3. Nếu có căn cứ đủ mạnh, tạo module thử nghiệm riêng và patch DMI nhỏ để review;
   không load module cho tới khi người dùng cho phép.
4. Trước test thật phải có tải CPU/GPU thấp, giám sát nhiệt độc lập, timeout và
   lệnh phục hồi auto đã biết.

## Nguồn chính

- Linux 7.0: `drivers/hwmon/dell-smm-hwmon.c`
- Linux kernel documentation: `hwmon/dell-smm-hwmon`
- Ubuntu source package: `linux-hwe-7.0` version `7.0.0-38.38~24.04.4`
