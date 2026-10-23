# Giai đoạn 5I — Performance qua `power-profiles-daemon`

Ngày: 2026-10-10. Máy: Alienware x17 R1, BIOS `1.27.0`, kernel
`7.0.0-38-generic`.

## Kết luận

Profile **Performance** đã được xác minh qua đúng đường normal-user mà desktop
app dùng: `powerprofilesctl set performance`. Đây là route
`power-profiles-daemon` (PPD), không phải helper đặc quyền, Game Shift, SMM,
PWM hay AWCC fan boost.

PPD và `alienware_wmi` platform profile cùng giữ `performance` ở cả bốn mẫu
trong cửa sổ xác minh hai giây. Runner sau đó gọi `powerprofilesctl set
balanced` và xác nhận cả hai giá trị đã về Balanced. Vì vậy app mở Performance
khi PPD active và công bố mode này.

## Điều kiện và guard

Runner chỉ chạy khi DMI/BIOS khớp chính xác, AC online, PPD và platform profile
đang Balanced, `awccd` socket vắng mặt, Performance được firmware công bố và
nhiệt độ baseline không quá 60 °C. Nó từ chối chạy qua root/`pkexec`, có lock
riêng trong `/tmp`, watchdog 30 giây và restore Balanced trên mọi nhánh sau khi
preflight đã cho phép write.

Không module nào được nạp/tháo, không thay đổi cấu hình hệ thống và không có
lệnh manual-fan nào trong run.

## Kết quả

| Mốc | PPD | platform profile | CPU / GPU |
| --- | --- | --- | --- |
| Baseline | balanced | balanced | 49 / 2 °C |
| Mẫu 1 | performance | performance | 49 / 3 °C |
| Mẫu 2 | performance | performance | 50 / 3 °C |
| Mẫu 3 | performance | performance | 50 / 3 °C |
| Mẫu 4 (2 giây) | performance | performance | 50 / 46 °C |
| Restore | balanced | balanced | 50 / 46 °C |

Log nguyên bản: [hardware-test-performance-ppd-e2e-2026-10-10.jsonl](../research/results/hardware-test-performance-ppd-e2e-2026-10-10.jsonl).

## Phạm vi mở khóa

Mở **Performance qua PPD** chỉ khi PPD đang active và công bố Performance.
Fallback privileged helper vẫn bị UI chặn trên x17 R1 / BIOS 1.27.0 vì chưa có
phép thử độc lập cho route đó. `low-power`, `custom`, fan boost, PWM, Game Shift
và mọi manual fan curve vẫn không được mở bởi kết quả này.
