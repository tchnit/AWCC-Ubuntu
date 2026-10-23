# Phase 5M — kiểm chứng AWCC fan 2/3/4, 2026-10-15

Tiếp nối triển khai: [Phase 5N](PHASE5N_BOUNDED_FAN_SESSION.md) có backend
lease/guardian và UI slider trong workspace; chưa cài helper hoặc E2E đường mới.

## Kết luận

Fan2 và fan4 đạt đáp ứng tachometer A–B–A với tiêu chí không đổi. Fan3 lần đầu
bị watchdog dừng trước khi đủ A2; **retry1 được cấp phép riêng đã đạt toàn chuỗi**.
Kết hợp fan1 ở [Phase 5L](PHASE5L_CUSTOM_BOOST_VALIDATION.md), hiện **4/4 kênh
đạt tại raw 64/100 trong cửa sổ thử 20 giây/mức**. Không phải hoàn tất manual
actuator, toàn range hoặc vận hành lâu dài. Log lần chưa hoàn tất giữ nguyên.

| Kênh AWCC | Mẫu A1/B/A2 | Median cuối A1/B/A2 (RPM) | Kết luận |
| --- | --- | --- | --- |
| 1 — CPU1, Phase 5L run3 | 20/20/20 | 3300 / 4100 / 3300 | Đạt trước đó, không thử lại |
| 2 — GPU1 | 20/20/20 | 3200 / 4100 / 3200 | Đạt, tăng/giảm 900 RPM |
| 3 — CPU2, lần đầu | 20/20/2 | 1700 / 2700 / chưa đủ mẫu | Chưa kết luận, watchdog |
| 3 — CPU2, retry1 | 20/20/20 | 1700 / 2700 / 1700 | Đạt, tăng/giảm 1000 RPM |
| 4 — GPU2 | 20/20/20 | 1200 / 2000 / 1200 | Đạt, tăng/giảm 800 RPM |

Đây là thứ tự AWCC-native, không phải thứ tự `dell_smm`. Raw 64/100 không có
nghĩa 64%/100% RPM, không dùng `fan*_max` làm mẫu số hoặc physical maximum.

## Kết quả mới nhất — fan3 retry1 có timing, đã đạt

Người dùng cấp phép riêng một lần thử lại fan3 có log thời gian từng write,
vẫn ba mức 64 → 100 → 64, 20 giây/mức, ba quạt khác raw 100; mọi điều kiện
và evaluator/watchdog giữ nguyên. Không tự lặp kênh khác hoặc lần thử tiếp.

- Baseline mới: Performance, boost 0, CPU/GPU 43/40 °C, AC online, không
  controller cạnh tranh; model/BIOS/driver/helper đúng bản đã xác minh.
- Đủ 60 mẫu; median tail 1700 → 2700 → 1700 RPM, span cuối cả ba phase 0.
  Increase/decrease 1000 RPM, threshold 300; stable_tails, repeated_low và
  responsive đều true; process exit 0. CPU 43–44 °C, GPU NVIDIA 39–41 °C.
- Custom/PPD power-saver giữ suốt các mẫu, ba boost khác 100 và SMM vẫn auto
  2/2/2/2. Mẫu đầu A1 fan3 RPM 0 trong cửa sổ settle cho phép; từ mẫu 2 đã
  quay, không có fan dừng từ mẫu 4 trở đi theo guard không đổi.
- Profile Custom write 0,072736 giây; boost writes thử khoảng
  0,000738–0,001065 giây. **Không tái hiện trễ 28 giây**; không được coi
  nguyên nhân trễ lần đầu đã xác định hoặc đã sửa. Production actuator phải
  xử lý khả năng call kéo dài và không giữ UI thread khi gọi phần cứng.
- Restore parent qua Balanced → Performance, boost gốc 0/0/0/0; bốn mẫu
  read-back, restore-complete ok=true, restored=true. Không watchdog-fired;
  từ arm Custom đến hoàn tất khoảng 72,3 giây, không nới deadline 75 giây.
