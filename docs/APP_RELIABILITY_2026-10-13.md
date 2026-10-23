# Hoàn thiện app: mục 1–6 — 2026-10-13

Phiên bản app/helper: 0.1.1. Bộ kiểm thử sau hardware fixes: 148 bài đạt, gồm 18 bài GTK;
render kiểm tra preset, thermal profiles, cảm biến và quạt đã thành công.
App và helper 0.1.1 đã được cài đồng bộ sau khi người dùng cấp phép. Kiểm tra
payload/quyền root và smoke test GTK của bản đã cài đạt; đây không phải bằng
chứng hardware write mới.

## Thay đổi

- PPD chỉ báo thành công sau đủ bốn mẫu trong hai giây, cả PPD và Alienware
  platform profile đều đúng. Lấy baseline trực tiếp trước write, không dùng
  cached ActiveProfile làm trạng thái cần khôi phục.
- Khi request lỗi, timeout hoặc không giữ profile, thử khôi phục baseline rồi
  xác minh lại. Profile chuẩn khôi phục qua PPD; Quiet qua helper khớp source.
  Không ghi trực tiếp Performance bằng helper. Không có đường khôi phục đã
  xác minh thì dừng trước write. Lỗi khôi phục luôn là lỗi, không báo thành công.
- Helper có recovery khi write/read-back bị lỗi và SIGTERM/SIGINT trong
  transaction. SIGKILL/mất điện không có bảo đảm recovery. Đây là profile
  control; không phải actuator fan hoặc watchdog độc lập cho fan.
- App kiểm tra root ownership, quyền file và nội dung các module helper trước
  khi cho phép sử dụng. Helper cũ bị coi là chưa sẵn sàng, có lý do trên card.
  `python3 tools/check-helper.py` kiểm tra chỉ đọc; installer helper kiểm tra
  payload sau khi copy và lưu bản cũ trong `/var/backups/awcc-helper.*`.
  Desktop installer vẫn không nâng cấp helper hệ thống.
- Snapshot/`nvidia-smi` chạy ở background với tối đa một request đang chạy.
  Delivery quay về GTK; đóng cửa sổ hủy timer và bỏ qua kết quả đến muộn.
- Control cards và sensor/fan rows cập nhật tại chỗ; widget ổn định khi các
  channel/profile không thay đổi. Scroll anchor vẫn xử lý thay đổi discovery.
- Lọc nhiệt độ không hữu hạn/ngoài khoảng trước khi merge nguồn. GPU WMI/SMM
  dưới 10 °C bị loại như kênh không đáng tin trên cấu hình đang nghiên cứu.
  NVIDIA hợp lệ vẫn ưu tiên. Thiếu GPU hợp lệ hiển thị “— / Không có dữ liệu”.
- Settings JSON sai cấu trúc và giá trị không thể chuyển đổi dùng default.

## Kiểm chứng và phạm vi

Test profile dùng subprocess/transport giả, sysfs tạm, không gọi setter thật.
Bao phủ thiếu mẫu, read-back lỗi, timeout, lỗi recovery, baseline Quiet,
Performance recovery qua PPD, sai cấu trúc settings, nguồn GPU lỗi và reader
chậm. Test GTK kiểm tra giữ widget qua refresh và không đọc hardware trên
luồng UI. Các kết quả hardware Phase 5H/5I vẫn là bằng chứng trước thay đổi;
Tại thời điểm triển khai đầu tiên, recovery mới chỉ được mô phỏng. Sau đó
người dùng cấp phép ghi thật và Phase 5J xác nhận cả profile writes lẫn recovery
trên app/helper đã cài. Xem [PHASE5J_INSTALLED_APP_HARDWARE_WRITES.md](PHASE5J_INSTALLED_APP_HARDWARE_WRITES.md).

Không mở Low Power/Balanced+/Custom, PWM, boost, Game Shift hoặc fan curve.
Không sửa driver/service hay thử lại SMM. Cài helper là bước hệ thống riêng,
cần permission trước khi chạy `sudo bash tools/install-helper.sh`.

## Triển khai đã hoàn tất

- Permission: người dùng cho phép cài toàn bộ bản đã chuẩn bị và yêu cầu backup.
- App/desktop entry/settings cũ:
  `~/.local/share/alienware-control-center-backups/0.1.0-2026-10-13.jzJt2x`.
- Helper/library/PolicyKit cũ (root-only): `/var/backups/awcc-helper.imnEIw`.
- `pkexec /usr/bin/bash tools/install-helper.sh` hoàn tất, có xác thực PolicyKit.
  Kiểm tra helper root-owned và fingerprint khớp source thành công.
- `bash tools/install-desktop.sh` đã nâng app user scope từ 0.1.0 lên 0.1.1.
  Source, user-installed modules và system-helper modules giống nhau.
- Smoke test qua interpreter đã cài: GTK dashboard lấy snapshot ở background,
  Quiet có transport/helper hợp lệ; bốn fan, manual vẫn khóa; GPU 36 °C NVML,
  CPU 42 °C AWCC, SODIMM 37 °C và Other 36 °C.
- PPD và platform profile trước/sau cùng `performance`; `awccd`/`i8kmon`
  vẫn inactive/disabled. Không gọi setter hoặc nạp/tháo module khi smoke test.

Backup chứa đúng đường cài cũ; khi cần rollback, đóng app rồi copy nội dung
`app` về đường user install, `desktop-entry` về desktop file và các file root
trong backup về đường library/helper/PolicyKit gốc bằng quyền quản trị.
Settings backup được giữ riêng, không tự ghi đè settings người dùng khi upgrade.

## Bổ sung sau thử hardware

PPD có thể công bố power-saver cho platform Quiet. Recovery Quiet đã sửa để
khôi phục qua helper, không ghi Low Power. Setter phục hồi PPD chờ 20 giây và
vẫn đọc đủ mẫu sau timeout; helper client cho phép 75 giây. Các sửa đổi đã
được cài và kiểm chứng trong Phase 5J; evidence lỗi ban đầu vẫn được giữ.
