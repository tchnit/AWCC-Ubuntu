# Roadmap

## Trạng thái mã nguồn 23/10/2026 — chưa deploy bản remediation

Workspace đã sửa shared lock giữa hai privileged helper, deadline ở native
writer, PPD recovery cùng client ACK/timeout và desktop entry. Suite trên máy
đạt 289 tests; bản chỉ gồm file dự kiến đưa lên Git đạt 289 tests, skip một
test DSDT vì ACPI dump cá nhân không được đưa vào repo. Đây là kiểm chứng
phần mềm với fixture, không phải kiểm chứng phần cứng mới.

Mã nguồn hiện khác helper đã cài; production fan-control gate vẫn đóng và
không có activation record. Đường PPD trực tiếp từ desktop chưa tham gia
root-owned lock. Tiếp theo cần giải quyết ranh giới này, triển khai payload
đồng bộ sau khi backup, rồi kiểm chứng fan2/3/4, EOF/heartbeat/guardian và
phục hồi thật trước bất kỳ quyết định mở gate nào.

## Trạng thái lịch sử 15/10/2026 — desktop 0.1.2+fanraw255.2, fan1 E2E đạt

Đã cập nhật đồng bộ app/helper: theo yêu cầu người dùng, fan session bỏ riêng
ngưỡng CPU ≤50 °C lúc bắt đầu; CPU vẫn dưới 70 °C, giữ giới hạn tăng 10 °C và
mọi watchdog. Cảm biến ngoài CPU vẫn ≤50 °C khi bắt đầu. Profile helper cũ
không đổi. [Phase 5Q](PHASE5Q_WARM_CPU_FAN_E2E.md): fan1 raw 64→100→64 đạt
3400→4100→3400 RPM, 15 mẫu/mức; ACK mutated/restored và bốn observer samples
đều đạt, exit 0. Còn xác minh kênh 2/3/4 qua actuator mới, EOF/heartbeat và
đường production trước activation; gate vẫn đóng. Không ngoại suy toàn range.

[Phase 5P lịch sử](PHASE5P_INSTALLED_FAN_E2E.md): runner E2E đã chuẩn bị, 272 tests
đạt. Lần fan1 đầu hết chờ PolicyKit trước starting/ready; chưa có hardware
test qua actuator mới. Baseline được đối chiếu độc lập, gate vẫn đóng; cần
xác thực trực tiếp trên máy trước khi tiếp tục, không coi auth timeout là
fan-response failure.

[Phase 5O](PHASE5O_FULL_RAW_INSTALL.md): đã backup/cài desktop mới và fan
helper ứng viên, bỏ raw limiter 64/100 trong toàn bộ đường điều khiển; nhận
raw 0–255, vẫn giữ one-channel/Custom/thermal/lease/watchdog. 269 tests đạt,
package/root payload đúng source và PolicyKit nhận action mới. Chưa ghi quạt
qua đường mới, chưa E2E/activation record; nút ghi vẫn khóa rõ lý do. Profile
helper cũ không đổi; các kết quả Phase 5K bên dưới vẫn giữ nguyên.

Sáu thermal profile trên x17 R1 / BIOS 1.27.0 đã mở sau kiểm chứng ghi/đọc lại
và phục hồi: Low Power/Balanced/Performance qua PPD, Quiet/Balanced+/Custom qua
helper. Custom cần AC, fan BIOS auto và nhiệt độ ≤50 °C khi áp dụng; nó không
là fan curve. Các mục bên dưới giữ lịch sử từng giai đoạn, không mô tả khóa
profile hiện tại. Manual fan/boost/PWM vẫn thiếu actuator đã kiểm chứng.
Custom đã đạt cả diagnostic và end-to-end qua client production; chuyển về
Low Power/Balanced và khôi phục Performance cũng đạt. Xem
[bằng chứng và việc còn lại Phase 5K](PHASE5K_ALL_THERMAL_PROFILES.md).

Rà soát 15/10: ưu tiên chứng minh **Custom + AWCC boost** sau khi awccd đã cô
lập; không yêu cầu SMM pwm_enable phải giữ 1 cho đường AWCC. Đã kiểm chứng thêm
nhánh fan setter bằng AML offline, sau đó thử vật lý có cấp phép tại Phase 5L.
Xem [nghiên cứu manual fan và phép thử đề xuất](MANUAL_FAN_RESEARCH_2026-10-15.md).
Phase 5L run2 quan sát đáp ứng RPM nhưng chưa đạt stability do A1 chưa settle.
Run3 được cấp phép riêng, tăng lên 20 giây/mức và giữ nguyên tiêu chí: fan1
đạt 3300 → 4100 → 3300 RPM ở raw 64 → 100 → 64, restore Performance/boost
gốc đạt. Chưa mở production capability, chưa kiểm chứng riêng ba kênh khác
hoặc vận hành lâu dài. Tiếp theo: xin phép thử từng kênh còn lại, rồi xây
actuator có lease/heartbeat/watchdog/rollback trước khi tích hợp slider. Xem
[kết quả và giới hạn Phase 5L](PHASE5L_CUSTOM_BOOST_VALIDATION.md).

