# Phase 5L — phép thử được cấp phép, 2026-10-15

Tiếp nối: [Phase 5M](PHASE5M_REMAINING_FAN_CHANNELS.md) đã thử riêng fan2/3/4:
fan2 và fan4 đạt; fan3 lần đầu thiếu mẫu do watchdog, retry1 được cấp phép
riêng đã đạt 1700 → 2700 → 1700 RPM. Tổng 4/4 kênh đạt ở hai mức raw đã thử;
chưa mở production actuator, chưa xác định nguyên nhân trễ khởi tạo lần đầu.

## Kết quả mới nhất — run3, 20 giây mỗi mức, đã đạt trên fan1

Người dùng cấp phép riêng một lần thử kéo dài mỗi mức từ 12 lên 20 giây.
Giữ nguyên raw 64 → 100 → 64, ba kênh khác raw 100, gate bắt đầu ≤50 °C,
abort 70 °C/tăng ≥10 °C, watchdog Custom 75 giây và evaluator. Không hạ tiêu
chí để thay kết luận run2; đã sao lưu source/wrapper run2 dưới `research/results`.

| Phase | Fan1 boost raw | RPM median bốn mẫu cuối | Biên độ bốn mẫu cuối |
| --- | --- | --- | --- |
| A1 | 64 | 3300 | 0 RPM |
| B | 100 | 4100 | 0 RPM |
| A2 | 64 | 3300 | 0 RPM |

- Đủ 20 mẫu/mức, 60 mẫu tổng. Tăng/giảm 800 RPM, vượt threshold 330 RPM;
  stable_tails=true, repeated_low=true, responsive=true. Đáp ứng tachometer
  hai chiều và lặp lại mức thấp, không chỉ read-back raw.
- CPU 42–43 °C, GPU NVIDIA 38–40 °C. Physical Custom/PPD power-saver giữ
  suốt ba phase; boost ba kênh kia 100, SMM pwm_enable 2/2/2/2.
- Restore Performance qua PPD Balanced bridge, sau đó boost gốc 0/0/0/0;
  bốn mẫu restore, restore-complete ok=true, test-complete restored=true,
  process exit 0. Không có watchdog timeout; từ lúc arm Custom đến hoàn tất
  khoảng 72 giây, sát budget 75 giây, không coi đây là dư địa cho test dài hơn.
- Kiểm tra độc lập sau chạy: PPD/platform Performance, AC online, boost
  0/0/0/0, RPM AWCC 5000/5000/3000/3000, BIOS auto 2/2/2/2; CPU/GPU
  40/37 °C. awccd/i8kmon inactive, PPD active, helper root-owned khớp source.

Transcript: `research/results/hardware-test-custom-boost-2026-10-15-run3.jsonl`.
Root state tạm `/run/awcc-native-boost.x3y0w3h5`. Preflight ghi rõ timing,
watchdog và các mức raw; log cũ không bị ghi đè. Có regression test chính
dãy RPM run3 bên cạnh run2 (vẫn phải fail). Không đổi app/helper production.
Toàn bộ **193 tests đạt**, gồm GTK integration và các guard/recovery giả lập.
Đã mở lại desktop app sau khi kiểm tra độc lập; không còn probe/watchdog.

**Phạm vi kết luận:** native AWCC fan1 có đáp ứng ổn định trong cửa sổ thử
20 giây ở hai mức raw 64/100 trên đúng model/BIOS/driver này. Raw không phải
% RPM/PWM. Chưa xác minh riêng ba kênh khác, toàn dải 0–255, chạy lâu/tải cao
hoặc production actuator/lease/watchdog. Chưa mở slider, không cần SMM manual.

## Run2 — lịch sử sau khi người dùng giảm tải

**Đã quan sát đáp ứng RPM vật lý của AWCC fan1 trong Custom. Tuy nhiên, phép
kiểm ổn định toàn chuỗi A–B–A chưa đạt tiêu chí đặt trước. Không mở production
capability hoặc coi cả bốn kênh đã được xác minh.**

