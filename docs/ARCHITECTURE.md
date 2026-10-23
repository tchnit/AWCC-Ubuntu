# Kiến trúc

Workspace candidate: [Phase 5N](PHASE5N_BOUNDED_FAN_SESSION.md) đã triển khai
FanClient → JSONL/PolicyKit fan helper riêng → FanSession → NativeFanPort, kèm
guardian root process độc lập. Bản sửa 23/10 thêm shared lock, deadline và
kiểm tra ACK/timeout; chưa cài hoặc kiểm chứng phần cứng sau sửa. Production
deployment gate vẫn đóng. Đường PPD trực tiếp từ desktop chưa dùng root-owned
lock; các mô tả "future" bên dưới là lịch sử thiết kế.

## Nguyên tắc

Ứng dụng không đồng nhất “sysfs cho phép ghi” với “manual fan control ổn định”.
Mỗi tính năng đi qua capability gate dựa trên trạng thái đọc được và bằng chứng
thực nghiệm.

```text
GTK/libadwaita UI
       │ snapshots / intents
HardwareBackend (read-only, không cần root)
       │
Dynamic sysfs discovery
       ├── alienware_wmi (ưu tiên: nhiệt độ, RPM, fan boost)
       ├── dell_smm (legacy telemetry/fallback)
       └── platform-profile

Privileged profile helper (đã triển khai)
       ├── allow-list profile
       └── write + read-back verification

power-profiles-daemon client (đường ưu tiên)
       ├── power-saver ↔ low-power
       ├── balanced ↔ balanced
       ├── performance ↔ performance
       └── read-back PPD + alienware_wmi/degradation/capability gate

Future AWCC boost helper (chưa mở khóa)
       ├── exact DMI/provider validation
       ├── thermal safety policy
       ├── write + RPM/read-back verification
       └── automatic rollback / watchdog
```

## Vì sao backend hiện chỉ đọc

- `pwmX_enable=1` từng được ghi nhưng đọc lại thành `2`.
- ghi `pwmX` làm RPM thay đổi, song chỉ là override tạm thời.
- firmware/EC tiếp tục điều khiển fan curve.
- `fan*_max` không phản ánh RPM vật lý tối đa trên máy này.

Candidate global SMM `0x34a3/0x35a3` sau đó cũng bị BIOS 1.27.0 từ chối bằng
`EINVAL`. Do đó UI không có slider PWM legacy. Đây là capability đã bị bác bỏ
cho command pair đó, không phải một control bị giấu.

Kernel hiện công bố một đường điều khiển khác qua `alienware_wmi`:
`fan1_boost` đến `fan4_boost`, giá trị 0–255. Đây là giao diện AWCC-native và
không yêu cầu global SMM takeover. Backend đã đọc và hiển thị các kênh này,
nhưng ghi boost vẫn khóa cho tới khi có thử nghiệm read-back/RPM/rollback riêng.

Backend coi AWCC là nguồn telemetry độc lập; không yêu cầu `dell_smm` phải tồn
tại. Nếu cả hai provider có cùng nhãn nhiệt độ, giá trị AWCC được ưu tiên và
các sensor có nhãn riêng của `dell_smm` vẫn được giữ làm fallback mở rộng.

## Fan curve engine (giai đoạn 5B)

`fan_curves.py` là planner thuần logic, không có quyền ghi sysfs. Nó cung cấp
Auto/Silent/Balanced/Performance/Gaming/Custom, nội suy tuyến tính, hysteresis
khi nhiệt độ giảm, minimum-change suppression, stale-sensor failsafe và ngưỡng
nhiệt khẩn cấp. Mọi quyết định mang cờ `may_write`; cờ này luôn false khi
`stable_manual_fan_control` chưa được backend xác minh.

`curve_runtime.py` định nghĩa một `FanActuator` interface hẹp và supervisor chỉ
được arm khi caller cung cấp capability manual đã xác minh. Supervisor phát
duty qua curve engine, theo dõi heartbeat và gọi `restore_automatic()` khi
timeout hoặc disarm. Hiện không có implementation sysfs/SMM production nào được
đăng ký, nên lớp này chỉ được unit-test bằng fake actuator.

