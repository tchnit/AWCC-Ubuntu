# Giai đoạn 4 — kết quả thử AWCC fan boost

Ngày thực hiện: 2026-10-09.

## Kết luận

Kernel/firmware chấp nhận và giữ write `fan1_boost=224` trong `balanced`, nhưng
RPM của fan 1 không đổi trong cửa sổ tám giây. Trong các run lịch sử, `custom`
trở lại `balanced` dù `power-profiles-daemon` đã dừng; Phase 5E sau đó phát hiện
`awccd.service` là writer chưa được cô lập trong các run này. Vì vậy chỉ đường
ghi AWCC ở mức transport/read-back được xác nhận; hiệu lực điều khiển vật lý và
nguồn của thay đổi profile trong run cũ chưa được xác nhận.

Manual fan control trong ứng dụng tiếp tục bị khóa.

## Baseline

- Model: Alienware x17 R1
- BIOS: 1.27.0
- Kernel provider: `alienware_wmi`
- Platform profile: `balanced`
- AC: online
- Nhiệt độ: CPU 45 °C, GPU 39 °C
- Boost: `255 / 250 / 255 / 250`
- RPM: `4100 / 4100 / 2700 / 2000`
- Max RPM do provider báo: `4100 / 4100 / 2700 / 2000`

## Phép thử

Chỉ kênh 1 được đổi từ `255` xuống `224`. Ba kênh còn lại giữ nguyên. Trong tám
mẫu cách nhau một giây:

- read-back của kênh 1 luôn là `224`;
- fan 1 luôn là `4100 RPM`;
- các fan còn lại không đổi;
- CPU luôn 45 °C, GPU luôn 39 °C;
- không có thermal abort hoặc sensor error.

Runner yêu cầu chênh lệch tối thiểu 100 RPM để xác nhận tác động vật lý. Điều
kiện này không đạt nên kết quả được đánh dấu thất bại có kiểm soát.

## Rollback

Runner khôi phục cả bốn boost và read-back xác nhận đúng
`255 / 250 / 255 / 250`. Kiểm tra độc lập sau runner xác nhận:

- profile vẫn là `balanced`;
- CPU/GPU 45/40 °C;
- RPM `4100 / 4100 / 2700 / 2000`;
- không có kernel module hoặc cấu hình hệ thống nào bị thay đổi.

Runner và state directory tạm đã được xóa sau khi lưu log tại
`research/results/hardware-test-awcc-boost-2026-10-09.jsonl`.

## Thử nghiệm `custom + boost`

Sau authorization riêng, runner đặt profile `custom` và dành hai giây settle
trước khi ghi boost. Quan sát:

- `custom` được giữ trong bảy mẫu đầu, khoảng 1,8 giây;
- ngay sau khi vào `custom`, cả bốn boost về 0 và cả bốn RPM về 0;
- ở mẫu thứ tám profile trở lại `balanced`, boost tự về
  `255 / 250 / 255 / 250`;
- runner dừng trước write `fan1_boost=224`;
- rollback cuối xác nhận profile `balanced` và bốn boost ban đầu.

Sau rollback, RPM tăng dần và vượt các giá trị `fan*_max` mà provider công bố.
Vì vậy `fan*_max` không được dùng như giới hạn RPM vật lý hoặc mẫu số phần trăm
trong UI.

## Test cô lập `power-profiles-daemon`

Runner có watchdog đã dừng `power-profiles-daemon`, xác nhận daemon inactive rồi
chọn `custom`. Profile vẫn chỉ giữ bảy mẫu, khoảng 1,8 giây, và tự trở về
`balanced` ở mẫu thứ tám. Trong thời gian `custom`, cả bốn boost là 0; RPM giảm
chậm do quán tính thay vì lập tức về 0. Runner dừng trước write thử nghiệm và
khởi động lại daemon trong rollback.

Kết quả này loại riêng `power-profiles-daemon` khỏi cửa sổ đó, nhưng không loại
mọi userspace writer vì trạng thái `awccd` chưa được log. Log:
`research/results/hardware-test-awcc-isolated-boost-2026-10-09.jsonl`.

