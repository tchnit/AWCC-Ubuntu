# Phase 5N — backend phiên AWCC boost và thanh kéo, workspace candidate

Cập nhật tiếp nối: [Phase 5O](PHASE5O_FULL_RAW_INSTALL.md) đã được người dùng
cho phép cài và bỏ raw limiter: desktop/helper ứng viên nhận raw 0–255, có
backup. Gate E2E vẫn đóng. Mô tả raw 64/100 và “chưa cài” bên dưới là trạng
thái lịch sử của ứng viên Phase 5N trước yêu cầu mới, không phải limiter hiện tại.

Ngày 2026-10-15. **Đã triển khai và kiểm thử offline/GTK trong workspace; chưa
cài fan helper mới, chưa ghi phần cứng qua actuator mới và chưa bật production.**
Ứng dụng/helper cũ đang cài vẫn 0.1.2. Không coi unit tests hoặc ảnh render là
end-to-end hardware validation. Người dùng cho phép bước xây dựng, chưa cấp
quyền cài helper hoặc thực hiện phiên thử của backend mới.

## Cơ sở và phạm vi đầu tiên

[Phase 5M](PHASE5M_REMAINING_FAN_CHANNELS.md) đã xác minh bốn kênh AWCC ở hai
mức **raw 64/100**, mỗi lần chỉ hạ một kênh và ba kênh khác raw 100. Không
ngoại suy thành toàn dải 0–255, % RPM/PWM, fixed RPM, nhiều quạt cùng raw thấp,
tải cao, hay khả năng chạy lâu dài. Độ trễ khởi tạo khoảng 28 giây từng xuất
hiện vẫn chưa rõ nguyên nhân.

Ứng viên mới do đó chỉ cho raw 64/100, tối đa một kênh ở 64. Không có fan
curve, tự chạy khi đăng nhập, lưu boost vào settings, PWM, raw SMM hoặc ghi EC.
SMM vẫn auto 2/2/2/2: không giả mạo `stable_manual_fan_control=true` để mở AWCC.

## Cấu trúc đã xây

- `fan_policy.py`: allow-list model/BIOS/kernel/driver, provider, source sensor,
  mức/kênh và điều kiện nhiệt. Snapshot ≤3 giây, mọi sensor finite 10–<70 °C,
  lúc bắt đầu ≤50 °C; abort khi từng sensor tăng ≥10 °C. CPU phải AWCC WMI,
  GPU phải NVIDIA NVML; AC online, không awccd/i8kmon/controller socket.
- `fan_session.py`: supervisor thuần logic với hardware port được inject.
  Chuẩn bị guardian trước mọi mutation. Baseline boost 0 và PPD Balanced hoặc
  Performance, platform cùng mode đó hoặc Custom. Low Power qua PPD và xác
  minh cả daemon/physical; sau đó Custom, khởi tạo bốn boost 100 và settle có
  guard bốn giây. Read-back đủ bốn boost sau mỗi thay đổi, không gửi lại giá
  trị đang dùng, tối thiểu hai giây giữa các lần đổi.
- `fan_hardware.py`: port root-only, dynamic discovery, chỉ các sysfs/profile
  nodes nội bộ, audit thời gian từng write. Snapshot đọc >3 giây bị từ chối
  dù backend đóng timestamp lúc hoàn tất. Singleton dùng cùng lock với các
  diagnostic cũ để tránh hai actuator chạy đồng thời.
- `fan_helper.py`: helper riêng, JSONL trên pipe được kế thừa từ pkexec, không
  mở socket/service. EUID/argument/deployment gates trước tạo hardware port.
  Sau xác thực cần handshake `start` mới arm; EOF/stop trước handshake không
  tạo hardware write. Giới hạn độ dài command/buffer, từ chối duplicate keys,
  raw/channel/sequence bất hợp lệ và replay; flood không bỏ qua thermal tick.
- `fan_integrity.py`: kiểm tra payload root-owned không writable/symlink, khớp
  mã nguồn. Gate deployment riêng ràng buộc model/BIOS/kernel/driver, protocol
  và SHA-256 của toàn bộ payload helper liên quan.
- `fan_client.py`: tiến trình GTK dưới user thường; xác thực/giao tiếp trong
  thread nền, heartbeat mỗi giây. Một lệnh đang chờ ACK, nhận read-back rồi
  mới cập nhật trạng thái thành công. Hủy/timeout/EOF thiếu final ACK không
  được diễn giải là đã khôi phục. Không SIGKILL tiến trình sở hữu recovery.
- `ui.py`: bốn thanh kéo hai nấc raw 64/100 trên hàng AWCC, nút Áp dụng riêng,
  start/stop phiên và thời gian còn lại. Kéo chỉ chọn, không ghi mỗi tick.
  Refresh giữ slider/selection và scroll; chỉ cho thao tác khi Custom, helper
  đã qua deployment gate và phiên đã ACK ready. Chặn đổi profile khi phiên
  đang khởi tạo/chạy/khôi phục; callbacks cũng kiểm tra gate, không chỉ nút.

## Lease và khôi phục

Giới hạn active **60 giây tính từ trước khi vào Custom**, không được gia hạn
bằng heartbeat. Heartbeat timeout 5 giây. Guardian root fork độc lập arm trước
lệnh PPD đầu tiên; giới hạn tổng startup 150 giây và hard deadline Custom
75 giây. Thời gian khởi tạo/đọc phần cứng ăn vào budget, không dời deadline
để lấy pass. Đây là bản session có thời hạn, không phải fan daemon thường trực.