Desktop UI không còn hiển thị hoặc lưu Fan modes, preview hay Custom curve: các
control này được gỡ để thiết kế lại. `fan_curves.py` và `curve_runtime.py` chỉ
còn là mã nghiên cứu/test, không phải actuator hay tính năng desktop hiện tại.
Privileged actuator tương lai phải có watchdog độc lập, heartbeat, rollback về
BIOS auto và kiểm tra read-back/RPM trước khi capability gate được mở.

Profile policy tách khỏi UI và helper. Profile từng không persistent trên cặp
model/BIOS này vẫn bị khóa bảo thủ trước write; nguyên nhân chỉ được kết luận
sau khi attribution được kiểm chứng. Riêng Quiet đã giữ 10 mẫu/2,9 giây khi PPD
active và `awccd` cô lập, nên được helper xác minh read-back 2,75 giây.
Performance cũng giữ cả PPD và platform profile ở bốn read-back trong hai giây
qua đúng đường PPD của app, nên được mở trên đường đó. Nếu PPD không hoạt động,
UI vẫn chặn fallback helper cho Performance vì đường đó chưa được kiểm chứng.
Phase 5K đã xác minh Low Power qua PPD và Balanced+/Custom qua profile ABI.
Trên x17 R1 / BIOS 1.27.0, cả sáu thermal profile đã mở trong bản 0.1.2;
Custom trên các model/BIOS khác vẫn khóa vì choices synthetic không đủ bằng
chứng. Custom được xác minh chỉ là thermal profile, không mở manual fan.
Write/read-back Custom đạt cả diagnostic và production-client end-to-end;
Custom → Low Power và Balanced+ → Balanced cũng đã được kiểm chứng, chi tiết ở
[Phase 5K](PHASE5K_ALL_THERMAL_PROFILES.md).
Helper yêu cầu AC, bốn fan BIOS auto và nhiệt độ <=50 °C trước khi vào Custom;
rollback Custom không còn đủ điều kiện sẽ về Balanced, báo rõ không phục hồi
được baseline cũ. Khi phát hiện socket `awccd`, backend còn chặn mọi write profile mới
vì một root controller bên ngoài đang cạnh tranh.

PPD và thermal profile là hai trạng thái khác nhau: Balanced+/Custom có thể
giữ mode CPU Balanced hoặc power-saver trước đó. Client lưu đúng cặp baseline;
phục hồi CPU bằng mode PPD đã xác minh nếu cần, sau đó phục hồi thermal bằng
helper. Khi PPD bỏ qua một request cùng giá trị từ thermal profile khác, client
dùng helper Balanced hoặc đi qua Balanced PPD rồi áp lại mode chuẩn. Không
ghi Performance/Low Power trực tiếp qua helper để giải quyết alias.

## Preset và settings

Preset là lớp UI phía trên platform profile, không phải đường điều khiển fan
mới. `Auto` chỉ ghi nhớ lựa chọn “theo hệ thống” và không tạo hardware write;
`Balanced`/`Performance` gọi `power-profiles-daemon` khi khả dụng. `Yên tĩnh`
là hardware write đã xác minh: vì PPD không quản lý Quiet, nó gọi helper với
read-back 2,75 giây. Preset chỉ được lưu sau khi read-back thành công.
Performance degradation được hiển thị như cảnh báo API. Trên x17 R1 / BIOS
1.27.0, Performance chỉ được mở khi PPD công bố profile đó; fallback helper
vẫn bị chặn. Ứng dụng không tự áp preset khi khởi động.

Settings được lưu dạng JSON user scope với quyền `0600`. Chỉ có preset ưu tiên
và chu kỳ refresh 1/2/5 giây; không có PWM, boost, SMM command hoặc secret.

## Privilege boundary dự kiến

Phần UI luôn chạy dưới user thường. Khi `power-profiles-daemon` active, mode mà
daemon công bố đi qua daemon để đồng bộ CPU driver và platform driver. Quiet
không thuộc mô hình PPD nhưng đã được kiểm chứng với PPD active, nên đi qua
helper nhỏ với allow-list và read-back nhiều lần. Những profile ngoài hai đường
này không mở mặc định. AWCC fan boost sẽ cần helper riêng hoặc API mở rộng với
allow-list theo kênh, thermal ceiling, stale-sensor detection, timeout và
rollback trước khi UI có control.
