# Giai đoạn 5B — khoanh vùng AWCC / EBADRQC

Ngày: 2026-10-09. Máy: Alienware x17 R1, BIOS 1.27.0.

## Kết luận chính

Đã khoanh vùng lỗi G-Mode ở **truy vấn trạng thái Game Shift**, trước toggle và
trước kích hoạt profile. Kết luận dựa trên bảng AML của máy, mã nguồn đúng source
package, disassembly của module đang cài và log phép thử đã có; không gọi lại
firmware để xác nhận cùng một lỗi.

```text
force_gmode=1 → setter profile
  → WMAX(method=0x25, operation=0x02): hỏi Game Shift
  → AML không có case 0x25 → nhánh mặc định trả 0xFFFFFFFF
  → driver ánh xạ thành -EBADRQC (errno 56) → dừng setter
  → không đến toggle / activate profile
```

Điều này giải thích tại sao cả Performance lẫn Balanced đều lỗi khi còn bật
force_gmode trong phép thử trước. Không phải bằng chứng Game Shift đã được bật
rồi thất bại khi kích hoạt profile. Giá trị raw `0xFFFFFFFF` ở đây được suy ra
từ nhánh AML đã kiểm chứng, **không phải** raw reply vừa đo bằng live WMI call.

## 1. Đối chiếu đúng source Ubuntu

Installed package xác minh lại:

- `linux-modules-7.0.0-38-generic`;
- source `linux-hwe-7.0`, version `7.0.0-38.38~24.04.4`;
- loaded `/sys/module/alienware_wmi/srcversion`: `28A4134FBF8432C66D7C668`.

