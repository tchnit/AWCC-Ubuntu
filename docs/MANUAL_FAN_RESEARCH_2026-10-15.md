# Điều khiển quạt thủ công x17 R1 — rà soát 2026-10-15

## Kết luận tại lượt nghiên cứu ban đầu

Hướng ưu tiên là **driver gốc alienware_wmi → Custom → fanN_boost**, không
phải tiếp tục ép SMM takeover. Đây là giả thuyết có cơ sở, **chưa phải bằng
chứng điều khiển RPM đã thành công**. Chưa thực hiện hardware write mới.

Tài liệu kernel mô tả boost 0–255 và lưu ý một số thiết bị chỉ điều khiển quạt
ổn định khi chọn Custom. Boost không phải PWM tuyệt đối hay phần trăm RPM;
firmware vẫn quyết định mức nền. Vì thế không hứa khóa một RPM chính xác.
[Nguồn kernel](https://docs.kernel.org/admin-guide/laptops/alienware-wmi.html).

AlienFan-SDK của T-Troll dùng `Unlock() → SetPower(0)`; CLI cũng gọi
`SetPower(0)` cho `unlock`, sau đó gửi boost theo fan ID. Source có ngoại lệ
cho một số loại thiết bị, nên đây chỉ là đối chiếu giao thức, không dùng nó
làm bằng chứng runtime trên x17 R1.
[SDK](https://github.com/T-Troll/alienfx-tools/blob/master/alienfan-tools/alienfan-SDK/alienfan-SDK.cpp),
[CLI](https://github.com/T-Troll/alienfx-tools/blob/master/alienfan-tools/alienfan-cli/alienfan-cli.cpp).

## Trạng thái được đọc lại

Snapshot 12:02 ngày 15/10/2026, múi giờ Việt Nam:

- Ổ New Volume đã mount; project đọc được. Không mount/thay cấu hình ổ đĩa.
- x17 R1, BIOS 1.27.0, kernel 7.0.0-38-generic.
- Loaded alienware_wmi srcversion `28A4134FBF8432C66D7C668`.
- Platform Performance; ACAD online=1.
- awccd/i8kmon inactive và disabled, không awccd socket.
- CPU 54 °C AWCC, GPU 45 °C NVIDIA NVML; SODIMM/Other 43 °C.
- AWCC RPM theo thứ tự kênh 1–4: 5000/5000/3000/3000; boost 0/0/0/0.
- Bốn dell_smm pwm_enable=2. Helper root-owned vẫn khớp source.

Không coi nhiệt độ/AC này còn nguyên lúc thử. CPU 54 °C ở snapshot trên chưa
đủ guard Custom ≤50 °C; nếu được phép thử, cần đọc lại và làm mát bằng Low
Power trước. Không tự đổi profile trong lượt nghiên cứu này.

## Vì sao cần một phép thử khác, không phải thử lại từ đầu

1. Phép 255 → 224 trước đây chạy trong **Balanced**, không chứng minh được
   hành vi khi Custom đã giữ ổn định. Khoảng raw nhỏ/tình trạng bão hòa cũng
   chưa được loại trừ; bão hòa chỉ là giả thuyết, chưa đo.
2. Các run Custom ngày 09/10 bị ghi đè về Balanced, chưa cô lập awccd. Run
   handshake dừng trước bước đổi fan1 xuống mức test. Không dùng chúng để kết
   luận firmware từ chối điều khiển boost trong Custom.
3. Phase 5E xác định awccd là writer cạnh tranh; Phase 5K sau khi cô lập đã
   xác minh Custom qua helper production và chuyển về mode chuẩn thành công.
4. Tuy vậy Phase 5K **không** ghi boost mới trong Custom. Đây chính là bằng
   chứng vật lý còn thiếu, không cần lặp SMM/PWM hoặc thử thêm thermal mode.

Xem [Phase 4](PHASE4_HARDWARE_TEST_AWCC_BOOST.md),
[Phase 5E](PHASE5E_AWCCD_CONFLICT.md), [Phase 5K](PHASE5K_ALL_THERMAL_PROFILES.md).

## Đối chiếu firmware tĩnh mới

`research/analyze_awcc_fan_setter.py` xác minh cấu trúc AML từ **DSDT đã lưu
ngày 09/10**, không gọi firmware. Nó tái dùng parser kiểm tra checksum, WMAX,
nguồn tham số và nhánh method; chỉ chấp nhận cây fan setter đúng dạng đã biết,
từ chối các selector, phép gán, đường dẫn, tail/reply hoặc fan ID trùng khác.

DSDT SHA-256:
`4a7c8c5a8adddca255bc414d0f92afe5db0d5f1b133644d710dfb2600900c9f4`.

Nhánh WMAX method 0x15, operation 2 nhận fan ID ở DM21, giá trị ở DM22:

| Fan ID | Đích tên AML tương đối với AMW1 | Kênh theo cache driver lịch sử |
| --- | --- | --- |
| 0x32 | ^^PC00.LPCB.EC0_.C1FW | AWCC fan1, CPU |
| 0x33 | ^^PC00.LPCB.EC0_.G1FW | AWCC fan2, GPU |
| 0x3b | ^^PC00.LPCB.EC0_.C2FW | AWCC fan3, CPU |
| 0x3c | ^^PC00.LPCB.EC0_.G2FW | AWCC fan4, GPU |

Nhánh nhận ID hợp lệ gán DM22 tới tên trên và đặt Local0=0. ID không biết đặt
Local0=0xffffffff. Điều này chứng minh cấu trúc chuyển lệnh trong bảng đã lưu,
**không** chứng minh EC áp dụng tốc độ, tên đích là Field ở địa chỉ nào, range
vật lý an toàn hay RPM đáp ứng. Không truy cập trực tiếp các tên/địa chỉ EC.

Mã Ubuntu đang chạy đối chiếu được: profile Custom là 0x00; fan_boost_store
gửi method 0x15/operation 2, fan ID từ discovery, raw boost clamp 0–255. Không
cần driver mới để gửi lệnh này. Kênh AWCC và dell_smm không cùng thứ tự.

Kiểm tra offline mới: bốn bài test decoder đạt; toàn bộ suite **178 tests đạt**.
Không thay parser cũ để suy diễn các hành vi firmware ngoài phạm vi đã đọc.

## Hiệu chỉnh cách đánh giá capability

`dell_smm/pwm_enable=2` là trạng thái báo qua giao diện SMM, không phải bằng
chứng tất cả đường điều khiển AWCC đều không dùng được. Không dùng điều kiện
phải thấy pwm_enable=1 làm tiêu chí bắt buộc cho AWCC boost.

Ứng dụng hiện vẫn giữ manual capability false vì **chưa có actuator/RPM
validation**, không phải kết luận không thể làm được. Nếu boost được chứng
minh, cần gate riêng cho AWCC boost đã xác minh, giới hạn Custom; không giả
đổi SMM mode thành manual, không tự bật lại daemon cũ.

## Phép thử tiếp theo đề xuất — cần permission riêng, chưa chạy

Mục tiêu đầu tiên chỉ là xác minh điều khiển vật lý kênh AWCC fan1. Không coi
một kênh đạt là cả bốn kênh, fan curve hay RPM tuyệt đối đã hoàn tất.

1. Dùng stock driver; chụp baseline PPD/platform/boost/RPM, kiểm tra AC,
   CPU/GPU hợp lệ ≤50 °C, đúng model/BIOS/driver, không writer cạnh tranh.
   Đóng app để tránh thao tác profile đồng thời; không stop PPD.
2. Nếu cần, dùng đường PPD Low Power đã xác minh để làm mát; thời gian chờ có
   giới hạn. Bắt đầu phép ghi chỉ sau khi đã arm watchdog độc lập.
3. Chọn Custom và đặt bộ boost raw ban đầu 100/100/100/100. Sau đó chỉ đổi
   fan1 theo chuỗi A–B–A: 64 → 100 → 64; ba kênh kia giữ 100. Mỗi mức khoảng
   12 giây để quan sát quán tính; không giữ fan ở raw 0, không dùng overboost
   calibration hay max RPM firmware làm mẫu số. Đây là giá trị raw thử nghiệm,
   không phải 64%/100% RPM và chưa được khẳng định là range vật lý an toàn.
4. Log tất cả fan/RPM/boost, profile, nhiệt độ CPU AWCC/GPU NVIDIA, AC và PPD
   trong từng mẫu. Abort khi mất sensor/AC, profile đổi, boost bị ghi đè, fan
   không quay sau settle hoặc nhiệt độ tới 70 °C/tăng ≥10 °C từ baseline.
5. So sánh nhiều mẫu cuối A/B/A, yêu cầu chênh RPM có hướng và tái lập; một
   spike hoặc chỉ read-back raw không được coi là thành công. Không spam write
   mỗi tick. Không đạt thì ghi nhận inconclusive/failed, không mở UI giả.
6. Watchdog hard deadline khoảng 75 giây cho đoạn Custom; `finally` và watchdog
   phải đưa về đường profile chuẩn đã xác minh và khôi phục baseline boost,
   xác minh lại cả PPD lẫn physical profile. Lưu ý profile setter có thể reset
   boost, nên restore profile trước rồi đối chiếu/khôi phục boost và đọc lại.
   Phải xử lý same-value PPD alias, không dùng direct Performance helper chưa
   xác minh. Không báo restore thành công chỉ vì CLI exit 0.

Rủi ro: Custom/boost có thể giảm RPM, quạt có quán tính và restore vẫn có thể
thất bại; watchdog phần mềm không bảo vệ mất điện/kernel treo. Do đó không
chạy khi tải nặng, không thử ép quạt thấp khi nóng. Chỉ sau permission cụ thể
mới xây/kiểm thử runner có guard và thực thi. Không dùng lại runner handshake
cũ: nó dừng PPD, đọc GPU WMI lỗi và có giả định baseline/rollback đã lỗi thời.

Không cài package, đổi kernel/module, sửa service, dùng raw SMM hay ghi EC.

## Bổ sung sau khi người dùng cấp phép

Run1 đã được thực hiện nhưng không đạt gate làm mát ≤50 °C, nên dừng trước
Custom/boost thử nghiệm. Restore Performance/boost gốc đã được xác minh.
Xem [Phase 5L](PHASE5L_CUSTOM_BOOST_VALIDATION.md). Không coi đây là kết quả
âm tính của khả năng điều khiển RPM.

Sau khi người dùng giảm tải, run2 đã vào Custom và quan sát AWCC fan1 tăng
đến 4100 RPM ở raw 100, giảm/giữ 3300 RPM ở raw 64, trong khi SMM vẫn báo
auto. Đây là bằng chứng vật lý mới cho đường AWCC. Tuy nhiên, kiểm tra ổn
định toàn A–B–A chưa đạt vì A1 chưa settle; không nới tiêu chí, chưa mở UI
production và chưa xác minh riêng ba kênh còn lại. Chi tiết trong Phase 5L.

Run3 được cấp phép riêng tăng cửa sổ lên 20 giây/mức, giữ nguyên evaluator,
watchdog 75 giây và các ngưỡng an toàn. Fan1 đã đạt A–B–A: median cuối
3300 → 4100 → 3300 RPM ở raw 64 → 100 → 64, span cuối đều 0, chênh lệch
hai chiều 800 RPM (threshold 330). CPU 42–43 °C, GPU 38–40 °C. Restore
Performance/boost 0 đã xác minh và kiểm tra độc lập; không đổi service/driver.
Đây là bằng chứng ổn định trong cửa sổ thử của một kênh, không phải kiểm chứng
ba kênh còn lại hay production actuator. Bước tiếp theo cần cấp phép riêng cho
phép thử cô lập từng kênh khác. Xem log và giới hạn ở Phase 5L.

Tiếp nối sau permission: [Phase 5M](PHASE5M_REMAINING_FAN_CHANNELS.md) đã thử
riêng fan2/3/4. Fan2 đạt 3200 → 4100 → 3200 RPM, fan4 đạt 1200 → 2000 → 1200
RPM. Fan3 thấy 1700 → 2700 nhưng khởi tạo trễ khoảng 28 giây làm watchdog
dừng khi A2 mới có hai mẫu; không kết luận pass hoặc firmware không điều khiển
được fan3. Cả ba run đã restore Performance/boost gốc, kiểm tra độc lập đạt.
Tổng 3/4 kênh đạt tại hai raw 64/100; chưa production actuator. Chỉ thêm timing
logging trước fan4, không tái hiện trễ; cần permission riêng nếu thử lại fan3.

Fan3 retry1 sau permission riêng đã đạt đủ A–B–A 20 mẫu/mức: 1700 → 2700 →
1700 RPM, delta hai chiều 1000, span cuối 0, threshold 300. Không đổi evaluator,
guard/watchdog. Custom write 0,073 giây, boost writes khoảng 1 ms, không tái
hiện trễ 28 giây nên chưa xác định nguyên nhân trễ lần đầu. CPU 43–44 °C,
GPU 39–41 °C; restore và kiểm tra độc lập Performance/boost gốc đạt. Tổng
4/4 kênh đã đạt tại raw 64/100 trong cửa sổ thử, chưa production actuator hoặc
toàn range/long-run. Bước tiếp theo là backend lease/heartbeat/watchdog và
Custom-only control, không lặp kiểm chứng đã rõ nếu không có giả thuyết mới.
