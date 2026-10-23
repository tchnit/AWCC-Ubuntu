# Ba thẻ tài nguyên desktop — 2026-10-13

Thêm Xung CPU / % CPU, Xung GPU / % GPU và RAM vào cùng dãy thẻ tổng quan.
Không thay đổi backend/profile helper root hoặc chức năng điều khiển phần cứng.

- CPU: trung bình `scaling_cur_freq` của các luồng có dữ liệu, đổi kHz thành
  GHz; fallback `cpu MHz` trong `/proc/cpuinfo`. Đây là snapshot xung hiện tại,
  không phải xung tối đa, không ghi governor hay ép xung.
- % CPU: chênh lệch counter aggregate `/proc/stat` giữa hai lần đọc; guest đã
  nằm trong user/nice nên không cộng hai lần. Idle gồm idle/iowait. Lần đầu,
  counter reset hoặc thiếu interval sẽ hiện “—”, không lấy mẫu bằng sleep.
- NVIDIA GPU 0: `nvidia-smi` query read-only `clocks.current.graphics` (MHz)
  và `utilization.gpu` (%), timeout hai giây. Lỗi/từng field N/A/NaN được hiển
  thị thiếu dữ liệu độc lập, không giả sử 0% hay làm mất CPU/RAM.
- RAM: `(MemTotal − MemAvailable) / MemTotal`, đổi kB kernel sang GiB; không
  tính cache khả dụng là RAM đang dùng. Thiếu MemAvailable không đoán bằng
  MemFree; RAM không phải VRAM.

ResourceReader và hardware reader chạy trong một SnapshotPoller single-flight,
trả cặp snapshot bất biến về GTK. Card giữ nguyên widget qua refresh. Module
resource telemetry chỉ nằm ở desktop user scope, không tham gia helper payload.

Kiểm chứng: 174 bài test đạt; GPU query thực tế đọc 210 MHz/0%, CPU mẫu thứ hai
đọc khoảng 2,17 GHz/21%, RAM used khoảng 9,97 GiB/15,28 GiB. Đây là số liệu tại
thời điểm smoke test, không phải giá trị mặc định. Render kiểm tra ở
`research/results/ui-reliability-2026-10-13/ui-sensors-status.png` dùng fixture
không ghi hardware.

App user-scope/wheel cập nhật, version giữ 0.1.2, helper không thay đổi.
Backup app/desktop/settings/wheel trước cập nhật:
`~/.local/share/alienware-control-center-backups/0.1.2-before-resource-cards-2026-10-13.UvAqPY`.
