# Alienware Control Center for Linux

Ứng dụng desktop GTK 4/libadwaita dành cho Alienware x17 R1 trên Ubuntu.

Bản đã cài **0.1.2+fanraw255.2** có thanh kéo toàn dải **raw 0–255** trên
mỗi kênh AWCC và fan helper ứng viên với heartbeat/watchdog/khôi phục. Đã
sao lưu app cũ trước cập nhật. Hardware-write gate vẫn khóa vì chưa hoàn tất
kiểm chứng end-to-end actuator mới; kênh 1 đã đạt qua helper mới, còn kênh
2/3/4 và mất kết nối/heartbeat. Chưa tạo activation record hoặc thử raw mới. Chỉ
64/100 có bằng chứng RPM máy thật. Một kênh khác raw 100 mỗi lần, active tối
đa 60 giây; raw không phải % RPM. Xem
[kết quả cài và backup Phase 5O](docs/PHASE5O_FULL_RAW_INSTALL.md) và
[kiến trúc phiên Phase 5N](docs/PHASE5N_BOUNDED_FAN_SESSION.md).

Đã cài thay đổi theo yêu cầu: fan session không còn chặn
CPU trên 50 °C lúc bắt đầu, nhưng vẫn dừng ở 70 °C hoặc tăng 10 °C. GPU và
cảm biến ngoài CPU vẫn cần ≤50 °C khi bắt đầu. Không thay điều kiện của
profile helper cũ. Kênh 1 qua helper mới đạt 3400 → 4100 → 3400 RPM ở raw
64 → 100 → 64, khôi phục Performance/raw 0 đã xác nhận độc lập; xem
[tiến độ Phase 5Q](docs/PHASE5Q_WARM_CPU_FAN_E2E.md).

Phiên bản hiện tại tập trung vào những khả năng đã được xác minh:

- tự động tìm `alienware_wmi` và `dell_smm` thay vì hard-code `hwmonN`;
- ưu tiên NVIDIA cho GPU, AWCC cho CPU/RPM và vẫn hoạt động khi thiếu `dell_smm`;
- hiển thị nhiệt độ, RPM, AWCC fan boost, fan target và trạng thái BIOS/manual;
- các cảm biến CPU/GPU/SODIMM/Other hiển thị bằng thẻ ở đầu dashboard,
  cùng Quạt đang chạy/Thermal profile; không còn danh sách kênh cảm biến riêng;
- thêm ba thẻ xung/tải CPU, xung/tải NVIDIA GPU và RAM đang dùng/tổng RAM;
  đọc nền, không sleep để lấy mẫu CPU; RAM dùng MemTotal − MemAvailable;
- hiển thị platform profile hiện tại và các profile firmware công bố;
- đánh giá capability trước khi mở các tính năng điều khiển;
- trạng thái nút tách rõ Đang dùng/Đang chọn, Bị khóa, Chưa sẵn sàng,
  Đang xử lý và Chỉ xem trước; lý do khóa hiển thị ngay trên card;
- mở cả sáu thermal profile trên x17 R1 / BIOS 1.27.0 sau Phase 5K;
- Low Power/Balanced/Performance qua `power-profiles-daemon`; Quiet/Balanced+
  và Custom thermal qua helper có read-back 2,75 giây;
- policy theo bằng chứng model/BIOS; Custom cần AC, bốn fan BIOS auto và nhiệt độ
  hợp lệ không quá 50 °C khi áp dụng, không phải custom fan curve;
- preset Auto/Balanced/Yên tĩnh/Performance; Yên tĩnh được xác minh qua helper
  và Performance qua `power-profiles-daemon`, không tự áp dụng lúc khởi động;
- fan modes/curve Giai đoạn 5B đã được gỡ khỏi desktop UI để thiết kế lại;
  không có lựa chọn curve hoặc lưu curve từ ứng dụng hiện tại;
- lưu preset ưu tiên và chu kỳ refresh tại user scope;
- không ghi PWM và không gọi raw SMM.

Snapshot được đọc trên luồng nền; refresh giữ nguyên các card/row khi topology
không đổi. Profile request thất bại sẽ thử phục hồi trạng thái ban đầu và xác
minh lại, báo riêng nếu phục hồi thất bại. Helper phải khớp mã nguồn app và
được root bảo vệ mới được sử dụng. Xem
[cập nhật độ tin cậy](docs/APP_RELIABILITY_2026-10-13.md).
Ghi Balanced/Quiet và các nhánh phục hồi đã được kiểm chứng trên app/helper
đã cài; PPD có thể gọi Quiet là power-saver trong khi platform vẫn là Quiet.
Xem [hardware validation Phase 5J](docs/PHASE5J_INSTALLED_APP_HARDWARE_WRITES.md).
Phase 5K tiếp tục kiểm chứng Low Power/Balanced+/Custom, mở các thermal profile
đó trong bản 0.1.2. Manual RPM/PWM/boost vẫn chưa có actuator production.
Chuỗi kiểm tra cuối qua client app đã đạt sau xác thực PolicyKit: Low Power,
Balanced+, Custom và chuyển về mode chuẩn đều có write/read-back thực tế;
Performance ban đầu được khôi phục. Log các lần timeout vẫn được giữ.
Xem [bằng chứng và phần còn thiếu Phase 5K](docs/PHASE5K_ALL_THERMAL_PROFILES.md).