[Phase 5M](PHASE5M_REMAINING_FAN_CHANNELS.md) sau đó đã thử từng kênh 2/3/4:
fan2 và fan4 đạt A–B–A; fan3 lần đầu bị watchdog do trễ khởi tạo khoảng 28
giây. Retry1 được cấp phép riêng đã đạt fan3 1700 → 2700 → 1700 RPM với
evaluator/guard/watchdog giữ nguyên. Restore và kiểm tra độc lập các run đạt.
Tổng 4/4 kênh đã xác minh tại raw 64/100; trễ lần đầu chưa rõ nguyên nhân.
Tiếp theo xây actuator có lease/watchdog/rollback trước khi tích hợp slider.
App/helper vẫn 0.1.2, chưa mở production manual capability/toàn range.

[Phase 5N](PHASE5N_BOUNDED_FAN_SESSION.md): workspace candidate đã có backend
AWCC lease/heartbeat, root process guardian, narrow JSONL helper, deployment
fingerprint gate và bốn slider Custom-only với nút Áp dụng. Chỉ raw 64/100,
tối đa một kênh ở 64; không ngoại suy full range hoặc chạy lâu. 263 tests đạt,
GTK render đã xem; chưa cài fan helper mới, chưa E2E actuator mới, chưa có
activation record hoặc hardware write qua đường mới. Helper cũ không đổi.

## Giai đoạn 1 — quan sát an toàn (đã triển khai)

- GTK 4/libadwaita desktop UI.
- dynamic sysfs discovery.
- live temperatures, RPM, target RPM, `pwm_enable` và platform profile.
- capability report; manual control luôn khóa khi chưa có bằng chứng.
- unit tests với sysfs giả lập.

## Giai đoạn 2 — profile control (đã triển khai và kiểm tra)

- privileged helper với API allow-list: đã triển khai.
- PolicyKit rule tối thiểu: đã cài và được PolicyKit nhận diện.
- ghi profile, read-back sau nhiều khoảng thời gian, báo profile không giữ ổn
  định: đã có controller và unit tests. Nguồn của mỗi thay đổi phải được xác
  minh, không mặc định gọi là firmware rollback.
- tại Phase 2, `custom` bị loại vì synthetic và chưa có validation độc lập;
  Phase 5K đã xác minh, chỉ mở thermal Custom cho đúng model/BIOS này.

Kết quả máy thật lịch sử: `quiet`, `low-power` và đường daemon của
`performance` từng trở lại `balanced`; `balanced` giữ ổn định. Phase 5E phát
hiện một writer root chưa từng được log trong các run cũ. Sau khi cô lập nó,
Phase 5F/5G xác nhận Quiet giữ 10 mẫu cả khi PPD dừng lẫn khi PPD active, nên
Quiet được mở qua helper. Phase 5I tiếp tục xác minh Performance qua chính
đường PPD của app: cả PPD và platform profile giữ `performance` qua bốn mẫu
trong hai giây rồi khôi phục Balanced. Tại Phase 5I, `low-power` vẫn chưa được
mở khóa; Phase 5K sau đó xác minh và mở qua PPD. Xem [PHASE2_VALIDATION.md](PHASE2_VALIDATION.md),
[PHASE5E_AWCCD_CONFLICT.md](PHASE5E_AWCCD_CONFLICT.md) và
[PHASE5G_QUIET_WITH_PPD.md](PHASE5G_QUIET_WITH_PPD.md). Phase 5H xác nhận
end-to-end installed helper giữ Quiet qua ba read-back rồi khôi phục Balanced;
Phase 5I xác nhận PPD Performance. Xem
[PHASE5H_PROFILE_HELPER_E2E.md](PHASE5H_PROFILE_HELPER_E2E.md) và
[PHASE5I_PERFORMANCE_PPD_E2E.md](PHASE5I_PERFORMANCE_PPD_E2E.md).

## Giai đoạn 3 — nghiên cứu driver (`34a3/35a3` đã bị bác bỏ)

