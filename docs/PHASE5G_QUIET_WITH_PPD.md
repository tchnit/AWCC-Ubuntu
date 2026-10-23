# Giai đoạn 5G — Quiet khi `power-profiles-daemon` vẫn active

Ngày: 2026-10-10. Máy: Alienware x17 R1, BIOS 1.27.0, kernel
`7.0.0-38-generic`.

## Kết luận

Quiet giữ nguyên ở toàn bộ 10 mẫu khi `power-profiles-daemon` vẫn active, với
`awccd.service` inactive và socket của nó vắng mặt. Vì vậy PPD không phải writer
ghi đè Quiet trong cửa sổ quan sát; nguyên nhân cạnh tranh đã biết là `awccd`.

Phép thử chỉ ghi `quiet` một lần qua stock platform-profile ABI, quan sát 10 lần
mỗi 250 ms, sau đó khôi phục `balanced`. Không nạp/unload driver, không gọi SMM,
Game Shift, PWM hay AWCC fan boost. Watchdog độc lập 30 giây vẫn được arm.

## Điều kiện và bằng chứng

Preflight xác nhận driver gốc `28A4134FBF8432C66D7C668`, AC online, không có
module holder, baseline Balanced, PPD active và `awccd` inactive/socket absent.
Nhiệt CPU là 59 °C, thấp hơn guard 60 °C; telemetry GPU lúc đầu trả 2–3 °C rồi
50 °C nên không được dùng làm bằng chứng hiệu năng quạt.

| Mốc | Profile | PPD | Kết quả |
| --- | --- | --- | --- |
| Ngay sau write | Quiet | active | sysfs write trả về thành công |
| 10 mẫu, ~0,27–2,89 giây | Quiet | active ở mọi mẫu | Không có `awccd` |
| Restore | Balanced | active | stock driver vẫn giữ nguyên |

Kết quả tiêu chuẩn hóa từ runner:
[hardware-test-quiet-with-ppd-2026-10-10.jsonl](../research/results/hardware-test-quiet-with-ppd-2026-10-10.jsonl).

## Thay đổi ứng dụng

Quiet được mở riêng trên đúng model/BIOS này, nhưng không đi qua PPD vì PPD
không công bố mode Quiet. UI dùng privileged helper có allow-list và read-back
2,75 giây; PPD tiếp tục quản lý các mode chuẩn mà nó công bố. Socket `awccd`
vẫn chặn mọi write mới. Đây chỉ là platform profile, không phải manual fan
control và không mở AWCC boost/PWM/curve actuator.

Tại thời điểm thử nghiệm này, `low-power`, `performance` và `custom` tiếp tục bị
khóa do chưa có bằng chứng cô lập tương ứng. Phase 5I sau đó đã xác minh riêng
Performance qua PPD; `low-power` và `custom` vẫn khóa. Không lặp lại Quiet hoặc
thử thêm SMM/mode chỉ vì kết quả lịch sử này.
