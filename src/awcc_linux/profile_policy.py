from __future__ import annotations


def profile_block_reason(
    model: str | None,
    bios_version: str | None,
    profile: str,
    *,
    verified_ppd_route: bool = False,
) -> str | None:
    """Return a hardware-evidence-based reason why a profile must stay disabled.

    Low Power/Performance are verified only through PPD on the x17 R1.
    Phase 5K verified Balanced+ and Custom as thermal profiles, not fan control.
    """

    if profile == "custom":
        if model == "Alienware x17 R1" and bios_version == "1.27.0":
            return None
        return (
            "Custom chưa được kiểm chứng trên model/BIOS này; driver quảng bá "
            "profile đó không đồng nghĩa với hỗ trợ firmware."
        )

    if (
        model == "Alienware x17 R1"
        and bios_version == "1.27.0"
        and profile in {"low-power", "performance"}
    ):
        if verified_ppd_route:
            return None
        if profile == "performance":
            return (
                "Performance chỉ được xác minh qua power-profiles-daemon; "
                "fallback privileged helper vẫn khóa."
            )
        return (
            "Low Power chỉ được xác minh qua power-profiles-daemon; "
            "fallback privileged helper vẫn khóa."
        )

    return None