- Đối chiếu độc lập sau chạy: PPD/platform Performance, boost 0/0/0/0,
  AWCC RPM 5100/5100/3000/3000 (đang về baseline), auto 2/2/2/2, AC online;
  CPU/GPU 44/40 °C. awccd/i8kmon inactive, helper khớp source. Không còn
  root probe/watchdog; desktop app được mở lại sau kiểm tra.

Log mới: `research/results/hardware-test-custom-boost-2026-10-15-fan3-retry1.jsonl`;
root state `/run/awcc-native-boost.p4zd9jmn`. Wrapper mới
`research/run_fan3_timed_retry.py` chỉ nhận confirmation riêng, pin fan3 và
exclusive-create đúng log retry1. Không đổi runner/evaluator/timing để lấy pass,
không ghi đè log abort. Regression dùng dãy RPM thật của retry bên cạnh dãy
incomplete lần đầu, kèm guard wrapper không root/không chọn kênh khác.

## Phạm vi đã được cấp phép và thực hiện

Người dùng cho phép thử lần lượt ba kênh còn lại, mỗi kênh một lần, cùng
raw 64 → 100 → 64, 20 giây/mức, ba kênh khác giữ raw 100. Khôi phục và kiểm
tra độc lập giữa các lần, không gộp thành một phiên Custom kéo dài. App được
đóng tạm để tránh write profile đồng thời. PolicyKit xác thực root runner.

Các điều kiện không thay đổi:

- Alienware x17 R1 / BIOS 1.27.0 / kernel 7.0.0-38-generic; stock alienware_wmi
  srcversion `28A4134FBF8432C66D7C668`; helper root-owned khớp mã nguồn.
- AC online, awccd/i8kmon inactive, không có socket controller cạnh tranh.
- PPD Low Power làm mát, mọi sensor hợp lệ ≤50 °C trước khi vào Custom;
  CPU từ AWCC WMI, GPU từ NVIDIA NVML. PPD không bị dừng.
- Trong phép thử: Custom giữ, PPD power-saver, đọc lại đủ boost bốn kênh;
  abort nếu mất AC/sensor, fan dừng sau settle, profile/boost đổi, nhiệt đạt
  70 °C hoặc tăng ≥10 °C so với baseline nóng nhất. Watchdog độc lập 75 giây
  cho Custom, giới hạn tổng 150 giây; không nới giới hạn.
- Median bốn mẫu cuối; span ≤max(300 RPM, 10% median); tăng/giảm vượt
  max(300 RPM, 10% mức thấp); mức thấp lặp lại trong dung sai đặt trước.
  Không spam hardware write mỗi lần lấy mẫu.

## Kết quả và khôi phục

Fan2: tail span A1/B/A2 đều 0 RPM; delta hai chiều 900, threshold 320 RPM,
stable_tails/repeated_low/responsive đều true. CPU 42–43 °C, GPU 37–38 °C.
Process exit 0; restore parent thành công. Đối chiếu độc lập: Performance,
boost 0/0/0/0, SMM auto 2/2/2/2, bốn RPM dương; CPU/GPU 42/39 °C.

Fan3: khoảng từ cooling sample cuối đến custom-initial-boosts **28,208 giây**,
so với khoảng 0,095 giây ở fan2. Log lúc đó chưa tách từng write nên chưa thể
quy trễ cho riêng profile setter, boost setter hay một nguyên nhân kernel cụ
thể. A1 giữ 1700 RPM, B giữ 2700 RPM; A2 chỉ [2700,2600]. Watchdog fired,
fence test writes và gửi SIGTERM; runner báo responsive=null, outcome=aborted,
exit 1. Không có evaluation và không được biến mẫu thiếu thành pass/negative
fan-response. CPU 44–45 °C, GPU 39 °C. Watchdog khôi phục Balanced → Performance,
boost gốc, bốn read-back; restore-complete ok=true, restored=true. Đối chiếu
độc lập: Performance, boost 0/0/0/0, RPM 5000/5000/3000/3000, auto 2/2/2/2,
CPU/GPU 43/40 °C. Kernel journal mười phút gần đó không có entry trả về;
điều này không xác định hoặc loại trừ nguyên nhân độ trễ.

