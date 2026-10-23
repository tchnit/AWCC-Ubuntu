# Giai đoạn 2 — kết quả kiểm tra trên máy thật

Ngày kiểm tra: 2026-10-09.

## Thành phần đã cài

```text
/usr/libexec/awcc-profile-helper
/usr/lib/alienware-control-center/awcc_linux/
/usr/share/polkit-1/actions/io.github.awcclinux.ControlCenter.policy
```

Các file được xác nhận là `root:root`; helper có mode `0755`, source/policy có
mode `0644`. Checksum của helper và policy đã cài khớp bản trong workspace.
PolicyKit đã nhận action `io.github.awcclinux.ControlCenter.set-profile`.

Không cài package mới, không thay kernel/module và không reboot.

## Test `balanced → quiet`

Helper ghi `quiet`, sau đó đọc lại ở ba thời điểm:

```json
{
  "requested": "quiet",
  "previous": "balanced",
  "observed": ["quiet", "quiet", "balanced"],
  "final": "balanced",
  "persistent": false
}
```

Kết luận tại thời điểm test: `quiet` không persistent. Helper đã phát hiện
rollback thay vì báo thành công giả. Điều tra giai đoạn 4 sau đó phát hiện
`power-profiles-daemon` đang giữ `ActiveProfile=balanced` và không công bố
`quiet`/`custom`; vì vậy không còn đủ cơ sở để quy rollback này cho firmware.

## Test `balanced`

```json
{
  "requested": "balanced",
  "previous": "balanced",
  "observed": ["balanced", "balanced", "balanced"],
  "final": "balanced",
  "persistent": true
}
```

Trạng thái cuối đã xác nhận:

- profile `balanced`;
- CPU khoảng 45–46 °C, GPU khoảng 40 °C;
- `pwm1_enable` … `pwm4_enable` vẫn là `2`;
- sau khi ghi profile, RPM tăng dần trong 8 giây dù nhiệt độ thấp:
  fan1 `5700 → 6200`, fan2 `6800`, fan3 `5700 → 6400`, fan4 `5000` RPM.

Quan sát RPM phù hợp với báo cáo cũ rằng việc đổi thermal profile có thể khiến
firmware nạp lại trạng thái quạt rồi tăng RPM. Nó không chứng minh profile là
nguyên nhân gốc của hành vi quạt cao.

## Kết luận giai đoạn

- privilege boundary và PolicyKit hoạt động;
- helper phân biệt được write thành công tạm thời với profile persistent;
- `quiet` vẫn bị rollback trong môi trường hiện tại; cần phối hợp hoặc cô lập
  `power-profiles-daemon` trước khi đánh giá firmware;
- profile control không giải quyết manual fan control; capability này tiếp tục
  bị khóa trong UI.

## Hiệu chỉnh sau Phase 5E

Tại thời điểm Phase 2, log chưa attribution được mọi writer platform-profile.
Phase 5E sau đó nhận diện một root daemon bên ngoài, `awccd.service`, ép
Balanced ở mỗi tick. Không có log process của lần test 2026-10-09 để kết luận
daemon này có chạy đúng lúc Phase 2 hay không. Vì vậy kết luận lịch sử chỉ còn
nghĩa “Quiet không persistent trong môi trường lúc đó”; không quy nguyên nhân
cho firmware hoặc PPD cho tới khi daemon cạnh tranh được cô lập. Xem
[PHASE5E_AWCCD_CONFLICT.md](PHASE5E_AWCCD_CONFLICT.md).