Metadata `.dsc` lấy từ [Ubuntu HTTPS archive](https://archive.ubuntu.com/ubuntu/pool/main/l/linux-hwe-7.0/linux-hwe-7.0_7.0.0-38.38~24.04.4.dsc).
Archive đầy đủ lấy qua mirror HTTP đang được apt của máy cấu hình, chỉ trích
xuất sau khi SHA-256 khớp metadata từ HTTPS:

| Dữ liệu | SHA-256 |
| --- | --- |
| `linux-hwe-7.0_7.0.0.orig.tar.gz` | `c6343795c8c7e4feff55f5b309365c8e0eaf49cd6abcb412e32315313f149536` |
| `7.0.0-38.38~24.04.4.diff.gz` | `cd0996991ef58d83f4a7c64984b93d881eb10d450032348b482c9fbf4e7130ff` |

Đã trích xuất bốn file `alienware-wmi-base.c`, `alienware-wmi-legacy.c`,
`alienware-wmi-wmax.c`, `alienware-wmi.h` vào
`research/sources/ubuntu-hwe-7.0/alienware/`. Ubuntu diff không có thay đổi cho
bốn file này; `diff -u` với bản upstream tag v7.0 đã tải cho kết quả giống hệt.
Không dựa vào nhánh master để kết luận về driver đang chạy.

Module stock được sao chép/giải nén để disassemble, không nạp lại:
`research/sources/ubuntu-hwe-7.0/alienware-wmi-installed.ko`, SHA-256
`0dfcc686ca3e9517af870fce851ee678e9d875e5e23e070bc1cc0f7a8b9fc398`.
`awcc_platform_profile_set` trong binary gọi method `0x25` với operation `2`
trước các nhánh operation `1` và method `0x15`; reply lớn hơn `0xFFFFFFFD`
đi tới return `-56`. Các địa chỉ tương ứng: `0x2c7f`, `0x2c84`, `0x2c97`,
`0x2cd7`. Đây là xác nhận độc lập bằng binary của đường đi lỗi.

Build baseline offline thành công với headers đúng kernel, nhưng `srcversion`
của bản external build (`22697BF46BB665FD2E285BB`) khác module Ubuntu đang cài.
Vì vậy không khẳng định rebuild tái tạo binary stock hay dùng hash build để
thay thế bằng chứng từ archive/diff và disassembly. Chưa xác định riêng nguyên
nhân khác biệt srcversion; artefact baseline không được nạp.

Hai lần tải archive qua HTTPS trước đó bị timeout và git Launchpad trả 403.
Các file tải dở giữ hậu tố `.partial`, không dùng làm source. Không bỏ kiểm tra
TLS, không sửa apt và không cài gói để khắc phục tải.

## 2. Dữ liệu hiện có từ máy — chỉ đọc cache

Đọc ba file debugfs `system_description`, `pprof_data`, `hwmon_data` sau khi
kiểm tra source: chúng in dữ liệu driver đã lưu lúc probe, không evaluate WMI.
Không đọc `gpio_ctl/*`, không bật dynamic debug và không gọi raw WMI/SMM.

- GUID: `A70591CE-A997-11DA-B012-B622A1EF5492`.
- Object ID: `AX`; instance count: 1; expensive: 0.
- system description: `0x06000204`: bốn fan, hai sensor, sáu thermal resources.

| Profile | ID cached |
| --- | --- |
| Low-power | `0xA5` |
| Quiet | `0xA3` |
| Balanced | `0xA0` |
| Balanced-performance | `0xA1` |
| Performance thường | `0xA4` |

Fan IDs: `0x32`, `0x33`, `0x3B`, `0x3C`; sensor IDs: `0x01`, `0x06`.
`pprof_data` bỏ qua ID bằng 0, nên không dùng việc thiếu Custom trong cache
để suy luận một mình về hỗ trợ firmware. Kernel choices cũng không phải bằng
chứng profile giữ ổn định.

Metadata: [awcc-cached-metadata-2026-10-09.json](../research/results/awcc-cached-metadata-2026-10-09.json).

## 3. Phân tích bảng ACPI / AML offline

Đã sao chép DSDT, 15 SSDT tĩnh, SSDT16/17 động vào
`research/results/acpi-2026-10-09/`. Không sao chép bảng MSDM chứa license.
DSDT dài 378524 byte, checksum đúng; SHA-256:
`4a7c8c5a8adddca255bc414d0f92afe5db0d5f1b133644d710dfb2600900c9f4`.
Không tìm thấy bytes tên `WMAX`/`AMW1` trong các SSDT đã sao chép; đây là kiểm
tra tên, không phải tuyên bố đã decompile toàn bộ namespace.

Máy không có `iasl`; không cài mới. Đã viết parser nhỏ, strict/fail-closed dựa
trên [AML grammar ACPI 6.5](https://uefi.org/specs/ACPI/6.5/20_AML_Specification.html),
chỉ nhận đúng cấu trúc dispatch quan sát được. Nó xác minh checksum, Device
package, GUID `_WDG`, Method bounds/flags, toàn bộ preamble, nguồn selector,
If/Else bounds và nhánh mặc định. Bất kỳ cấu trúc chưa hiểu đều bị từ chối;
không phải một AML interpreter và không execute nhánh EC/SMM.

`AMW1._WDG` ánh xạ GUID AWCC tới `AX`, nghĩa là method `WMAX`. Method này có
ba argument, serialized, phạm vi DSDT `0x5A36B..0x5B05C`. Selector nhận từ
Arg1 qua `DMR1` tới `_T_0`. Các case đầy đủ:

```text
0D 0E 0F 13 14 15 17 1A 1C 20 21 22 23 24 80
```

Không có `25`. Default tại `0x5B051` có bytes `70 0C FF FF FF FF 60 A5`:
Store `0xFFFFFFFF` vào Local0, Break; sau dispatch Return Local0. Kết quả này
không phải chỉ tìm một byte/chuỗi không xuất hiện trong dump.

Tái chạy phân tích offline:

```bash
python3 research/analyze_awcc_aml.py research/results/acpi-2026-10-09/DSDT
```

Kết quả: [awcc-aml-dispatch-2026-10-09.json](../research/results/awcc-aml-dispatch-2026-10-09.json).

## 4. Candidate chỉ logging — build (trạng thái tại 5B)

Đã chuẩn bị `research/alienware-module-diagnostic/`. Chỉ wrapper
`awcc_wmi_command()` thêm rate-limited logging cho query/toggle Game Shift và
profile activation. Không thêm lệnh, không đổi error returns, DMI quirks,
profile mappings hay fan-control logic. Ba kiểm thử source đối chiếu phần
không sửa, số lần gọi firmware và error-return tail.

Build thành công với headers `7.0.0-38-generic`, compiler cùng version kernel.
Artefact unsigned; BTF bỏ qua vì thiếu matching `vmlinux`. Chi tiết và hash tại
[candidate README](../research/alienware-module-diagnostic/README.md).
Ở thời điểm hoàn thành 5B, không thay file trong `/lib/modules`, không chạy
depmod/initramfs, không unload hay load driver. Bản này phục vụ điều tra
rollback của profile thường, không phải lý do lặp lại Game Shift đã bị bác bỏ.
Lần nạp có kiểm soát duy nhất được ghi riêng ở tài liệu Phase 5C bên dưới.

## 5. Trạng thái cuối tại 5B, giới hạn và hướng tiếp theo

- Cả 75 tests đạt, gồm parser AML, kiểm tra logging-only và GTK fake clients.
- Loaded srcversion vẫn `28A4134FBF8432C66D7C668`; profile `balanced`;
  power-profiles-daemon active, kiểm tra lại bằng lệnh read-only.
- Không cài phần mềm hệ thống, sửa config, gọi raw WMI/SMM hay thử method mới,
  ghi PWM/boost hoặc reboot. Đọc profile/telemetry qua sysfs thông thường vẫn có
  thể khiến driver thực hiện WMI getter; đây là đường chỉ đọc đã có, không phải
  phép thử query `0x25` hay lệnh điều khiển mới.
- Chưa giải quyết manual takeover hoặc rollback của Quiet/Low-power/Performance
  **thường**. Phát hiện về `0x25` không giải thích thay cho các vấn đề đó.
- Bước có cơ sở tiếp theo: lần theo nhánh AML `0x15/operation 1`, mailbox,
  handler `CSMI` và trường `THMP` được getter sử dụng; hoặc kiểm chứng raw
  acceptance/rollback bằng logging candidate trong một phép thử được cấp quyền
  riêng. Chưa gọi bất kỳ handler đó trong giai đoạn này.

Điều khiển manual và các mode chưa kiểm chứng tiếp tục khóa. Không thêm fallback
bỏ qua query Game Shift để ép kích hoạt `0xAB` chỉ vì query bị từ chối.

## Bổ sung sau 5B: Phase 5C

Candidate đã được nạp một lần theo kế hoạch/permission riêng để quan sát Quiet
thường, sau đó khôi phục driver Ubuntu gốc, profile Balanced và PPD. Kết quả
thay đổi cách mô tả rollback: `0xA3` trả raw `0`, nhưng sau đó có một request
`0xA0` khác khi PPD inactive; logging v1 không attribution được caller. Chi
tiết và log nguyên gốc: [PHASE5C_ORDINARY_PROFILE_DIAGNOSTIC.md](PHASE5C_ORDINARY_PROFILE_DIAGNOSTIC.md).

Attribution v2/v3 sau đó nhận diện request Balanced thứ hai là root daemon
`awccd.service` (`python3 -m awccd.main`) khi PPD vẫn dừng, nên không còn xem
đây là firmware rollback. Xem
[PHASE5E_AWCCD_CONFLICT.md](PHASE5E_AWCCD_CONFLICT.md).
