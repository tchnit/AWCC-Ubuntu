# Kiểm chứng trước khi mở các phần còn khóa — 2026-10-13

Người dùng yêu cầu mở tất cả các phần còn khóa. Quiet, Balanced và Performance
qua PPD đã mở; Low Power, Balanced+ và Custom chưa có kiểm chứng riêng. Manual
fan không có actuator production và không được coi là hoàn tất bằng một cờ UI.

## Phép thử đã chuẩn bị

- Low Power: `powerprofilesctl set power-saver` dưới desktop user, quan sát
  đủ tám mẫu/10 giây cả PPD và platform; không nhầm Quiet/power-saver alias với
  Low Power thật. Mọi mẫu phải có platform `low-power`.
- Balanced+/Custom: root diagnostic riêng chỉ nhận hai target firmware quảng
  bá, exact confirmation, DMI/BIOS và stock-driver preflight từ guardian. Không
  thêm API bỏ qua policy vào production helper. Tám mẫu/10 giây, rồi restore
  Balanced và xác minh ba mẫu.
- CPU/GPU phải hợp lệ, AC online, không awccd/i8kmon, BIOS-auto trên cả bốn fan.
  Baseline tối đa 60 °C; riêng Custom tối đa 50 °C. Root probe dừng ở 75 °C.
- Independent guardian/watchdog giữ profile ban đầu và khôi phục qua PPD.
  Mỗi phép thử có log riêng; không ghi boost/PWM, SMM hoặc thay driver/service.
- Profile được mở trong production policy chỉ sau khi có write/readback,
  restoration và kiểm chứng lại qua đúng client/helper của app. Custom nếu
  giữ được chỉ là thermal profile; nó không cấp capability manual fan.

## Trạng thái lần kiểm tra đầu

ACAD/online=0, awccd/i8kmon inactive, không awccd socket. Baseline vẫn là
Performance. Guardian dừng ngay trong preflight, trước write và trước arm
watchdog. Không thay đổi policy/app để báo hỗ trợ sai.

Evidence:
`research/results/hardware-test-remaining-profiles-2026-10-13.jsonl`.
Run kế tiếp dùng file `...-run2.jsonl`, giữ nguyên log lần đầu.

Tiếp tục khi máy nhận nguồn AC. Sau đó chỉ mở các profile thực sự qua được
kiểm chứng; manual fan cần nghiên cứu backend riêng vì hiện chưa có actuator.

## Bổ sung sau khi người dùng cắm sạc

Run2 xác nhận Low Power/Balanced+ qua tám mẫu và restore đạt. Custom chưa được
thử ở bước đó do CPU 57 °C. Phép thử riêng từ Low Power đã hạ CPU còn 50 °C,
Custom giữ tám mẫu, nhiệt độ CPU 49 °C; restore Low Power và Performance đạt.
Policy/app/helper 0.1.2 đã mở ba thermal profile này; Custom giữ guard thực.
Manual fan không được mở bằng cách đặt capability giả.

Các lần production-client đầu có timeout và runner giả định sai coarse PPD
mode. Sau khi phân biệt hai trạng thái và người dùng xác thực PolicyKit, run4
đạt Low Power/Balanced+/Custom, chuyển về mode chuẩn và restore Performance.
Ghi đầy đủ lỗi lịch sử, bằng chứng đạt và giới hạn trong
[Phase 5K](PHASE5K_ALL_THERMAL_PROFILES.md). Manual vẫn thiếu actuator.

Evidence mới:
`research/results/hardware-test-remaining-profiles-2026-10-13-run2.jsonl`,
`research/results/hardware-test-custom-cooled-2026-10-13.jsonl`.
