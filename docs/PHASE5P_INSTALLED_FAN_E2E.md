# Phase 5P — E2E helper đã cài, 2026-10-15

## Trạng thái lịch sử — cập nhật mới nhất ở Phase 5Q

Đã xử lý được xác thực, cài bản CPU-start-relaxed và fan1 E2E đạt trong
[Phase 5Q](PHASE5Q_WARM_CPU_FAN_E2E.md). Các mục dưới giữ nguyên lịch sử trước
đó; không còn mô tả bản cài hiện tại.

Người dùng yêu cầu kiểm chứng/thử đường mới. Đã xây runner user-scope gọi
**đúng `/usr/libexec/awcc-fan-helper validation-session` đã cài**, không dùng
native sysfs writer trong runner, không dùng lại root diagnostic cũ. Mục tiêu:
từng kênh raw 64 → 100 → 64, 15 mẫu/mức để đủ lease 60 giây; sau đó thử EOF
và ngừng heartbeat với bộ boost khởi tạo 100, kiểm tra khôi phục độc lập giữa
mọi phiên. Không sweep toàn range hoặc nới guardian/thermal guards.

Runner `research/fan_helper_e2e.py` có confirmation riêng, đúng interpreter
app đã cài, candidate/source fingerprint check, AC/driver/controller/sensor
preflight, transcript exclusive-create, ACK channel/raw/four-level checks và
observer RPM thực. Không tự retry hoặc tự tạo activation record. Đủ 15 mẫu
mỗi phase mới đánh giá median bốn mẫu cuối, stability/direction/repeatability
như tiêu chí trước; không biến read-back thành bằng chứng RPM.

Trước chạy: Performance, boost 0/0/0/0, RPM 5000/5000/3000/3000, CPU/GPU
44/39 °C, AC online, BIOS auto 2/2/2/2; helper installed đúng digest
`2955223732c7795800680e61ae67babfc252fb468ddc2febd5bd4bab103bf0a5`,
không awccd/i8kmon. Đóng app tạm để tránh thay đổi profile đồng thời.

## Fan1 stop run1 — không tới bước bắt đầu

Log `research/results/hardware-fan-helper-2026-10-15-validation-fan1-stop-run1.jsonl`.
PolicyKit có `pkexec /usr/libexec/awcc-fan-helper validation-session` và PAM
agent-helper chờ xác thực. Hết 100 giây không có **bất kỳ** helper-event,
starting/ready/ACK, sample trong Custom hoặc evaluation. Runner đóng stdin,
chờ thêm final ACK và process; không SIGKILL root recovery owner. Khi runner
kết thúc, yêu cầu xác thực cũ có thể vẫn hiện; cần người dùng hủy hoặc xử lý
hộp thoại. Pipe đã đóng: xác thực muộn không thể gửi handshake start mới.

Không có bằng chứng helper đã chạy hoặc có fan write; tuyệt đối không coi
`passed=false` là RPM không đáp ứng. Bốn independent read-back cuối: PPD/
platform Performance, boost 0/0/0/0, RPM 5000/5000/3000/3000 và auto 2/2/2/2,
CPU/GPU mẫu cuối 43/38 °C. `helper_exit=null`, `final=null`, `audit=null`.
`restored=true` trong transcript này chỉ là baseline observer khớp, **không**
phải ACK chứng minh helper đã thực hiện recovery. Transcript giữ nguyên.
Runner mới phân biệt `start_handshake_sent`, `outcome=not-started` và
`recovery_confirmed` để các lần tiếp theo không nhập nhằng hai khái niệm đó.

Kiểm tra cuối: pkexec/PAM request cũ đã thoát, không có fan-helper process
hoặc thư mục `/run/awcc-fan-lease.*`. Polkit journal lúc 14:51:00 ghi **FAILED
to authenticate** cho action fan-session. Chưa xác định do không thấy hộp
thoại, hủy, sai thông tin hay timeout; không quy lỗi cho firmware/helper.

## Kiểm tra và việc còn lại

**272 tests đạt** sau bổ sung guard/evaluator/ACK tests của runner; không có
extra hardware runs trong các unit tests. Chưa sửa/cài lại app/helper, chưa
tạo deployment record, chưa mở cổng ghi. Đã mở lại desktop app sau khi kiểm tra
baseline. Cần người dùng trả lời có thấy hộp thoại và xác thực trực tiếp trên
máy; không gửi mật khẩu vào chat. Chỉ thử lại bằng log mới sau khi xử lý luồng
xác thực, giữ tất cả giới hạn, không tạo song song nhiều yêu cầu PolicyKit.

## Tiếp nối: xác thực thành công, preflight nhiệt độ chặn phép ghi

Người dùng xác nhận không thấy hộp thoại của run1. Kiểm tra read-only cho
thấy session 2 active, X11, không khóa; GNOME Shell đã đăng ký authentication
agent cho đúng session. Không có lỗi GNOME Shell trong khoảng 14:47:30–14:52.
Cảnh báo group `admin` không tồn tại cũng xuất hiện ở các lần xác thực thành
công trước đó; không đủ bằng chứng quy đây là nguyên nhân. Không sửa rule,
PAM, restart agent hay bỏ xác thực.

Lúc 15:34:19 chạy phép thử **chỉ xác thực**, `pkcheck` cho đúng action
`io.github.awcclinux.ControlCenter.fan-session`, có interaction và timeout
35 giây. Exit 0; journal 15:34:23 xác nhận ONE-SHOT authorization thành công.
Người dùng xác nhận thấy hộp thoại và đã xác thực trực tiếp. Không gọi helper,
không ghi phần cứng; quyền one-shot này không được coi là quyền cho lần chạy
helper kế tiếp. Nguyên nhân hộp thoại run1 không hiển thị vẫn chưa xác định.

