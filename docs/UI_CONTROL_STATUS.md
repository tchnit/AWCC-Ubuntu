# Control states — 2026-10-09

Previously, `set_sensitive(False)` was used both for the selected option and
for unavailable actions. The UI also relied on tooltips to explain most gates,
making "already selected" visually indistinguishable from "cannot work".

Each control now has a card with a state icon, explicit label and visible reason.
Only the hardware action button is disabled; explanatory text is outside that
button and retains normal contrast. The selected card uses an accent border and
checkmark, with an enabled selected button. Clicking it again does not send a
hardware command; selected preset clicks also avoid redundant settings writes.

States:

- **Đang dùng / Đang chọn**: current profile / selected preset, not a failure.
- **Bị khóa**: existing hardware-policy or daemon-routing gate; reason shown inline.
- **Chưa sẵn sàng**: no usable daemon/helper, distinct from firmware rejection.
- **Đang xử lý**: temporary lock during an outstanding profile request.

The active profile and preferred preset remain separate. In particular, Auto can
be selected while the hardware profile is Balanced. All original profile policy
and fan-actuator gates are retained. Callback checks also reject blocked profile
requests even if invoked directly; G-Mode, SMM, PWM and boost writes are unchanged.
Fan-mode/curve preview controls described by the original 5B review were later
removed from the desktop UI pending a redesign.

`control_status.py` is presentation-only. No installation, driver reload, service
restart, persistent system-config change or new hardware experiment was performed.

Verification: all 62 tests passed, including nine GTK integration tests with
an actual display. Unit and GTK integration tests cover selected clicks, hardware
policy, daemon-unmanaged profiles, missing transports, temporary busy state and
profile/preset behavior. The original GTK render images are retained as
historical evidence in `research/results/ui-*-status.png`; no hardware clients
were invoked.
