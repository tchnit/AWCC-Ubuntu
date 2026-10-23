# Giai đoạn 5F — Quiet với `awccd` đã cô lập

Ngày: 2026-10-10. Máy: Alienware x17 R1, BIOS 1.27.0, kernel
`7.0.0-38-generic`.

## Kết luận

Với `awccd.service` inactive/socket absent và `power-profiles-daemon` tạm dừng,
stock driver đã giữ `quiet` xuyên suốt 10 mẫu trong 2,5 giây. Không có module
diagnostic, Game Shift, SMM, PWM hay boost write trong phép thử này.

Điều này xác nhận firmware nhận và duy trì Quiet ít nhất trong cửa sổ ngắn khi
không có writer cạnh tranh. Nó bác bỏ giả thuyết trước đây rằng BIOS 1.27.0 tự
đổi Quiet về Balanced sau khoảng 1–2 giây. Nó chưa chứng minh Quiet sẽ giữ khi
PPD active hoặc qua thời gian dài, nên UI vẫn khóa Quiet.

## Điều kiện và kết quả

Preflight xác nhận stock `alienware_wmi` srcversion
`28A4134FBF8432C66D7C668`, Balanced, PPD active, AC online, nhiệt CPU 56 °C,
`awccd` inactive/socket absent, và không có module holder. Runner dừng PPD,
ghi đúng một `quiet`, rồi quan sát mỗi 250 ms:

| Mốc | Profile | PPD | Ghi chú |
| --- | --- | --- | --- |
| ngay sau write | Quiet | inactive | sysfs write trả về thành công |
| 0,26–2,78 giây | Quiet ở cả 10 mẫu | inactive | không có writer cạnh tranh |
| restore | Balanced | active | stock driver giữ nguyên |

Các giá trị RPM/telemetry trong cửa sổ này vẫn không nhất quán (một số kênh trả
0 rồi 1900–2000 RPM), nên chúng không phải bằng chứng manual takeover hay tốc
độ quạt vật lý. Runner chỉ dùng nhiệt độ và deadline làm guard; CPU/GPU EC cuối
là 56/47 °C, thấp hơn ngưỡng emergency 85 °C.

Log đã chuẩn hóa từ output runner:
[hardware-test-isolated-quiet-2026-10-10.jsonl](../research/results/hardware-test-isolated-quiet-2026-10-10.jsonl).

## Trạng thái cuối đã xác nhận

- `awccd` vẫn inactive, socket absent;
- profile `balanced`, PPD `active`;
- driver gốc `28A4134FBF8432C66D7C668`;
- AWCC boost `0, 0, 0, 0`.

## Bước tiếp theo có cơ sở

Phân biệt nốt vai trò PPD bằng một phép thử tương tự nhưng **giữ PPD active**:
chỉ một write Quiet, quan sát 2,5 giây, xác nhận `awccd` vẫn inactive, rồi
restore Balanced. Đây là hardware write mới nên cần permission riêng. Nếu Quiet
giữ trong cả hai điều kiện, mới cân nhắc mở profile Quiet qua helper với
read-back dài hơn; điều này vẫn không mở manual fan control.
