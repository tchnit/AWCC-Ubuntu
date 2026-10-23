# Giai đoạn 5H — end-to-end hardware write qua helper ứng dụng

Ngày: 2026-10-10. Máy: Alienware x17 R1, BIOS 1.27.0, kernel
`7.0.0-38-generic`.

## Kết luận

Đường hardware write mà desktop app dùng đã được xác minh end-to-end. Installed
`/usr/libexec/awcc-profile-helper` nhận yêu cầu Quiet, ghi platform profile và
read-back `quiet` ba lần (ngay sau write, 0,75 giây, 2,75 giây). Sau đó runner
gọi cùng helper để ghi/kiểm chứng `balanced` ba lần và khôi phục hoàn toàn.

Đây là bằng chứng cho **profile control**, không phải bằng chứng điều khiển quạt
thủ công. Không có PWM, SMM, Game Shift, AWCC fan boost hay module load trong
run này.

## Guard và kết quả

Preflight xác nhận stock `alienware_wmi` srcversion
`28A4134FBF8432C66D7C668`, baseline Balanced, PPD active, AC online, không
holder module, `awccd` inactive/socket absent, và helper root-owned/không
group- hoặc world-writable. CPU baseline là 50 °C. Runner có watchdog 30 giây;
nếu parent bị gián đoạn watchdog gọi cùng helper để trả Balanced.

| Mốc | Kết quả |
| --- | --- |
| Helper `set-profile quiet` | exit 0; `quiet`, `quiet`, `quiet`; persistent true |
| Snapshot sau helper | profile Quiet; PPD vẫn active; `awccd` vẫn vắng mặt |
| Helper restore Balanced | exit 0; `balanced`, `balanced`, `balanced`; persistent true |
| Trạng thái cuối | stock driver, Balanced, PPD active, CPU/GPU 51/48 °C |

Log nguyên bản: [hardware-test-profile-helper-quiet-e2e-2026-10-10.jsonl](../research/results/hardware-test-profile-helper-quiet-e2e-2026-10-10.jsonl).

## Hệ quả UI

Preset **Yên tĩnh** và card Thermal profile tương ứng đều có thể gửi hardware
write này qua PolicyKit. Tại thời điểm này Fan modes/curve vẫn chỉ preview, và
`low-power`, `custom`, PWM và boost vẫn giữ khóa theo bằng chứng riêng. Phase
5I sau đó mở Performance qua PPD, không qua helper fallback; UI Fan modes/curve
sau đó đã được gỡ để thiết kế lại.