Sau khi người dùng báo đã tắt ứng dụng, kiểm tra read-only CPU/GPU 47/42 °C,
AC online, driver/helper không đổi, không writer cạnh tranh. Run2 chụp baseline
Performance 46/41 °C, dùng cùng mức 64 → 100 → 64, cùng cửa sổ 12 mẫu/mức,
cùng guard và watchdog. Không nới nhiệt độ hoặc tiêu chí sau khi đo.

| Phase | Fan1 boost raw | RPM median bốn mẫu cuối | Biên độ bốn mẫu cuối |
| --- | --- | --- | --- |
| A1 | 64 | 3700 | 400 RPM |
| B | 100 | 4100 | 0 RPM |
| A2 | 64 | 3300 | 0 RPM |

- B tăng từ 3400 lên 4100 RPM và giữ đến hết phase; A2 giảm từ 4000 về 3300
  RPM, giữ năm mẫu cuối. Không chỉ là raw read-back: tachometer đổi theo hai
  chiều thay đổi boost.
- Sau settle ban đầu, ba kênh còn lại giữ boost 100 và RPM khoảng
  4100/2700/2000 trong lúc fan1 tăng/giảm. CPU 45–46 °C, GPU 41 °C.
- Custom giữ xuyên suốt; PPD giữ power-saver. SMM pwm_enable vẫn 2/2/2/2,
  cho thấy không cần ép SMM manual để quan sát tác động của AWCC.
- Kết quả định lượng: increase=400, decrease=800, threshold=370 RPM;
  repeated_low=true. **stable_tails=false**, vì A1 tail [3900,3700,3700,3500]
  có span 400, vượt giới hạn 370. Do đó responsive=false theo tiêu chí đã
  đặt, process exit 1. Không sửa log hay hạ tiêu chí để biến thành pass.
- A1 còn giảm tốc từ baseline 5000 RPM khi hết 12 giây. Giả thuyết cho phép
  thử kế tiếp là quán tính/settle chưa đủ, không phải firmware không nhận boost.
  Không tự chạy lại với thời gian dài hơn khi mới được phép một run.
- Restore-complete ok=true, test-complete restored=true. Đối chiếu độc lập:
  PPD/platform Performance, boost 0/0/0/0, BIOS auto 2/2/2/2; RPM trở lại
  5000/5000/3000/3000; CPU/GPU 44/41 °C, AC online. Không còn probe/watchdog.

Evidence: `research/results/hardware-test-custom-boost-2026-10-15-run2.jsonl`.
Root state tạm `/run/awcc-native-boost.hyoztsek`. Wrapper chỉ đổi đích transcript
run1 → run2, vẫn exclusive-create. Mức raw, ceiling, timing và evaluator không đổi.
Có regression test chính dãy RPM của run2 để bảo toàn kết luận stability=false.
Toàn bộ suite sau bổ sung: **191 tests đạt**; helper root-owned vẫn khớp source.

Giới hạn: hai mức boost có tác động ở một kênh trong Custom, không chứng minh
RPM tuyệt đối/giới hạn vật lý, tất cả mức 0–255, ba kênh còn lại, long-run hoặc
failure recovery của một production actuator. Không ghi PWM, raw SMM, EC hay
đổi driver/service. Desktop app/helper production vẫn giữ nguyên.

## Run1 — lịch sử dừng ở bước làm mát

**Dừng ở bước làm mát, chưa vào Custom và chưa thử boost 64/100.** Không có
kết luận mới rằng điều khiển boost hoạt động hoặc không hoạt động.

Người dùng đã cấp phép quy trình trong
[nghiên cứu manual fan](MANUAL_FAN_RESEARCH_2026-10-15.md): stock driver,
Custom + AWCC fan1 A–B–A 64 → 100 → 64, ba kênh khác giữ 100, có guard và
watchdog, không SMM/PWM/driver/service mutations. 189 tests đạt trước khi chạy.

## Quan sát thực tế

