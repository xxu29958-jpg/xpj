"""Windows user-root and UAC result-channel security contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend_manager import elevation, windows_user_security
from backend_manager.__main__ import main
from backend_manager.elevation import validate_helper_result_channel
from backend_manager.helper_channel import channel_file_identity, open_exclusive_channel
from backend_manager.runtime import RuntimeControlError


def test_helper_accepts_redirected_local_app_data_root_without_using_elevated_profile(monkeypatch) -> None:
    nonce = "n" * 43
    root = Path(r"C:\RedirectedProfiles\caller\LocalState\Ticketbox\helper-results")
    path = root / f"{nonce}.json"
    monkeypatch.setattr(
        windows_user_security,
        "local_app_data",
        lambda: (_ for _ in ()).throw(AssertionError("helper consulted elevated account LocalAppData")),
    )
    monkeypatch.setattr(windows_user_security, "is_reparse_point", lambda _path: False)

    windows_user_security.assert_helper_channel_path(path, root, nonce)  # noqa: SLF001 - adversarial path contract


@pytest.mark.parametrize(
    ("path", "root"),
    [
        (
            Path(r"C:\Redirected\Ticketbox\other") / ("n" * 43 + ".json"),
            Path(r"C:\Redirected\Ticketbox\helper-results"),
        ),
        (
            Path(r"C:\Redirected\Ticketbox\helper-results\wrong.json"),
            Path(r"C:\Redirected\Ticketbox\helper-results"),
        ),
        (
            Path(r"\\server\share\Ticketbox\helper-results") / ("n" * 43 + ".json"),
            Path(r"\\server\share\Ticketbox\helper-results"),
        ),
    ],
)
def test_helper_rejects_noncanonical_result_paths(monkeypatch, path: Path, root: Path) -> None:
    monkeypatch.setattr(windows_user_security, "is_reparse_point", lambda _path: False)

    with pytest.raises(RuntimeControlError):
        windows_user_security.assert_helper_channel_path(path, root, "n" * 43)  # noqa: SLF001 - adversarial path contract


def test_helper_rejects_reparse_ancestor_before_read(monkeypatch) -> None:
    nonce = "n" * 43
    root = Path(r"C:\Redirected\Ticketbox\helper-results")
    path = root / f"{nonce}.json"
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(windows_user_security, "is_reparse_point", lambda candidate: candidate.name == "Ticketbox")

    with pytest.raises(RuntimeControlError, match="重解析点"):
        windows_user_security.assert_helper_channel_path(path, root, nonce)  # noqa: SLF001 - adversarial path contract


def test_helper_rejects_pending_json_with_extra_fields(monkeypatch, tmp_path: Path) -> None:
    nonce = "n" * 43
    owner_sid = "S-1-5-21-1000"
    path = tmp_path / f"{nonce}.json"
    path.touch()
    with open_exclusive_channel(path) as stream:
        file_identity = channel_file_identity(stream)
    path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-manager-helper-result-v2",
                "root": str(tmp_path),
                "nonce": nonce,
                "action": "inventory",
                "state": "pending",
                "owner_sid": owner_sid,
                "file_identity": file_identity,
                "target": r"C:\Windows\System32\drivers\etc\hosts",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(windows_user_security, "assert_helper_channel_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(elevation, "validate_exact_file_security", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeControlError, match="精确契约"):
        validate_helper_result_channel(path, tmp_path, nonce, "inventory", owner_sid, file_identity)


def test_helper_binds_pending_payload_and_acl_to_exact_redirected_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "redirected-local-state" / "Ticketbox" / "helper-results"
    root.mkdir(parents=True)
    nonce = "n" * 43
    owner_sid = "S-1-5-21-1000"
    path = root / f"{nonce}.json"
    path.touch()
    with open_exclusive_channel(path) as stream:
        file_identity = channel_file_identity(stream)
    path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-manager-helper-result-v2",
                "root": str(root),
                "nonce": nonce,
                "action": "inventory",
                "state": "pending",
                "owner_sid": owner_sid,
                "file_identity": file_identity,
            },
        ),
        encoding="utf-8",
    )
    acl_checks: list[tuple[Path, bool]] = []
    monkeypatch.setattr(windows_user_security, "assert_helper_channel_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        elevation,
        "validate_exact_file_security",
        lambda candidate, _sid, *, directory=False: acl_checks.append((candidate, directory)),
    )

    validate_helper_result_channel(path, root, nonce, "inventory", owner_sid, file_identity)

    assert acl_checks == [(root, True), (path, False)]


def test_helper_rejects_payload_bound_to_a_different_root(monkeypatch, tmp_path: Path) -> None:
    nonce = "n" * 43
    owner_sid = "S-1-5-21-1000"
    path = tmp_path / f"{nonce}.json"
    path.touch()
    with open_exclusive_channel(path) as stream:
        file_identity = channel_file_identity(stream)
    path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-manager-helper-result-v2",
                "root": str(tmp_path / "attacker-selected-root"),
                "nonce": nonce,
                "action": "inventory",
                "state": "pending",
                "owner_sid": owner_sid,
                "file_identity": file_identity,
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(windows_user_security, "assert_helper_channel_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(elevation, "validate_exact_file_security", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeControlError, match="schema 或 action 不匹配"):
        validate_helper_result_channel(path, tmp_path, nonce, "inventory", owner_sid, file_identity)


@pytest.mark.skipif(os.name != "nt", reason="Windows hard-link semantics required")
def test_helper_rejects_hardlinked_result_file(monkeypatch, tmp_path: Path) -> None:
    nonce = "n" * 43
    owner_sid = "S-1-5-21-1000"
    path = tmp_path / f"{nonce}.json"
    path.touch()
    with open_exclusive_channel(path) as stream:
        file_identity = channel_file_identity(stream)
    path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-manager-helper-result-v2",
                "root": str(tmp_path),
                "nonce": nonce,
                "action": "inventory",
                "state": "pending",
                "owner_sid": owner_sid,
                "file_identity": file_identity,
            },
        ),
        encoding="utf-8",
    )
    os.link(path, tmp_path / "second-link.json")
    monkeypatch.setattr(windows_user_security, "assert_helper_channel_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(elevation, "validate_exact_file_security", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeControlError, match="单链接"):
        validate_helper_result_channel(path, tmp_path, nonce, "inventory", owner_sid, file_identity)


def test_helper_rejects_replaced_file_even_with_same_nonce_action_and_acl(monkeypatch, tmp_path: Path) -> None:
    nonce = "n" * 43
    owner_sid = "S-1-5-21-1000"
    path = tmp_path / f"{nonce}.json"
    path.touch()
    with open_exclusive_channel(path) as stream:
        original_identity = channel_file_identity(stream)
    replacement = tmp_path / "replacement.json"
    replacement.write_text(
        json.dumps(
            {
                "schema": "ticketbox-manager-helper-result-v2",
                "root": str(tmp_path),
                "nonce": nonce,
                "action": "inventory",
                "state": "pending",
                "owner_sid": owner_sid,
                "file_identity": original_identity,
            },
        ),
        encoding="utf-8",
    )
    path.unlink()
    replacement.rename(path)
    monkeypatch.setattr(windows_user_security, "assert_helper_channel_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(elevation, "validate_exact_file_security", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeControlError, match="文件身份已变化"):
        validate_helper_result_channel(path, tmp_path, nonce, "inventory", owner_sid, original_identity)


def test_helper_rejects_owner_or_acl_failure_before_maintenance_action(monkeypatch, tmp_path: Path) -> None:
    touched = False

    def reject(*_args) -> None:
        raise RuntimeControlError("bad owner")

    def load(**_kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("service config loaded before result channel validation")

    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: True)
    monkeypatch.setattr("backend_manager.__main__.validate_helper_result_channel", reject)
    monkeypatch.setattr("backend_manager.__main__.load_config", load)

    exit_code = main(
        [
            "--elevated-service-action",
            "inventory",
            "--helper-result-path",
            str(tmp_path / "result.json"),
            "--helper-result-root",
            str(tmp_path),
            "--helper-result-nonce",
            "n" * 43,
            "--helper-channel-owner-sid",
            "S-1-5-21-1000",
            "--helper-channel-file-id",
            "1:2",
        ],
    )

    assert exit_code != 0
    assert touched is False