- đối chiếu đúng source `dell-smm-hwmon` của kernel Ubuntu đang chạy.
- xác định DMI match và `i8k_whitelist_fan_control`/cơ chế tương đương.
- lần theo command enable/disable BIOS fan control và model-specific config.
- tạo patch nhỏ, build riêng, không tự load/thay module.

Đã hoàn tất source comparison, evidence review, RFC patch, offline build và một
hardware test có watchdog. Firmware BIOS 1.27.0 trả `EINVAL` cho cả `0x34a3`
và `0x35a3`; phép thử dừng trước khi giảm tốc fan. Driver gốc và BIOS auto đã
được khôi phục, xác minh. Xem [PHASE3_DRIVER_RESEARCH.md](PHASE3_DRIVER_RESEARCH.md)
và [PHASE3_HARDWARE_TEST_34A3.md](PHASE3_HARDWARE_TEST_34A3.md).

Nhánh nghiên cứu tiếp theo là đánh giá lại bằng chứng cho `0x30a3/0x31a3` hoặc
cơ chế khác. Không thử thêm command pair nếu chưa có giả thuyết mới, kế hoạch
riêng và sự cho phép rõ ràng.

Kết quả điều tra ban đầu được ghi tại [DRIVER_RESEARCH.md](DRIVER_RESEARCH.md).

## Giai đoạn 4 — AWCC fan boost (read-only discovery hoàn tất)

Kernel `alienware_wmi` hiện expose bốn AWCC-native `fan*_boost` channel cùng
RPM/max và CPU/GPU mapping. Backend/UI đã hỗ trợ đọc riêng, không trộn channel
với `dell_smm`. Xem
[PHASE4_AWCC_BOOST_DISCOVERY.md](PHASE4_AWCC_BOOST_DISCOVERY.md).

Write path vẫn khóa. Nhánh SMM `30a3/31a3` tạm hoãn vì không có evidence trực
tiếp cho x17 R1 và có giá trị thấp hơn giao diện AWCC chính thức.

Phép thử một kênh đã hoàn tất: write/read-back `255 → 224` hoạt động, nhưng RPM
không đổi trong tám giây; rollback thành công. Manual UI vẫn khóa. Các test
`custom` lịch sử thấy profile trở lại `balanced` khi PPD inactive, nhưng không
ghi trạng thái `awccd.service` vừa được Phase 5E xác định là writer profile/fan
boost cạnh tranh. Vì vậy không dùng các test đó để quy rollback cho firmware hay
loại trừ userspace; không lặp lại write boost trước khi daemon được cô lập an
toàn. Xem
[PHASE4_HARDWARE_TEST_AWCC_BOOST.md](PHASE4_HARDWARE_TEST_AWCC_BOOST.md).

Bước nghiên cứu kế tiếp không phải lặp lại sysfs write với giá trị thấp hơn.
Source upstream cho thấy driver tự quảng bá `custom` cho mọi model sau bước khám
phá profile, nên choice này không phải bằng chứng hỗ trợ từ firmware. Cô lập
`awccd` là điều kiện trước khi đánh giá profile/custom hoặc manual takeover.
Manual fan control tiếp tục khóa cho đến khi có bằng chứng RPM vật lý và
takeover ổn định.

Draft upstream được giữ lại nhưng không submit cho tới khi có evidence đã cô lập
daemon: [UPSTREAM_ALIENWARE_WMI_CUSTOM_REPORT.md](UPSTREAM_ALIENWARE_WMI_CUSTOM_REPORT.md).
Backend cũng đã được tách khỏi phụ thuộc `dell_smm`: AWCC-only vẫn là telemetry
hợp lệ, còn policy theo model/BIOS ngăn UI/helper lặp lại profile đã rollback.

## Giai đoạn 5A — preset an toàn (đã triển khai)

- Auto, Balanced và Performance.
- Auto không ghi phần cứng; hai preset profile dùng `power-profiles-daemon` và
  read-back, helper chỉ là fallback.
- không tự áp preset khi khởi động.
- lưu preset ưu tiên và chu kỳ refresh 1/2/5 giây ở user scope.
- UI card hoàn chỉnh, tooltip, daemon degradation và capability/policy gate.

Lỗi ghi sysfs song song với `power-profiles-daemon` đã được sửa. Read-back của
client nay quan sát đủ hai giây để phát hiện thay đổi trễ. Quiet không được PPD
quản lý nhưng đã giữ 2,9 giây khi PPD active và `awccd` cô lập, nên dùng helper
có read-back 2,75 giây. Phase 5I đã xác minh `performance` qua PPD active,
`awccd` vắng mặt và bốn read-back trong hai giây, vì thế mode này được mở qua
PPD; fallback helper vẫn bị chặn trên đúng model/BIOS này. `low-power` vẫn giữ
khóa bảo thủ. Về API, `high-operating-temperature` chỉ là degradation warning.