- Baseline: PPD/platform Performance, boost bốn kênh 0, CPU/GPU 54/45 °C,
  nguồn AC, BIOS auto 2/2/2/2; stock srcversion không đổi.
- Đóng desktop app để tránh chuyển mode đồng thời. Xác thực PolicyKit thành
  công; root runner chụp baseline rồi arm watchdog độc lập trước write.
- PPD Low Power giữ cả daemon `power-saver` và physical `low-power` qua bốn mẫu.
- Trong cửa sổ làm mát 45 giây, CPU thấp nhất 51 °C rồi tăng lại, dải 51–56 °C;
  GPU 45–48 °C. Chưa đạt điều kiện bắt đầu Custom ≤50 °C.
- Runner báo `Cannot cool to <=50 C within budget` và dừng **trước** write
  `custom`/`custom-initial-boosts`/`stage-request`. Không ghi các giá trị thử.
- Khôi phục PPD Balanced → Performance để xử lý alias; khôi phục boost gốc
  0/0/0/0 **sau** khi Performance đã được xác minh. Đây là restore write,
  không phải mẫu thử boost.
- Bốn mẫu cuối khớp PPD/platform Performance, boost gốc và BIOS auto; cả bốn
  quạt đã quay lại. `restore-complete.ok=true`, `test-complete.restored=true`.
- Kiểm tra độc lập sau runner: Performance, CPU/GPU 55/48 °C, RPM khoảng
  5000/4900/3000/3000, boost 0/0/0/0, pwm_enable 2/2/2/2, AC online.
- Không còn process probe/watchdog; awccd/i8kmon vẫn inactive. Không cài driver,
  đổi service, gọi raw SMM, ghi PWM hay truy cập EC trực tiếp.

Transcript giữ nguyên:
`research/results/hardware-test-custom-boost-2026-10-15-run1.jsonl`.
Root state tạm: `/run/awcc-native-boost.9to5iad8`; không có service/autostart,
log đã được chép qua stdout sang transcript user-scope, không phụ thuộc /run
cho lưu trữ dài hạn.

**Lưu ý đọc log:** completion của run1 có `responsive=false` vì cờ chung mặc
định false khi abort. Không có sự kiện `evaluation` hay `stage-request`; do đó
không diễn giải là RPM không đáp ứng. Source đã được sửa phân biệt trường hợp
chưa vào Custom bằng `responsive=null`, `custom_requested=false`, outcome
`not-entered-custom`. Không sửa transcript lịch sử. Có regression test cho gate này.
Sau sửa phân loại kết quả: toàn bộ **190 tests đạt**. Desktop app được mở lại;
app/helper production không thay đổi và vẫn khớp fingerprint.

## Runner và giới hạn

- `research/custom_boost_validation.py`: root, exact confirmation, nguồn import
  helper root-owned, Linux/BIOS/srcversion/AC/sensor/controller gates; singleton
  lock; watchdog root fork trước write, dừng test writes sau fencing; deadline
  Custom publish atomic. Không dùng runner handshake cũ.
- `research/run_custom_boost_validation.py`: normal user, pkexec Python isolated,
  stream transcript bằng exclusive-create, không ghi đè run cũ/không tự retry.
- So sánh median bốn RPM mẫu cuối A/B/A, yêu cầu tăng/giảm có hướng và tái lập;
  không dùng fan_max hoặc một spike làm bằng chứng.
- Recovery chỉ cancel watchdog sau khi đọc lại profile/boost/BIOS-auto. Software
  watchdog không bảo đảm khi mất điện, kernel hoặc ACPI call treo không thể ngắt.

## Bước tiếp theo

Ba kênh khác đã được cấp phép và thử riêng ở Phase 5M; fan3 retry1 đã hoàn tất
với guard/watchdog không đổi. Tiếp theo thiết kế actuator tối thiểu quyền,
lease/heartbeat, watchdog độc lập và rollback, rồi tích hợp slider chỉ trong
Custom. Không suy diễn toàn range/long-run từ hai mức đã thử; không nâng guard
hoặc thử opcode khác, không cài helper mới trước khi được phép.