Sau đó tạm đóng app và gọi runner fan1/stop/run2. **Preflight từ chối ngay
trước `Popen(pkexec)`** vì cảm biến vượt ngưỡng bắt đầu 50 °C. Quan sát độc lập
lúc 15:35:13: CPU 53 °C, GPU 44 °C, SODIMM 43 °C, Other 42 °C; PPD/platform
Performance, boost 0/0/0/0, RPM 5000/5000/3000/3000. Không có helper session
hay phép ghi mới. File run2 đã được exclusive-create nhưng rỗng do preflight
raise trước event đầu tiên; giữ nguyên file, lần thử sau phải dùng run mới.
Đã mở lại app. Không nới thermal guard, chưa tạo activation record.

Điều kiện tiếp tục: hạ tải để mọi cảm biến ≤50 °C, giữ AC, kiểm tra preflight
mới rồi mới thử lại. Xác thực thành công không phải bằng chứng E2E quạt.

## Yêu cầu tiếp theo: bỏ chặn khởi đầu 50 °C riêng cho CPU

Sau khi người dùng yêu cầu bỏ chặn CPU, đã sửa **workspace candidate** trong
`fan_policy.check_snapshot`: CPU không còn phải ≤50 °C khi bắt đầu. GPU và
các cảm biến ngoài CPU vẫn phải ≤50 °C. CPU vẫn phải có dữ liệu hợp lệ/đúng
nguồn và dưới 70 °C; ngưỡng dừng 70 °C, mức tăng từng cảm biến ≥10 °C, AC,
quạt đang quay, singleton, heartbeat, lease và guardian không thay đổi.
Không coi việc nới ngưỡng bắt đầu là bằng chứng an toàn/đạt E2E ở nhiệt độ cao.

Test mới bao phủ CPU 50.1/53/69.9 °C được nhận ở preflight, CPU 70 °C và
dữ liệu lỗi bị từ chối, cảm biến ngoài CPU 50.1 °C vẫn bị chặn; fake session
CPU 53→63 và 65→70 đều khôi phục, GPU tăng 10 °C không bị CPU nóng che khuất.
Đây là kiểm thử giả lập, không ghi phần cứng. Profile helper cũ (nút chọn
thermal Custom) vẫn giữ điều kiện ≤50 °C của chính nó; thay đổi này chỉ áp
dụng cho fan session mới, không lén thay policy của profile helper.

Bản nguồn trước sửa được sao lưu tại
`research/results/before-cpu-start-relax.LWM1fQ/`. Chưa cài lại root helper
hoặc desktop package, chưa chạy lại hardware test; bản đã cài vẫn dùng ngưỡng
cũ. Cần cài đồng bộ app/helper có backup trước khi chạy validation bằng
interpreter đã cài; không trộn source mới với root payload cũ hoặc bỏ kiểm tra
fingerprint. Chưa tạo deployment record, gate production vẫn đóng.

Kiểm thử sau sửa: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -m
unittest discover -s tests -v` đạt **275 tests**, bao gồm GTK và fake port;
không có hardware write hoặc cài đặt hệ thống trong lượt này.

## Đã cho phép cài và thử lại — GNOME từ chối mở hộp thoại

Người dùng cho phép cập nhật có backup rồi thử lại fan1. Đã sao lưu app/venv,
desktop entry và source pyproject tại
`~/.local/share/awcc-before-cpu-start-relax.xZxE3s/` trước thay đổi.
Nâng version nguồn thành `0.1.2+fanraw255.2`, build wheel local, không tải
dependency: `dist/phase5q/alienware_control_center_linux-0.1.2+fanraw255.2-py3-none-any.whl`,
SHA-256 `1c3a54663da58c671c4857da502f3a4b050daeb9aa1a7103a2b77ca4caa2e900`.
Chạy lại toàn bộ 275 tests đạt.

Hai yêu cầu cài qua `pkexec /bin/bash tools/install-fan-helper.sh` lúc
15:38:50 và 15:40:06 đều exit 126, `Request dismissed`. Lần hai có trì hoãn
3 giây và giữ parent shell riêng. Cả hai có log GNOME Shell **Failed to show
modal dialog. Dismissing authentication request** cho action exec. Đây là
bằng chứng lỗi mở modal ở hai lần cài này, không phải bằng chứng người dùng
hủy, nhập sai mật khẩu hoặc firmware từ chối. Không suy diễn thành nguyên
nhân chắc chắn của timeout fan-session run1 trước đó.

Installer chưa chạy, root payload không thay đổi và chưa phát sinh backup
root mới. Không cài desktop riêng để tránh app/helper lệch payload. Bản cài
vẫn `0.1.2+fanraw255.1`, candidate_reason None, digest cũ
`2955223732c7795800680e61ae67babfc252fb468ddc2febd5bd4bab103bf0a5`.
Read-only giữa hai lần: Performance, raw 0/0/0/0, RPM 5000/5000/3000/3000,
CPU 56 °C, GPU 48 °C, SODIMM 43 °C, Other 44 °C. Chưa gọi runner/phép ghi.
Không đổi PolicyKit/PAM, không restart GNOME hay bỏ xác thực. Dừng retry tự
động; cần giải phóng input grab/modal hoặc chạy installer trực tiếp từ
Terminal của người dùng. Sau khi root install thực sự thành công mới cài
desktop đồng bộ, đối chiếu fingerprint và thử phần cứng bằng run mới.