## Test handshake `custom + boost` tức thời

Để kiểm tra giả thuyết firmware đòi hỏi boost được lập trình ngay sau `custom`,
runner tiếp tục giữ `power-profiles-daemon` inactive và thực hiện:

1. ghi profile `custom`;
2. ghi ngay lại bộ boost baseline an toàn `255 / 250 / 255 / 250` cho cả bốn
   kênh;
3. read-back profile và cả bốn boost;
4. chỉ giảm fan 1 xuống 224 nếu handshake giữ ổn định.

Handshake hoàn tất trong 14,56885 ms; read-back ban đầu là `custom` và đúng cả
bốn boost. Tuy nhiên mẫu đầu sau 255 ms đã là `balanced`. Runner vì vậy dừng
trước khi giảm fan 1. Nhiệt độ giữ ở CPU/GPU 42/36 °C và RPM không giảm.

Kết luận lịch sử: thao tác ghi boost tức thời không làm `custom` giữ trong môi
trường run đó. Đây không đủ để gán rollback cho firmware/platform driver hoặc
thiếu protocol, vì `awccd` chưa được loại trừ.

Log: `research/results/hardware-test-awcc-custom-boost-handshake-2026-10-09.jsonl`
(SHA-256 `3a757110d2ab0db0ce4c67a2795e7f3d43d262368949455c91d83861d29073ed`).

## Giải thích từ source driver

Source `alienware-wmi-wmax.c` hiện tại làm hai việc khác nhau:

- các thermal profile thông thường được khám phá từ resource ID do firmware
  trả về;
- sau bước khám phá, driver **luôn** gán ID đặc biệt `0x00` và bật choice
  `custom`, với chú thích “Every model supports the custom profile”.

Do đó `custom` xuất hiện trong `platform_profile_choices` không chứng minh x17
R1 firmware đã công bố hoặc duy trì profile này. Tuy nhiên hai phép thử lịch sử
chưa cô lập `awccd`, nên chưa đủ bằng chứng để khẳng định giả định chung của
driver không đúng với BIOS 1.27.0. Cần một phép thử attribution mới sau khi
daemon được cô lập trước khi đánh giá lại hypothesis.

Tham chiếu source upstream:
[`awcc_platform_profile_probe()`](https://github.com/torvalds/linux/blob/master/drivers/platform/x86/dell/alienware-wmi-wmax.c#L1230-L1284).

## Trạng thái cuối

- `power-profiles-daemon`: active;
- profile: `balanced`;
- boost: `255 / 250 / 255 / 250`;
- RPM: `6300 / 6400 / 6800 / 5000`;
- CPU/GPU: 42/36 °C;
- runner và state directory tạm đã được xóa.

Thay đổi 31/255 trong `balanced` có thể chưa vượt qua bước RPM rời rạc của
firmware, nhưng thử giá trị thấp hơn lúc này không giải quyết được việc máy
không duy trì `custom` và làm tăng rủi ro nhiệt. Không thực hiện nếu chưa có
bằng chứng giao thức mới và một kế hoạch an toàn riêng.

## Hiệu chỉnh sau Phase 5E

Các run Phase 4 đã cô lập `power-profiles-daemon`, nhưng chưa kiểm tra hay log
trạng thái của `awccd.service`. Phase 5E nay chứng minh service root này ép
platform profile và đang ghi fan boost Manual. Vì vậy các quan sát `custom →
balanced` trong Phase 4 **không còn đủ để kết luận firmware/driver tự rollback**
hoặc để nộp draft upstream; `awccd` có thể đã là writer cạnh tranh. Kết quả
transport/read-back riêng lẻ vẫn là dữ liệu lịch sử, nhưng không chứng minh
takeover vật lý ổn định.

Không lặp lại các write boost này ngay. Trước hết cần chuyển daemon về profile
mode/boost 0 và dừng tạm thời bằng quy trình được cấp phép, rồi mới xét một phép
thử cô lập mới. Manual UI vẫn khóa. Xem
[PHASE5E_AWCCD_CONFLICT.md](PHASE5E_AWCCD_CONFLICT.md).
