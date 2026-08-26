from __future__ import annotations

from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
from ticketbox_lifecycle.runtime.command import CompletedCommand

_BOOTSTRAP_SID = "S-1-5-21-9-9-9-1003"
_SERVICE_SID = "S-1-5-80-111-222-333-444-555"


class RecordingRunner:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    def run(self, argv, **_kwargs) -> CompletedCommand:
        recorded = tuple(str(part) for part in argv)
        self.events.append(("command", recorded))
        return CompletedCommand(recorded, 0, "", "")


def _root_sddl(principal: str) -> str:
    return (
        "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        f"(A;OICI;FA;;;{principal})"
        "(A;;RC;;;OW)(A;OICIIO;RC;;;OW)"
    )


def test_prepare_initdb_publishes_one_protected_root_dacl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pgdata = tmp_path / "pgdata"
    published: list[tuple[Path, str, str]] = []
    monkeypatch.setattr(
        pgdata_security,
        "apply_protected_dacl",
        lambda path, sddl, *, code: published.append((path, sddl, code)),
        raising=False,
    )

    pgdata_security.prepare_initdb_directory(
        pgdata,
        bootstrap_sid=_BOOTSTRAP_SID,
    )

    assert published == [
        (
            pgdata,
            _root_sddl(_BOOTSTRAP_SID).replace("D:PAI", "D:P"),
            "initdb_directory_acl_failed",
        )
    ]


def test_seal_sets_owner_before_publishing_the_final_root_dacl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    events: list[tuple[object, ...]] = []
    runner = RecordingRunner(events)
    monkeypatch.setattr(
        pgdata_security,
        "apply_protected_dacl",
        lambda path, sddl, *, code: events.append(("dacl", path, sddl, code)),
        raising=False,
    )
    monkeypatch.setattr(
        pgdata_security,
        "_require_exact_tree",
        lambda path, *, service_sid: events.append(("verify", path, service_sid)),
    )

    pgdata_security.seal_for_service(runner, pgdata, service_sid=_SERVICE_SID)

    assert events == [
        (
            "command",
            (
                "icacls",
                str(pgdata),
                "/setowner",
                "*S-1-5-32-544",
                "/T",
                "/C",
                "/L",
            ),
        ),
        (
            "dacl",
            pgdata,
            _root_sddl(_SERVICE_SID).replace("D:PAI", "D:P"),
            "pgdata_acl_failed",
        ),
        ("verify", pgdata, _SERVICE_SID),
    ]


@pytest.mark.parametrize(
    ("sddl", "shape"),
    [
        (_root_sddl(_SERVICE_SID), "root"),
        (
            "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)"
            f"(A;OICIID;FA;;;{_SERVICE_SID})(A;OICIID;RC;;;OW)",
            "directory",
        ),
        (
            f"D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;{_SERVICE_SID})(A;ID;RC;;;OW)",
            "file",
        ),
    ],
)
def test_pgdata_policy_accepts_exact_root_and_inherited_shapes(
    sddl: str,
    shape: pgdata_security.AclShape,
) -> None:
    pgdata_security._require_policy_dacl(
        sddl,
        service_sid=_SERVICE_SID,
        name="object",
        shape=shape,
    )


@pytest.mark.parametrize(
    ("sddl", "shape"),
    [
        (
            "D:PAI(A;IO;RC;;;OW)"
            f"(A;OICI;FA;;;{_SERVICE_SID})(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)",
            "root",
        ),
        (
            "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
            f"(A;OICI;FA;;;{_SERVICE_SID})(A;OICIIO;RC;;;OW)",
            "root",
        ),
        (
            "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
            f"(A;OICI;FA;;;{_SERVICE_SID})(A;;RC;;;OW)",
            "root",
        ),
        (
            "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)"
            f"(A;OICIID;FA;;;{_SERVICE_SID})(A;OICIIOID;RC;;;OW)",
            "directory",
        ),
        (
            "D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)"
            f"(A;ID;FA;;;{_SERVICE_SID})(A;IOID;RC;;;OW)",
            "file",
        ),
    ],
)
def test_pgdata_policy_rejects_inert_or_incomplete_owner_rights(
    sddl: str,
    shape: pgdata_security.AclShape,
) -> None:
    with pytest.raises(LifecycleError, match="non-service ACL"):
        pgdata_security._require_policy_dacl(
            sddl,
            service_sid=_SERVICE_SID,
            name="object",
            shape=shape,
        )
