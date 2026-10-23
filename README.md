# Alienware Control Center for Linux

Ứng dụng GTK 4/libadwaita cho Alienware x17 R1 trên Ubuntu. Dự án đọc cảm biến,
hiển thị trạng thái bốn quạt AWCC và điều khiển thermal profile qua những đường
đã được kiểm chứng trên máy thử nghiệm.

## Trạng thái

Mã nguồn hiện là ứng viên **0.1.2+fanraw255.2**. **Điều khiển quạt thủ công
trong ứng dụng vẫn bị khóa**: chưa có bản ghi xác nhận end-to-end cho đúng
payload đang chạy. Việc build hoặc cài file không tự mở khóa tính năng này.
Bản đã cài trên máy thử nghiệm có thể khác mã nguồn trong repo; hãy kiểm tra
payload trước khi thử một helper mới.

- Bốn kênh AWCC đã cho thấy thay đổi RPM với raw 64 ↔ 100 trong phép thử
  chẩn đoán riêng từng kênh. Fan 3 từng trễ khởi tạo và cần một lần thử lại.
- Fan 1 đã đạt phép thử end-to-end qua fan helper ứng viên với raw
  64 → 100 → 64, median 3400 → 4100 → 3400 RPM, rồi xác nhận khôi phục.
- Fan 2/3/4, mất kết nối, hết heartbeat, đường client production và các giá
  trị raw khác vẫn cần kiểm chứng qua helper hiện tại. Raw 0–255 là ABI của
  firmware, không phải phần trăm RPM hay cam kết tốc độ tuyến tính.
- Bản sửa an toàn gần nhất thêm shared lock cho hai privileged helper, chặn
  write sau deadline, giới hạn PPD recovery retry và kiểm tra ACK/timeout.
  Đường PPD trực tiếp từ desktop và các chương trình ngoài dự án vẫn chưa cùng
  tham gia root-owned lock. Chưa cài hoặc thử phần sửa này trên phần cứng.

Xem [kết quả fan helper gần nhất](docs/PHASE5Q_WARM_CPU_FAN_E2E.md),
[kiến trúc phiên quạt](docs/PHASE5N_BOUNDED_FAN_SESSION.md) và
[roadmap](docs/ROADMAP.md). Các báo cáo cũ ghi lại từng thời điểm thử nghiệm,
không mô tả trạng thái cài đặt hiện tại của một máy khác.

## Tính năng

- Tự tìm alienware_wmi/dell_smm, đọc nhiệt độ CPU/GPU, RPM, boost, thermal
  profile và tài nguyên CPU/GPU/RAM trong luồng nền.
- Ưu tiên NVIDIA cho nhiệt độ GPU khi có dGPU; thiếu provider thì hiển thị
  trạng thái thiếu dữ liệu thay vì giá trị giả.
- Thermal profile có allow-list, kiểm tra model/BIOS, nguồn AC và read-back.
  Low Power/Balanced/Performance đi qua power-profiles-daemon khi khả dụng;
  Quiet/Balanced+/Custom dùng profile helper riêng. Custom là thermal profile,
  không đồng nghĩa quạt thủ công.
- Bốn thanh chọn AWCC raw chỉ gửi lệnh sau nút Áp dụng trong phiên Custom được
  xác thực và đã mở gate. Mặc định chúng không có quyền hardware write.
- Không có đường ghi PWM legacy hay lệnh SMM trong ứng dụng production.

## Chạy và kiểm thử

Cần Python 3.12+, GTK 4, libadwaita, PyGObject và venv của Ubuntu. Giao diện
chạy dưới user thường; không dùng sudo để mở app.

~~~bash
./run.sh
PYTHONPATH=src python3 -m unittest discover -s tests -q
~~~

Suite dùng sysfs giả và child process giả; nó không gửi lệnh điều khiển phần
cứng. Trên workspace có dữ liệu firmware cục bộ, lần kiểm tra gần nhất đạt
**289 tests, 0 lỗi, 0 skipped**. Bản clone không có ACPI dump riêng của máy sẽ
skip một test đối chiếu bảng DSDT; các test giao diện còn tùy display/GTK sẵn
có. Xem [nguồn nghiên cứu và dữ liệu cục bộ](research/README.md).

## Cài đặt

Chỉ cài ứng dụng desktop cho user hiện tại:

~~~bash
./tools/install-desktop.sh
~~~

Script build wheel offline và cài vào $XDG_DATA_HOME/alienware-control-center
(mặc định ~/.local/share/alienware-control-center nếu biến chưa được đặt).
Nó không cài privileged helper, PolicyKit, kernel module hay driver. Các script
tools/install-helper.sh và tools/install-fan-helper.sh thay file hệ thống,
được giữ tách riêng. Không chạy chúng như một bước cài app thông thường; cần
đánh giá payload, backup và kế hoạch kiểm chứng phần cứng riêng.

Kiểm tra helper đã cài bằng lệnh chỉ đọc:

~~~bash
python3 tools/check-helper.py
~~~

Nếu source mới không khớp helper hệ thống, các nút cần helper sẽ không khả dụng.
Production fan-control còn yêu cầu bản ghi xác nhận đúng hardware/payload; repo
không chứa và không tạo bản ghi đó.

## Cấu trúc và dữ liệu nghiên cứu

src/awcc_linux/ chứa GTK, telemetry, profile client/controller và fan
session/helper. tests/ dùng fake cho các đường ghi. data/ chứa desktop entry,
PolicyKit action và launcher. tools/ có installer/build script. docs/ giữ
kiến trúc, bằng chứng và các quyết định theo giai đoạn. research/ chứa runner
chẩn đoán, bản vá driver và phần source kernel nhỏ cần cho test offline.

.gitignore loại virtual environment, wheel, module biên dịch, archive kernel,
ACPI dump, transcript phần cứng, screenshot và snapshot/backup cũ trong
research/results/. Các file này vẫn ở máy đã tạo ra chúng; một số link đến
research/results/ trong báo cáo lịch sử vì thế không mở được từ bản clone.
Không dùng transcript thiếu để suy ra một chức năng đã được xác minh.

Ứng dụng khai báo GPL-3.0-or-later trong pyproject.toml; xem [LICENSE](LICENSE).
Mã kernel bên thứ ba trong research/ giữ nguyên SPDX và copyright của từng file.
