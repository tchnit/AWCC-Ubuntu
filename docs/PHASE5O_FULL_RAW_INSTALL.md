# Phase 5O — cài bản full raw theo yêu cầu, 2026-10-15

## Kết quả

Người dùng cho phép cài bản mới, sao lưu bản cũ và bỏ giới hạn raw 64/100.
Đã cài desktop **0.1.2+fanraw255.1** và fan helper ứng viên. UI, client,
protocol, supervisor và native port đều nhận **mọi số nguyên raw 0–255**,
không âm thầm ép về 64/100. Ngoài ABI 0–255, bool/float/string vẫn bị từ chối.

**Không có hardware write trong lần cài.** Cổng production vẫn đóng do chưa
kiểm chứng end-to-end actuator mới. Không tạo activation record, không gọi
`session` hoặc `validation-session`, không chạy thử raw mới và không đổi
kernel/service/driver. Đã mở lại app sau cập nhật.

Hỗ trợ giá trị trong mã không phải bằng chứng an toàn/đáp ứng RPM của giá trị
đó: bằng chứng máy thật vẫn chỉ raw 64/100 ở bốn kênh như Phase 5M. Raw 255
không được quảng cáo là RPM tối đa và raw không phải phần trăm RPM.

## Sao lưu trước thay đổi

- App/venv, desktop entry và settings cũ:
  `~/.local/share/awcc-before-full-raw.xv3n88/`.
  Package trước cài là 0.1.2. Venv sao lưu có shebang trỏ vị trí cài gốc:
  phục hồi đúng đường dẫn khi rollback, không chạy launcher trong bản sao
  rồi giả định nó dùng interpreter/package cũ.
- Root helper library cũ và các file fan-helper/policy/record nếu có:
  `/var/backups/awcc-fan-helper.injk4M/`, root:root 0700. Installer dùng
  `set -euo pipefail`, backup hoàn tất trước install. Fan launcher/policy là
  file mới trên máy; khi rollback đầy đủ cần xử lý riêng các file vốn chưa
  tồn tại, không chỉ chép đè thư viện. Chưa thực hiện rollback hoặc xóa file.
- Source/tests/metadata/wheel ứng viên giới hạn 64/100 trước chỉnh:
  `research/results/phase5n-before-full-raw/`.
- Backup giai đoạn trước `research/results/phase5n-installed-baseline/` vẫn giữ.

## Những gì đã cài và xác nhận

- `tools/install-fan-helper.sh` chạy qua PolicyKit, exit 0; chỉ cài năm module
  fan root-owned, `/usr/libexec/awcc-fan-helper` root:root 0755 và policy riêng
  `/usr/share/polkit-1/actions/io.github.awcclinux.FanControl.policy` 0644.
- `pkaction` nhận action `io.github.awcclinux.ControlCenter.fan-session`,
  active=auth_admin, inactive/any=no, exec.path đúng fan helper.
- `tools/install-desktop.sh` build wheel local và thay package user-scope
  0.1.2 bằng 0.1.2+fanraw255.1, exit 0. Không cài dependency hệ thống.
- Tất cả module Python trong package đã cài đối chiếu byte-for-byte với
  source hiện tại. `fan_candidate_reason()` trả None; profile helper cũ vẫn
  khớp source và không bị sửa. Fan deployment gate trả “Chưa kiểm chứng
  end-to-end fan helper mới”; record `fan-control-verified.json` chưa tồn tại.
- Digest fan/common root payload:
  `2955223732c7795800680e61ae67babfc252fb468ddc2febd5bd4bab103bf0a5`.
- Baseline trước cài: PPD/platform Performance, boost 0/0/0/0, AWCC RPM
  5000/5000/3000/3000, CPU/GPU 44/39 °C. Sau cài: cùng profile, boost và RPM,
  SMM auto 2/2/2/2; CPU/GPU 45/40 °C. awccd/i8kmon vẫn inactive; không có
  tiến trình fan session/probe. Đây là kiểm tra read-only, không phải chạy actuator.

## Các giới hạn khác vẫn giữ

Không còn giới hạn giá trị chỉ 64/100. Vẫn chỉ cho **một kênh khác raw 100**
tại một thời điểm, ba kênh khác giữ 100; đây là giới hạn tổ hợp/kênh, không phải
giới hạn raw. Custom-only, AC/model/BIOS/kernel/driver, sensor freshness/source,
ngưỡng bắt đầu ≤50 °C, abort 70 °C hoặc mỗi sensor tăng ≥10 °C, heartbeat 5 giây,
active 60 giây và guardian 75 giây vẫn giữ. Quạt dừng sau settle sẽ abort và
khôi phục kể cả nếu người dùng đã chọn raw 0; không bỏ bảo vệ RPM/nhiệt.

## Kiểm thử và bước tiếp

**269 tests đạt** trước cài; bổ sung exhaustive kiểm tra 256 raw values tại
policy/client/protocol/supervisor/native port giả lập và GTK range 0–255 step 1.
Native-port tests chỉ ghi file tạm, không ghi sysfs. Từ chối -1/256/bool,
giữ one-channel/rate/restore guards. RPM regression máy thật lịch sử không
bị sửa để suy diễn toàn range. GTK fixture đã render/xem, không có hardware write.
Chạy lại sau cài vẫn **269 tests đạt**. Backup package 0.1.2/desktop/settings
đã kiểm tra tồn tại; wheel lưu tại `dist/phase5o/` đối chiếu byte-for-byte với
tất cả module nguồn. SHA-256 wheel lưu:
`79b6b6fee4e6a91ecb153e2dfa9dac6cf88df86d33e8913bc079ba8798dc21c4`.

Bước tiếp theo cần kế hoạch/approval riêng cho end-to-end session có guard
của **helper mới**, trước khi tạo record kích hoạt. Bỏ raw limiter trong code
không tự cho phép thực hiện một sweep 0–255, giữ fan raw 0 hoặc bỏ watchdog.
