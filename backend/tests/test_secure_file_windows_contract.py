"""Pure contract tests for C07 protected-file Windows SDDL."""

from app.services.secure_file_windows import (
    ADMINISTRATORS_SID,
    SYSTEM_SID,
    _protected_sddl,
)


def test_protected_sddl_deduplicates_system_process_sid() -> None:
    sddl = _protected_sddl(SYSTEM_SID)

    assert sddl.count(f"(A;;FA;;;{SYSTEM_SID})") == 1
    assert sddl.count(f"(A;;FA;;;{ADMINISTRATORS_SID})") == 1
    assert sddl.count("(A;;FA;;;") == 2


def test_protected_sddl_keeps_three_distinct_trustees_for_service_user() -> None:
    service_sid = "S-1-5-21-1-2-3-1001"
    sddl = _protected_sddl(service_sid)

    assert sddl.count(f"(A;;FA;;;{service_sid})") == 1
    assert sddl.count(f"(A;;FA;;;{SYSTEM_SID})") == 1
    assert sddl.count(f"(A;;FA;;;{ADMINISTRATORS_SID})") == 1
    assert sddl.count("(A;;FA;;;") == 3
