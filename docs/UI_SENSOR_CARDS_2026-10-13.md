# Cảm biến trên dãy thẻ tổng quan — 2026-10-13

Theo yêu cầu giao diện, bỏ danh sách Cảm biến/Kênh cảm biến riêng. Mọi sensor
backend cung cấp hiển thị thành MetricCard ở đầu dashboard, trước bảng quạt:
CPU, GPU, SODIMM, Other hoặc các sensor bổ sung khi discovery thay đổi.
Quạt đang chạy/Thermal profile vẫn nằm trong cùng FlowBox responsive.

- Giá trị và nguồn dữ liệu giữ nguyên backend, GPU vẫn ưu tiên NVIDIA NVML.
- CPU/GPU không có dữ liệu hiển thị “—”, không dùng giá trị giả.
- Card hiện có được cập nhật tại chỗ; chỉ thêm/bớt/đổi vị trí khi topology đổi.
- Không thay profile policy/helper, không hardware write hay sửa cấu hình hệ thống.
- 161 bài kiểm thử đạt, có regression cho đủ sensor, refresh giữ card, sensor
  xuất hiện/mất đi, GPU thiếu dữ liệu và vị trí trước profile controls.
- Render GTK đã xem: `research/results/ui-reliability-2026-10-13/ui-sensors-status.png`.

App user-scope được cập nhật, giữ version 0.1.2 vì chỉ sửa UI, không thay
helper payload. Backup app/desktop/settings/wheel cũ:
`~/.local/share/alienware-control-center-backups/0.1.2-before-sensor-cards-2026-10-13.hzrHAR`.