## Chạy ứng dụng

```bash
./run.sh
```

Không chạy giao diện bằng `sudo`. Nếu privileged helper đã được cài, PolicyKit
sẽ yêu cầu xác thực khi cần fallback. Khi `power-profiles-daemon` đang active,
ứng dụng dùng API của daemon cho các mode daemon quản lý; Quiet/Balanced+/Custom
đi qua helper vì daemon không công bố các thermal profile này, với read-back
2,75 giây. Mode qua daemon chỉ
được báo thành công khi cả PPD và `alienware_wmi` platform profile cùng giữ giá
trị yêu cầu trong cửa sổ xác minh.

Kiểm tra phiên bản helper mà không gọi lệnh điều khiển:

```bash
python3 tools/check-helper.py
```

Nếu helper cũ, cần cập nhật riêng bằng `sudo bash tools/install-helper.sh` sau
khi được cấp phép và đóng app, rồi mở lại. Script cài file/helper/PolicyKit;
không gọi setter hay thay profile hiện tại.

## Cài ứng dụng desktop cho user hiện tại

Script dưới đây build wheel local rồi cài nó vào một virtual environment riêng
trong `$XDG_DATA_HOME/alienware-control-center`; desktop entry được đặt tại
`$XDG_DATA_HOME/applications` (mặc định là `~/.local/share/applications`). Nó
không cập nhật privileged helper, PolicyKit, driver, module, service hay fan
configuration:

```bash
./tools/install-desktop.sh
```

Máy cần sẵn Python 3 (kèm `venv`), GTK 4, libadwaita và PyGObject từ Ubuntu.
Script không tự cài dependency hệ thống, không dùng `--break-system-packages`
và không tải dependency từ mạng; nếu thiếu, nó dừng trước khi cài app.
Đường `Quiet` trong app vẫn cần helper đã cài riêng bằng PolicyKit; các nút
manual fan/PWM/boost không được mở bởi desktop installer.

## Kiểm thử

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Kiểm thử GTK dùng client giả lập, không gửi lệnh phần cứng; tự bỏ qua nếu không
có display. Để render riêng control cards cho kiểm tra hình ảnh:

```bash
PYTHONPATH=src python3 tests/render_controls.py
```

Script mở cửa sổ thử tạm, chỉ đọc telemetry và lưu PNG vào `research/results`;
không dùng cài đặt thật của người dùng.

Cài đặt người dùng được lưu tại
`$XDG_CONFIG_HOME/alienware-control-center/settings.json` hoặc
`~/.config/alienware-control-center/settings.json`. File chỉ chứa preset giao
diện và chu kỳ refresh; không chứa lệnh fan hay dữ liệu đặc quyền.

## Cấu trúc

```text
src/awcc_linux/
├── application.py   # GTK application và cửa sổ chính
├── backend.py       # snapshot/capability service
├── discovery.py     # khám phá sysfs động
├── fan_curves.py    # mode/curve engine, hysteresis và failsafe thuần logic
├── curve_runtime.py # supervisor/heartbeat/rollback qua actuator interface
├── models.py        # data model độc lập UI
├── presets.py       # preset an toàn và profile mapping
├── profile_policy.py # policy theo bằng chứng model/BIOS
├── settings.py      # cấu hình JSON ở user scope
└── ui.py            # dashboard và components

tools/
├── install-desktop.sh # cài launcher GTK ở user scope, không nâng quyền
└── install-helper.sh  # cài riêng helper/profile policy cần root
```

## Phạm vi an toàn

`pwmX` có tác động vật lý trên máy đã thử nghiệm, nhưng BIOS/EC lấy lại quyền và
`pwmX_enable=1` không duy trì. Vì vậy bản này cố ý không cung cấp slider PWM giả
manual-control. Helper giai đoạn 2 chỉ được phép ghi platform profile; nó không
có API để ghi PWM hay gọi SMM.

Code nghiên cứu Giai đoạn 5B vẫn được giữ ngoài UI (curve planner và runtime
supervisor) để làm nền cho thiết kế sau này, nhưng phần Fan modes, preview và
Custom curve đã được gỡ khỏi desktop app. Không còn lựa chọn hoặc lưu curve từ
giao diện hiện tại. Bản đang cài chưa có actuator quạt; workspace Phase 5N có
actuator AWCC ứng viên và slider giới hạn, vẫn bị deployment gate chặn.