Fan4: chỉ bổ sung log native-write-start/finished và elapsed trước khi chạy;
không đổi write, mức boost, timing, evaluator hay watchdog. Profile Custom
write mất 0,063 giây; boost writes khoảng 0,0003–0,0012 giây; không tái hiện
trễ 28 giây. Tail span A1/B/A2 đều 0; delta 800, threshold 300 RPM, tất cả
gate định lượng đạt. CPU 44–45 °C, GPU 39 °C; exit 0, restore parent đạt.
Đối chiếu độc lập cuối: PPD/platform Performance, boost 0/0/0/0, RPM
5000/5000/3000/3000, auto 2/2/2/2, AC online, CPU/GPU 43/40 °C; helper vẫn
khớp source. Không còn root probe/watchdog; desktop app được mở lại.

Trong tất cả các mẫu thử, boost ba kênh không phải mục tiêu giữ 100; Custom,
PPD và SMM auto giữ đúng trạng thái. Restore thông qua PPD Balanced bridge
rồi Performance; chỉ sau khi xác minh profile mới restore boost 0. Chuyển
profile có transient RPM 0/ramp-up; kiểm tra độc lập sau đó xác nhận cả bốn
quạt đã quay lại. Không coi RPM transient bằng 0 là mất khôi phục profile.

## Bằng chứng và mã

- `research/results/hardware-test-custom-boost-2026-10-15-fan2.jsonl`
  — root state `/run/awcc-native-boost.nl9z9lj2`.
- `research/results/hardware-test-custom-boost-2026-10-15-fan3.jsonl`
  — root state `/run/awcc-native-boost.jvf_5_s_`.
- `research/results/hardware-test-custom-boost-2026-10-15-fan4.jsonl`
  — root state `/run/awcc-native-boost.zui1stei`.

Runner chỉ nhận confirmation mới và đúng một `--channel 2|3|4`; không tự loop
hoặc retry. Transcript exclusive-create riêng từng kênh; không ghi đè run cũ.
Source/wrapper run3 fan1 được sao lưu `custom-boost-run3-*.py.txt` trước chỉnh.
Unit tests kiểm tra mapping write và đọc RPM theo kênh, giữ ba boost khác,
guard/rollback, thiếu phase, timing không thêm write và bảo toàn log cũ.
Regression dùng dãy RPM thật giữ nguyên run2 fail, run3 pass, fan2/fan4 pass,
fan3 thiếu mẫu. Các bài test là offline/mock, không phải thêm hardware run.
Trước retry: **200 tests đạt**. Sau wrapper riêng và regression retry: **203
tests đạt**, gồm GTK integration và kiểm thử guard/recovery; không thêm hardware run.

App/helper production vẫn 0.1.2 và manual capability false. Không cài package,
đổi driver/kernel/service, raw SMM, PWM hoặc ghi EC trực tiếp.

## Việc còn lại

1. Bốn kênh đã đạt tại hai mức; không cần lặp các phép thử đó nếu không có
   giả thuyết mới. Độ trễ 28 giây lần đầu chưa rõ nguyên nhân; chỉ bắt thêm
   timing khi được phép một phép ghi khác, không suy đoán rằng đã hết lỗi.
2. Chưa chứng minh toàn range, tải cao, chạy lâu,
   kiểm soát RPM tuyệt đối hoặc an toàn khi ACPI call treo/kernel mất đáp ứng.
3. Trước UI write cần actuator có quyền tối thiểu, Custom-only policy, lease,
   heartbeat, sensor freshness, watchdog độc lập, xử lý profile changes và
   khôi phục đã kiểm thử. Không mở slider/capability chỉ từ raw read-back.