## Giai đoạn 5B — modes và fan curve (tạm gỡ khỏi desktop UI)

- Silent, Balanced, Performance, Gaming và Auto.
- custom curves theo từng vùng nhiệt với hysteresis.
- lưu preset ở user scope; không ghi liên tục nếu không cần thiết.

Code nghiên cứu còn giữ trong workspace:

- curve planner thuần logic cho Auto/Silent/Balanced/Performance/Gaming/Custom;
- nội suy, hysteresis 3 °C và minimum-change suppression;
- stale-sensor và ngưỡng nhiệt khẩn cấp đều yêu cầu failsafe 100%;
- runtime supervisor có arm gate, heartbeat timeout và automatic rollback API;
- capability gate bảo đảm preview không thể tạo hardware write;
- unit tests cho interpolation, hysteresis, failsafe và gate.

Theo yêu cầu thiết kế lại, phần Fan modes, Curve preview và Custom curve đã
được gỡ hoàn toàn khỏi desktop UI. Cấu hình fan-mode/curve cũ không được hiển
thị, ghi hay áp dụng bởi UI hiện tại; các khóa legacy bị bỏ qua khi đọc settings.
Planner/runtime giữ lại như mã nghiên cứu nội bộ, không phải một tính năng
desktop đang mở.

Chưa triển khai actuator ghi quạt. Silent/Gaming/custom curves chỉ được phép áp
dụng khi backend điều khiển quạt ổn định được xác minh. Actuator tương lai phải
có watchdog độc lập, sensor freshness, thermal ceiling, heartbeat và rollback
BIOS-auto; không được mở chỉ dựa trên `pwm_enable=1` hoặc boost read-back.

Phép thử `force_gmode=1` được người dùng cho phép đã chạy ngày 2026-10-09:
Performance trả `EBADRQC` ngay khi ghi, chưa vào cửa sổ quan sát ba giây.
Balanced cũng lỗi khi driver còn bật force_gmode; driver thường, Balanced và
daemon đã được khôi phục, watchdog và kiểm tra độc lập xác nhận. Giả thuyết
chỉ bật force_gmode là đủ bị bác bỏ cho cấu hình này; không bật thường trực và
không lặp lại test. Xem [PHASE5B_GMODE_RESULT.md](PHASE5B_GMODE_RESULT.md).

Trước khi gỡ UI 5B, giao diện đã tách rõ trạng thái Đang dùng/Đang chọn khỏi Bị
khóa và Chỉ xem trước.
Lý do khóa hiển thị trên card, không chỉ trong tooltip; bấm lại lựa chọn hiện tại
không gửi lệnh phần cứng. Cả 62 tests (gồm chín GTK integration tests) đạt;
render kiểm tra ba nhóm control đã được xem. Đây là cải thiện giao diện, không
mở khóa manual control. Xem [UI_CONTROL_STATUS.md](UI_CONTROL_STATUS.md).

Điều tra AWCC đã đối chiếu source Ubuntu đúng package, đọc cache IDs, và phân
tích DSDT offline: method WMAX không có case `0x25`, default trả `0xFFFFFFFF`.
Binary stock gọi query Game Shift trước toggle/activate, nên đã khoanh vùng
`EBADRQC` ở query. Một phép thử logging có watchdog sau đó xác nhận Quiet
`0xA3` được firmware nhận (`raw=0`) và giữ khoảng 1,3 giây, nhưng có request
Balanced `0xA0` thứ hai trong lúc PPD inactive, rồi block khoảng 18 giây.
Attribution v3 đã xác nhận request `A0` đến từ root daemon `awccd.service`
(`python3 -m awccd.main`, PID 2350/TGID 2337), trong khi PPD đã dừng; không
phải firmware/EC tự gọi WMAX. Daemon này ép profile cấu hình (hiện Balanced) ở
mỗi tick và cũng đang điều khiển fan boost thủ công, nên profile stability chưa
thể đánh giá độc lập. Manual takeover và profile ổn định vẫn chưa giải quyết.
Xem
[PHASE5B_AWCC_REJECTION_ANALYSIS.md](PHASE5B_AWCC_REJECTION_ANALYSIS.md),
[PHASE5C_ORDINARY_PROFILE_DIAGNOSTIC.md](PHASE5C_ORDINARY_PROFILE_DIAGNOSTIC.md)
và [PHASE5E_AWCCD_CONFLICT.md](PHASE5E_AWCCD_CONFLICT.md).