Candidate driver dùng global command pair `0x34a3/0x35a3` cũng đã được thử có
watchdog và bị firmware BIOS 1.27.0 từ chối bằng `EINVAL`; driver gốc cùng BIOS
auto đã được khôi phục. Xem
[docs/PHASE3_HARDWARE_TEST_34A3.md](docs/PHASE3_HARDWARE_TEST_34A3.md).

Kernel hiện có đường AWCC-native qua `alienware_wmi/fan*_boost`; ứng dụng đã đọc
và hiển thị bốn kênh. Phép thử `255 → 224` cho read-back ổn định nhưng RPM không
đổi, nên ứng dụng chưa cho phép điều khiển. Xem
[docs/PHASE4_AWCC_BOOST_DISCOVERY.md](docs/PHASE4_AWCC_BOOST_DISCOVERY.md) và
[docs/PHASE4_HARDWARE_TEST_AWCC_BOOST.md](docs/PHASE4_HARDWARE_TEST_AWCC_BOOST.md).

Sau khi cô lập awccd và Custom giữ ổn định, Phase 5L ngày 15/10 đã quan sát
fan1 đổi RPM vật lý theo boost. Run2 chưa đạt stability do phase đầu chưa
settle; run3 được cấp phép riêng với 20 giây/mức đã đạt toàn A–B–A:
raw 64 → 100 → 64 cho median 3300 → 4100 → 3300 RPM và khôi phục
Performance/boost gốc thành công. Raw không phải phần trăm RPM. Chưa mở
production actuator/slider, chưa xác minh riêng ba kênh còn lại hoặc chạy lâu.
Xem
[docs/PHASE5L_CUSTOM_BOOST_VALIDATION.md](docs/PHASE5L_CUSTOM_BOOST_VALIDATION.md).

Phase 5M tiếp tục kiểm chứng riêng ba kênh còn lại: fan2/fan4 đạt A–B–A tại
raw 64/100; fan3 lần đầu bị watchdog do trễ khởi tạo nhưng retry1 có cấp phép
riêng đã đạt 1700 → 2700 → 1700 RPM. Tổng 4/4 kênh đạt ở hai mức đã thử;
chưa có actuator production hoặc slider ghi, chưa kiểm chứng toàn range/chạy
lâu và chưa xác định nguyên nhân trễ lần đầu. Các run đã khôi phục và kiểm tra
độc lập. Xem
[kết quả Phase 5M](docs/PHASE5M_REMAINING_FAN_CHANNELS.md).

Trên đúng Alienware x17 R1 / BIOS 1.27.0 đang thử nghiệm, logging có watchdog
xác nhận `quiet` được firmware nhận và giữ xuyên suốt 2,9 giây khi
`power-profiles-daemon` active. Việc trở lại `balanced` đến từ một daemon
root ngoài workspace, `awccd.service` (`python3 -m awccd.main`), đang ép profile
cấu hình mỗi tick và từng điều khiển fan boost Manual. Do đó ứng dụng phát hiện
socket daemon này, báo xung đột và chặn write profile mới; không được gán hiện
tượng cho firmware hoặc coi manual fan control là đã hoàn tất. Ở Phase 5E,
Low Power vẫn giữ khóa; Phase 5K sau đó xác minh và mở qua PPD. Quiet chỉ được
mở qua helper khi socket `awccd` vắng mặt. Sau khi
cô lập daemon, Performance đã giữ cả PPD và platform profile trong cửa sổ hai
giây qua đúng đường app dùng. Xem
[docs/PHASE5E_AWCCD_CONFLICT.md](docs/PHASE5E_AWCCD_CONFLICT.md) và
[docs/PHASE5I_PERFORMANCE_PPD_E2E.md](docs/PHASE5I_PERFORMANCE_PPD_E2E.md).

Đường **Yên tĩnh** trong desktop app đã được xác minh qua installed helper:
Quiet giữ cả ba read-back trong 2,75 giây, rồi helper khôi phục Balanced.
Performance cũng được mở qua PPD sau bốn read-back trong hai giây, rồi khôi
phục Balanced. Cả hai chỉ là hardware write platform profile, không phải manual
fan control. Xem [docs/PHASE5H_PROFILE_HELPER_E2E.md](docs/PHASE5H_PROFILE_HELPER_E2E.md)
và [docs/PHASE5I_PERFORMANCE_PPD_E2E.md](docs/PHASE5I_PERFORMANCE_PPD_E2E.md).

Phép thử G-Mode ngày 2026-10-09 với `force_gmode=1` cũng trả lỗi `EBADRQC`
ngay khi yêu cầu Performance. Driver thường, `balanced` và dịch vụ nguồn đã
được khôi phục; không thay cấu hình thường trực. Xem
[docs/PHASE5B_GMODE_RESULT.md](docs/PHASE5B_GMODE_RESULT.md). Giai đoạn 5B
vẫn là planner/UI, chưa phải điều khiển quạt thủ công hoạt động trên máy này.

Xem [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) và
[docs/ROADMAP.md](docs/ROADMAP.md) để biết thiết kế và các giai đoạn tiếp theo.
# AWCC-Ubuntu
