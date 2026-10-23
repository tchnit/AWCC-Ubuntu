# Phase 5Q — cài policy CPU-start mới, fan1 helper E2E đạt

Ngày 15/10/2026, giờ Việt Nam. Người dùng cho phép cài có backup và thử lại;
sau đó xác nhận đã đóng menu/hộp thoại và sẵn sàng xác thực. Không thay đổi
PolicyKit/PAM, driver/kernel, service hoặc cấu hình khởi động.

## Cài đặt và backup

15:52:17: PolicyKit xác thực thành công, installer exit 0. Root payload trước
cài được backup tại `/var/backups/awcc-fan-helper.3iAh4c/` (root-only), gồm
library, launcher và policy hiện có. App/venv/desktop entry cũ đã backup tại
`~/.local/share/awcc-before-cpu-start-relax.xZxE3s/`; các backup
Phase 5O vẫn giữ. Venv backup cần phục hồi về đúng vị trí gốc khi rollback.

Đã cài desktop **0.1.2+fanraw255.2**, root fan helper và policy đồng bộ. Tất
cả module Python app đã đối chiếu byte-for-byte với source, candidate gate
trả None; profile helper cũ vẫn khớp source và không đổi. Digest fan/common:
`bfcfaa316db113f3f632e21b1a492f74ada13bda310b2cc278109142fd70fe66`.

Wheel lưu tại `dist/phase5q/alienware_control_center_linux-0.1.2+fanraw255.2-py3-none-any.whl`,
SHA-256 `1c3a54663da58c671c4857da502f3a4b050daeb9aa1a7103a2b77ca4caa2e900`.
Installer desktop build wheel riêng trong thư mục tạm; hash zip khác do
metadata build, không dùng hash của wheel lưu để khẳng định archive đã cài
giống từng byte. Các module Python đã cài được kiểm tra trực tiếp như trên.
275 tests đạt trước cài; không cài dependency hệ thống hoặc từ mạng.

Policy mới chỉ bỏ ngưỡng CPU ≤50 °C lúc bắt đầu **fan session**. Dữ liệu CPU
vẫn phải hợp lệ và dưới 70 °C; mọi cảm biến ngoài CPU vẫn ≤50 °C khi bắt đầu.
Giới hạn tăng từng sensor 10 °C, RPM, AC, model/BIOS/kernel/driver, heartbeat,
lease 60 giây, guardian 75 giây và tối đa một kênh khác raw 100 không đổi.
Profile helper cho nút thermal Custom vẫn giữ điều kiện ≤50 °C riêng.

## Fan1 validation / stop / run3

Transcript thật, không sửa:
`research/results/hardware-fan-helper-2026-10-15-validation-fan1-stop-run3.jsonl`.
Chạy bằng interpreter app đã cài, gọi đúng fan helper `validation-session`;
không dùng native writer trong runner hoặc root diagnostic cũ.

Preflight 15:52:50: Performance ở PPD và platform, CPU 56 °C, GPU 46 °C,
SODIMM/Other 44 °C, raw 0/0/0/0, RPM 5000/5000/3000/3000, SMM auto 2/2/2/2.
PolicyKit xác thực action fan-session thành công. Helper phát starting, nhận
handshake start và ready với 54.64 giây còn lại. Audit root-only:
`/run/awcc-fan-lease.vewbjzw9/audit.jsonl` (chưa sao chép/đọc audit này).

Một kênh thay đổi, ba kênh còn lại giữ raw 100. Ba phase đủ 15 mẫu/mức:

| Phase | Raw kênh 1 | Median RPM bốn mẫu cuối |
| --- | ---: | ---: |
| A1 | 64 | 3400 |
| B | 100 | 4100 |
| A2 | 64 | 3400 |

Evaluator giữ nguyên tiêu chí stability/direction/repeatability: tails ổn
định, tăng/giảm đều 700 RPM so với mức yêu cầu tối thiểu 340 RPM, lặp lại mức
thấp đạt. Không đổi tiêu chí để làm kết quả pass. Mỗi set có ACK khớp channel,
raw và toàn bộ bốn level, observer xác nhận profile Custom/boost/RPM thực.
CPU trong 45 mẫu 55–56 °C, GPU 46 °C. Không thử raw ngoài 64/100.

15:53:52 gửi stop. 15:54:00 helper trả `mutated=true`, `restored=true`, exit 0.
Bốn mẫu độc lập sau đó xác nhận Performance cả PPD/platform, boost 0 trên cả
bốn kênh, SMM BIOS-auto 2 và quạt còn quay. RPM sau chuyển Performance còn
đang giảm dần (mẫu đầu 6300/6400/4700/3200), không giả định profile/raw phục
hồi có nghĩa RPM phải bằng ngay giá trị trước test. Quan sát muộn trở lại
5000/5000/3000/3000, CPU 56 °C/GPU 47 °C. Runner complete: passed/restored/
start_handshake_sent/recovery_confirmed đều true, error null. Không còn tiến
trình session/helper của phép thử. App được mở lại sau kiểm tra.

## Còn lại trước khi mở UI production

- Kênh 2/3/4 qua **helper mới**; các diagnostic 64/100 cũ vẫn là bằng chứng
  vật lý có giá trị nhưng không thay thế kiểm chứng actuator/protocol mới.
- Khôi phục khi EOF và mất heartbeat trên helper đã cài.
- Xác minh đường production/client/UI với đúng payload sau khi đủ bằng chứng.

Chưa tạo `/usr/lib/alienware-control-center/fan-control-verified.json`, gate
production vẫn đóng. Fan1 đạt không chứng minh toàn raw 0–255, vận hành dài
hạn, hoặc đã giải thích được lần trễ 28 giây trong Phase 5M. Không bỏ guard,
không tự thử thêm các kênh hoặc fault session trong lượt này.
