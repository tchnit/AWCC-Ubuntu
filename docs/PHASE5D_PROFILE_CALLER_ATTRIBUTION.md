# Giai đoạn 5D — attribution của request Balanced

Ngày: 2026-10-10. Máy: Alienware x17 R1, BIOS 1.27.0, kernel
`7.0.0-38-generic`.

## Kết luận

Nguồn của request `Balanced` (`0xA0`) quan sát ở Phase 5C là một **client Linux
`python3` khác**, không phải EC/firmware tự phát lệnh WMAX. Đây là kết luận từ
ngữ cảnh của callback kernel, không suy diễn từ thời điểm read-back.

Tuy nhiên executable, argv và chủ sở hữu chính xác của client chưa được thu
thập: PID đó đã thoát trước khi có thể đọc `/proc`. Vì vậy không được quy cho
ứng dụng AWCC này, `power-profiles-daemon`, GNOME hay một script cụ thể khi chưa
có bằng chứng bổ sung.

`quiet` vẫn phải khóa trong UI. Dù firmware nhận `0xA3`, tồn tại writer cạnh
tranh khiến application chưa thể hứa trạng thái ổn định; điều này cũng chưa mở
đường manual fan control.

## Phép thử được cấp phép

Đây là lần chạy duy nhất của candidate attribution v2, theo cấp phép riêng.
Candidate được tạo offline từ source Ubuntu HWE đúng phiên bản, SHA-256:

```
2dd22cca0e6457ad904d569e580a2a63d01fbd719defd42be35b9e413a3d9482
```

Nó chỉ thêm logging rate-limited tại đầu
`awcc_platform_profile_set()`: PID, `comm`, profile platform và AWCC ID. Không
thêm hay thay đổi WMI/SMM/PWM/boost/profile mapping. Runner dùng lại toàn bộ
preflight, DMI/BIOS/AC/nhiệt độ, watchdog 30 giây và khôi phục driver stock từ
Phase 5C; chỉ thay artefact logging.

## Bằng chứng kernel và journal

Journal trên host ghi các mốc sau (giờ địa phương `+07:00`):

| Thời điểm | Bằng chứng | Diễn giải |
| --- | --- | --- |
| 10:01:43 | PPD đã stop | daemon không chạy trong cửa sổ write |
| 10:01:43 | `AWCC_ATTRIB setter pid=36666 comm=python3 profile=2 profile_id=0xa3` | runner gửi Quiet theo kế hoạch |
| 10:01:44 | `AWCC_ATTRIB setter pid=2350 comm=python3 profile=3 profile_id=0xa0` | writer khác gửi Balanced |
| 10:01:46 | `AWCC_ATTRIB setter pid=36666 comm=python3 profile=3 profile_id=0xa0` | bước restore Balanced theo thiết kế runner |
| 10:01:46 | PPD đã start | khôi phục dịch vụ hoàn tất |

Cả request `0xA3` và `0xA0` đều có wrapper log raw `0x00000000`. Vì log
attribution nằm trước đường WMAX, `pid=2350/comm=python3` là caller thực tế của
setter, không phải tên do firmware cung cấp.

Sau khi runner kết thúc, kiểm tra chỉ đọc xác nhận profile `balanced`, driver
stock `alienware_wmi` srcversion `28A4134FBF8432C66D7C668`, kernel
`7.0.0-38-generic`, BIOS `1.27.0`. Phiên môi trường cô lập không được phép truy
vấn systemd trực tiếp; journal của runner là bằng chứng PPD được start lại.

## Cập nhật sau attribution v3: nguồn đã xác định

Candidate v3 đã được build và nạp một lần theo permission riêng. Nó thêm TGID,
PPID và UID vào marker và ghi `pid=2350 tgid=2337 ppid=1 uid=0`. Kiểm tra
process chỉ đọc sau đó nhận diện TGID 2337 là
`/usr/bin/python3 -m awccd.main`, do `awccd.service` khởi động.

Vì vậy phần “executable chưa biết” của 5D đã được giải quyết: đây là root daemon
AWCC ngoài workspace. Không suy ra Quiet sẽ ổn định khi daemon dừng; phép thử
mới vẫn cần thiết. Cũng không mở khóa mode, profile hoặc manual fan control chỉ
vì firmware nhận một write đơn lẻ. Chi tiết trạng thái live của daemon, nguồn
enforce và phương án cô lập có rollback: [PHASE5E_AWCCD_CONFLICT.md](PHASE5E_AWCCD_CONFLICT.md).