Khi stop/EOF/đóng app/lỗi sensor/AC/profile/boost/heartbeat/lease: fence mọi
write mới; PPD Balanced bridge (fallback sysfs Balanced đã được kiểm chứng),
rồi PPD Performance nếu đó là coarse mode ban đầu. Chỉ sau verify physical +
daemon mới restore boost baseline 0; kiểm tra lại profile trước từng write 0
để không ghi 0 vào Custom. Bốn read-back profile/boost/auto và RPM cuối dương
mới xác nhận restore. Nếu chưa xác minh, không cancel guardian; guardian thử
recovery độc lập. Nếu còn Custom, chỉ giữ mức thử trên 100, không ghi raw 0.

Heartbeat không được yêu cầu trong lúc parent đang recovery (có thể >5 giây),
nhưng hard deadline và parent-death vẫn có hiệu lực. Guardian phần mềm không
thể bảo đảm cứu máy khi mất điện, kernel/ACPI call treo không thể ngắt hoặc
recovery route không đáp ứng. Không quảng cáo mức raw 100 là 100% tốc độ hay
failsafe maximum vật lý. Nếu restore không được xác minh, UI báo rõ cần kiểm
tra máy, không âm thầm báo thành công hoặc tự mở phiên mới.

## Hai cổng triển khai, đều chưa mở trên máy

1. `tools/install-fan-helper.sh` **chỉ là script đã chuẩn bị, chưa chạy**.
   Cần root và approval riêng. Refuse nếu profile helper/common payload không
   khớp; backup library/helper/policy/record trước khi cài. Chỉ cài năm module
   fan, `/usr/libexec/awcc-fan-helper` và PolicyKit action riêng; không đổi
   profile, fan, kernel, service hoặc tạo activation record.
2. Production `session` cần record root-owned
   `/usr/lib/alienware-control-center/fan-control-verified.json`, trạng thái
   `e2e-verified` đúng toàn payload/hardware. **Record chưa được tạo và không
   được tạo chỉ vì unit tests đạt.** `validation-session` là đường candidate
   có xác thực admin riêng, cùng policy/lease/guardian/actuator; không phải
   fallback tự động của UI, chỉ chạy sau approval hardware test cụ thể.

Launcher dùng Python isolated `-I` và root-owned library; PolicyKit chỉ cho
active desktop auth_admin (không auth_admin_keep), chặn inactive/any. Helper
đổi profile cũ không được mở rộng thêm opcode quạt và fingerprint vẫn khớp.

## Kiểm tra đã thực hiện

- **263 tests đạt**: tất cả suite cũ, policy/session giả lập, identity/freshness,
  sai source/NaN/nhiệt/AC/topology, budget/heartbeat, nguyên tắc một low channel,
  suppression/rate-limit, read-back mismatch, EOF/handshake, replay, malformed
  protocol, root/deployment gate, recover failure và child-watchdog triggers.
- Giao tiếp qua pipe với subprocess JSON giả lập (không import hardware,
  không pkexec), GTK tests kéo không ghi, Apply chỉ trong Custom, callback
  gate, profile interlock, close recovery request và refresh giữ widget/value.
- Kiểm tra installer `bash -n`, launcher và PolicyKit action. Build wheel local
  `dist/phase5n/alienware_control_center_linux-0.1.2-py3-none-any.whl` không cài
  vào venv hoặc hệ thống; candidate giữ base version 0.1.2, không nhầm với app
  đang cài chỉ vì cùng version. Source fan payload/deployment hash phân biệt.
  Wheel cuối đã đối chiếu byte-for-byte với tất cả module Python hiện tại;
  SHA-256 `fd63ebcb59aa48055b14128af0ac123c044101fd5c4745ffca6615dff4155fee`.
- Ảnh GTK fixture đã render và xem ở
  `research/results/ui-fan-session-2026-10-15/`; transport là Mock, ảnh active
  là **mô phỏng**, không phải phiên điều khiển máy thật.
- Bản đang cài được chép lưu trong `research/results/phase5n-installed-baseline/`
  (desktop package, profile-helper payload/launcher/policy). Đây là bản sao
  user-owned phục vụ đối chiếu; nếu rollback hệ thống phải install lại bằng
  quyền root/mode phù hợp, không dùng bản sao user-owned làm privileged helper.
- `tools/check-helper.py` vẫn xác nhận helper cũ khớp source; gate fan mới báo
  chưa cài và chỉ xem trước. Không gọi bất kỳ setter nào trong bước này.

## Bước cần phép tiếp theo

Cài **candidate fan helper** có backup (không tạo deployment record), rồi một
phiên end-to-end ngắn được cấp phép riêng với audit và kiểm tra độc lập sau
restore. Phải kiểm chứng ACK/read-back, tác động RPM, stop/EOF/mất heartbeat và
recovery của **đường mới**, không suy diễn từ diagnostic runner cũ. Không gộp
nhiều kiểu failure injection vào một phép ghi chưa được chấp thuận. Chỉ sau
bằng chứng end-to-end mới tạo record kích hoạt đúng payload và cập nhật app
user-scope; hai bước đó cũng chưa thực hiện.
