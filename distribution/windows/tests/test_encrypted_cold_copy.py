from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from test_cold_restore_source import make_restore_source
from ticketbox_lifecycle import cli, cold_copy_cli
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import cold_copy_encryption as enc
from ticketbox_lifecycle.runtime import windows_cold_file as private_file
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.cold_archive import MANIFEST, verify_archive
from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource

_PASSWORD = b"test-only independent recovery secret"
_LIFECYCLE = Path(cli.__file__).resolve().parents[1]
windows = pytest.mark.skipif(os.name != "nt", reason="requires Windows private exclusive files")


@pytest.fixture
def archive(tmp_path):
    return make_restore_source(tmp_path)


@pytest.fixture(autouse=True)
def managed_roots(tmp_path, monkeypatch):
    roots = (tmp_path / "Program Data/Ticketbox", tmp_path / "Program Files/Ticketbox",
             tmp_path / "Common Files/Ticketbox")
    for name, path in zip(("ticketbox_program_data_root", "ticketbox_install_root", "ticketbox_control_root"), roots):
        monkeypatch.setattr(cold_copy_cli, name, Mock(return_value=path))
    return roots


@pytest.fixture(autouse=True)
def private_logs(caplog):
    caplog.set_level("DEBUG")
    yield
    for secret in (_PASSWORD.decode(), "wrong private key", "test-only-key", "old-credentials-stay-in-backup"):
        assert secret not in caplog.text


def _invoke(command, source, *args, capsys, monkeypatch, password=_PASSWORD):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(password + b"\r\n")))
    code = cli.main([command, "--source", str(source), *(str(arg) for arg in args)])
    out, err = capsys.readouterr()
    assert all(secret not in out + err for secret in (
        _PASSWORD.decode(), password.decode(), "fixture-only-secret", "old-credentials-stay-in-backup",
    ))
    assert not (err if code == 0 else out)
    result = json.loads(out if code == 0 else err)
    assert result["ok"] is (code == 0)
    if code:
        assert code == 2 and result.keys() == {"ok", "code", "message"}
    return result


def _wire(plaintext, password=_PASSWORD):
    """Independent v1 writer with fixed salt/prefix for wire-compatibility tests."""
    salt, prefix = bytes(range(16)), bytes(range(7))
    header = b"TBXCENC\x01" + salt + prefix + len(plaintext).to_bytes(8, "big")
    key = Argon2id(salt=salt, length=32, memory_cost=65536, iterations=3, lanes=4).derive(password)
    cipher = AESGCM(key)
    wire = bytearray(header + cipher.encrypt(prefix + bytes(5), b"", header))
    chunks = [plaintext[start:start + 1048576] for start in range(0, len(plaintext), 1048576)] or [b""]
    for index, chunk in enumerate(chunks, 1):
        position = index.to_bytes(4, "big") + bytes([index == len(chunks)])
        aad = hashlib.sha256(header).digest() + position
        wire.extend(cipher.encrypt(prefix + position, chunk, aad))
    return wire


@pytest.mark.parametrize("size", [0, 1, 1048575, 1048576, 1048577, 2097152])
def test_v1_interoperability_at_frame_boundaries(size):
    data = (b"0123456789abcdef" * (size // 16 + 1))[:size]
    wire = _wire(data)
    reader = enc._AuthenticatedReader(io.BytesIO(wire), _PASSWORD)
    with io.BufferedReader(reader) as stream:
        assert stream.read() == data
        stream.seek(size // 2)
        assert stream.read(37) == data[size // 2:size // 2 + 37]
    frames = enc._Frames.from_header(wire[:enc.HEADER.size], _PASSWORD)
    generated = io.BytesIO()
    assert enc._seal(io.BytesIO(data), generated, frames) == hashlib.sha256(data).hexdigest()
    assert generated.getvalue() == wire


@windows
def test_transferred_ciphertext_decrypts_in_clean_process_and_matches_restore(tmp_path, monkeypatch, capsys):
    receipt = b"original-receipt" * 140000
    source, request = make_restore_source(tmp_path, receipt=receipt)
    original = source.read_bytes()
    ciphertext = tmp_path / "copy.enc"
    encrypted = _invoke("encrypt-cold-copy", source, "--output", ciphertext, "--passphrase-stdin",
                        capsys=capsys, monkeypatch=monkeypatch)
    assert encrypted["ok"] and source.read_bytes() == original
    for secret in (_PASSWORD, b"old-credentials-stay-in-backup", b"fixture-only-secret", b"COLD_COPY.json"):
        assert secret not in ciphertext.read_bytes()
    other = tmp_path / "independent"
    other.mkdir()
    transfer = other / "download.enc"
    shutil.copyfile(ciphertext, transfer)
    assert hashlib.sha256(transfer.read_bytes()).digest() == hashlib.sha256(ciphertext.read_bytes()).digest()
    restored = other / "recovered.tbxcold"
    # Only the tool, the downloaded bytes and piped passphrase go into this process.
    # Block the native credential DLLs even if this Windows user has stored credentials.
    entry = """
import ctypes, sys
def forbid_old_credentials(event, args):
    if event == 'ctypes.dlopen' and any(dll in str(args[0]).lower() for dll in ('crypt32', 'credui', 'vaultcli')):
        raise AssertionError('old credential dependency')
    if event == 'ctypes.dlsym' and str(args[1]).startswith(('CredRead', 'CredEnumerate', 'CryptUnprotect')):
        raise AssertionError('old credential dependency')
sys.addaudithook(forbid_old_credentials)
sys.path.insert(0, sys.argv.pop(1))
from ticketbox_lifecycle.cli import main
raise SystemExit(main())
"""
    env = {"SystemRoot": os.environ["SystemRoot"], "SystemDrive": os.environ["SystemDrive"],
           "USERPROFILE": str(other), "TEMP": str(other), "TMP": str(other)}
    for command in ("verify-encrypted-cold-copy", "decrypt-cold-copy"):
        args = [sys.executable, "-I", "-B", "-c", entry, str(_LIFECYCLE), command, "--source", str(transfer),
                "--passphrase-stdin"]
        if command == "decrypt-cold-copy":
            args.extend(["--output", str(restored)])
        proc = subprocess.run(args, input=_PASSWORD + b"\n", cwd=other, env=env, capture_output=True, timeout=30)
        assert proc.returncode == 0 and proc.stderr == b""
        assert _PASSWORD not in proc.stdout and b"fixture-only-secret" not in proc.stdout
        assert json.loads(proc.stdout) == {**encrypted, "command": command}
    assert {p.name for p in other.iterdir()} == {transfer.name, restored.name}
    assert restored.read_bytes() == original
    assert encrypted["sha256"] == hashlib.sha256(original).hexdigest()
    with restored.open("rb") as stream:
        assert verify_archive(stream)["identity"]["dataset_id"] == encrypted["identity"]["dataset_id"]
        consumer = ColdRestoreSource(stream, encrypted["sha256"], request)
        assert consumer.backup_id == encrypted["backup_id"]
        consumer.extract_data(Path(request.data_root))
    assert (Path(request.data_root) / "app/uploads/receipt.jpg").read_bytes() == receipt


@pytest.fixture(scope="module")
def multiframe():
    return _wire(b"a" * 1048576 + b"b" * 1048576 + b"final")


@windows
@pytest.mark.parametrize("damage", ["wrong-key", "version", "salt", "nonce", "length", "header-tag",
                                    "ciphertext", "final-tag", "truncated", "missing-frame", "extension", "swapped"])
def test_damaged_ciphertext_never_publishes(tmp_path, monkeypatch, capsys, multiframe, damage):
    raw = bytearray(multiframe)
    start = enc.HEADER.size + enc.TAG
    stride = enc.CHUNK + enc.TAG
    offsets = {"version": 7, "salt": 8, "nonce": 24, "length": 38, "header-tag": start - 1,
               "ciphertext": start, "final-tag": -1}
    if damage in offsets:
        raw[offsets[damage]] ^= 1
    elif damage == "truncated":
        del raw[-1:]
    elif damage == "missing-frame":
        del raw[start:start + stride]
    elif damage == "extension":
        raw.extend(b"x")
    elif damage == "swapped":
        raw[start:start + 2 * stride] = raw[start + stride:start + 2 * stride] + raw[start:start + stride]
    source = tmp_path / "copy.enc"
    source.write_bytes(raw)
    for command in ("decrypt-cold-copy", "verify-encrypted-cold-copy"):
        args = ["--output", tmp_path / "partial.tbxcold"] if command == "decrypt-cold-copy" else []
        result = _invoke(command, source, *args, "--passphrase-stdin", capsys=capsys, monkeypatch=monkeypatch,
                         password=b"wrong private key" if damage == "wrong-key" else _PASSWORD)
        assert result["code"] == "cold_authentication_failed"
        assert list(tmp_path.iterdir()) == [source]


@windows
@pytest.mark.parametrize("damage", ["missing-manifest", "unknown-schema", "bad-member", "invalid-uuid"])
def test_rejects_invalid_inner_archive_before_encryption_and_after_authentication(
    archive, tmp_path, monkeypatch, capsys, damage,
):
    source, _ = archive
    invalid = tmp_path / "invalid.tbxcold"
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(invalid, "w") as new:
        for item in old.infolist():
            payload = old.read(item)
            if item.filename == MANIFEST:
                if damage == "missing-manifest":
                    continue
                if damage == "unknown-schema":
                    payload = json.dumps({**json.loads(payload), "schema": "unknown"}).encode()
                if damage == "invalid-uuid":
                    manifest = json.loads(payload)
                    manifest["identity"]["install_id"] = "invalid UUID"
                    payload = json.dumps(manifest).encode()
            if damage == "bad-member" and item.filename == "data/app/.env":
                payload += b"changed"
            new.writestr(item, payload)
    ciphertext = tmp_path / "new.enc"
    expected_codes = {"cold_identity_invalid"} if damage == "invalid-uuid" else {"cold_incomplete", "cold_corrupt"}
    with monkeypatch.context() as patch:
        patch.setattr(enc._Frames, "from_header", lambda *_: pytest.fail("invalid archive reached the KDF"))
        result = _invoke("encrypt-cold-copy", invalid, "--output", ciphertext, "--passphrase-stdin",
                         capsys=capsys, monkeypatch=patch)
    assert result["code"] in expected_codes and not ciphertext.exists()
    ciphertext.write_bytes(_wire(invalid.read_bytes()))
    out = tmp_path / "new.tbxcold"
    for command, args in (("decrypt-cold-copy", ["--output", out]), ("verify-encrypted-cold-copy", [])):
        result = _invoke(command, ciphertext, *args, "--passphrase-stdin", capsys=capsys, monkeypatch=monkeypatch)
        assert result["code"] in expected_codes and not out.exists()


@windows
def test_key_file_is_exact_independent_binary_and_outside_managed_roots(tmp_path, monkeypatch, capsys, managed_roots):
    source, _ = make_restore_source(tmp_path / "archives")
    ciphertext = tmp_path / "storage" / "copy.enc"
    ciphertext.parent.mkdir()
    material = b"test-only-key\x00\xff\n"
    for parent in (ciphertext.parent, ciphertext.parent / "sub", tmp_path, source.parent,
                   *managed_roots, managed_roots[0] / "machine/secrets", managed_roots[0] / "data/sub"):
        parent.mkdir(parents=True, exist_ok=True)
        key = parent / "separate.key"
        key.write_bytes(material)
        result = _invoke("encrypt-cold-copy", source, "--output", ciphertext, "--key-file", key,
                         capsys=capsys, monkeypatch=monkeypatch)
        assert result["code"] == "cold_key_location_invalid" and not ciphertext.exists()
    for target in (source, ciphertext):
        result = _invoke("encrypt-cold-copy", source, "--output", ciphertext, "--key-file", target,
                         capsys=capsys, monkeypatch=monkeypatch)
        assert result["code"] == "cold_key_location_invalid" and not ciphertext.exists()
    key = tmp_path / "keys" / "kept-separately.key"
    key.parent.mkdir()
    key.write_bytes(material)
    encrypted = _invoke("encrypt-cold-copy", source, "--output", ciphertext, "--key-file", key,
                        capsys=capsys, monkeypatch=monkeypatch)
    assert encrypted["ok"]
    assert _invoke("verify-encrypted-cold-copy", ciphertext, "--key-file", key,
                   capsys=capsys, monkeypatch=monkeypatch)["sha256"] == encrypted["sha256"]
    misplaced = key.with_name("plain.tbxcold")
    result = _invoke("decrypt-cold-copy", ciphertext, "--output", misplaced, "--key-file", key,
                     capsys=capsys, monkeypatch=monkeypatch)
    assert result["code"] == "cold_key_location_invalid" and not misplaced.exists()
    key.write_bytes(material.rstrip())
    assert _invoke("verify-encrypted-cold-copy", ciphertext, "--key-file", key,
                   capsys=capsys, monkeypatch=monkeypatch)["code"] == "cold_authentication_failed"


@windows
@pytest.mark.parametrize("command", ["encrypt-cold-copy", "decrypt-cold-copy"])
def test_existing_target_and_disk_full_preserve_source(archive, tmp_path, monkeypatch, capsys, command):
    source, _ = archive
    output = tmp_path / "copy.enc"
    if command == "decrypt-cold-copy":
        source, output = output, tmp_path / "result.tbxcold"
        source.write_bytes(_wire(archive[0].read_bytes()))
    before = source.read_bytes()
    output.write_bytes(b"pre-existing")
    def run():
        return _invoke(command, source, "--output", output, "--passphrase-stdin", capsys=capsys, monkeypatch=monkeypatch)
    assert run()["code"] == "cold_output_exists" and output.read_bytes() == b"pre-existing"
    output.unlink()
    monkeypatch.setattr(enc.shutil, "disk_usage", lambda parent: Mock(free=0))
    assert run()["code"] == "cold_space_insufficient" and not output.exists()
    monkeypatch.setattr(enc.shutil, "disk_usage", lambda parent: Mock(free=10**10))
    monkeypatch.setattr(private_file.os, "fsync", Mock(side_effect=OSError("disk full during flush")))
    assert run()["code"] == "cold_io_or_corrupt" and not output.exists()
    assert source.read_bytes() == before


@windows
def test_private_create_locks_and_process_termination(tmp_path):
    dest = tmp_path / "pending.tbxcold"
    with private_file.create_private_archive(dest, independent=True) as stream:
        stream.write(b"authenticated")
        with pytest.raises(PermissionError):
            dest.read_bytes()
    owner = native.current_process_user_sid()
    assert native.file_owner_sid(dest) == owner
    dacl = "D:P(A;;FA;;;SY)(A;;FA;;;BA)"
    if owner not in {native.SYSTEM_SID, native.ADMINISTRATORS_SID}:
        dacl += f"(A;;FA;;;{owner})"
    assert native._object_dacl_sddl(dest) == native._canonical_dacl_sddl(dacl)
    with pytest.raises(LifecycleError), private_file.create_private_archive(dest, independent=True):
        pytest.fail("exclusive creation admitted an existing target")
    with private_file.open_cold_source(dest), pytest.raises(PermissionError):
        dest.write_bytes(b"changed")
    assert dest.read_bytes() == b"authenticated"
    dest.unlink()
    entry = """
import os, sys
from pathlib import Path
from ticketbox_lifecycle.runtime import windows_cold_file as files
if sys.argv[2] == "security-check":
    files._require_handle_security = lambda *args: os._exit(16)
with files.create_private_archive(Path(sys.argv[1]), independent=True) as target:
    target.write(b'partial')
    target.flush()
    os._exit(17)
"""
    for stage, code in (("security-check", 16), ("write", 17)):
        proc = subprocess.run([sys.executable, "-B", "-c", entry, str(dest), stage],
                              env={**os.environ, "PYTHONPATH": str(_LIFECYCLE)})
        assert proc.returncode == code and not dest.exists()


def test_invalid_secret_arguments_do_not_echo_values(capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["verify-encrypted-cold-copy", "--source", "copy.enc", "--passphrase", _PASSWORD.decode()])
    assert stopped.value.code == 2
    out, err = capsys.readouterr()
    assert not out and _PASSWORD.decode() not in err and json.loads(err)["code"] == "cold_arguments_invalid"


@windows
@pytest.mark.parametrize("command,suffix", [("encrypt-cold-copy", ".enc"), ("decrypt-cold-copy", ".tbxcold")])
def test_managed_output_is_rejected_before_io(command, suffix, tmp_path, monkeypatch, capsys, managed_roots):
    source = tmp_path / ("copy.tbxcold" if command == "encrypt-cold-copy" else "copy.enc")
    for root in (*managed_roots, managed_roots[0] / "data", managed_roots[0] / "machine"):
        root.mkdir(parents=True)
        output = root / ("new" + suffix)
        result = _invoke(command, source, "--output", output, "--passphrase-stdin", capsys=capsys, monkeypatch=monkeypatch)
        assert result["code"] == "cold_output_inside_source" and not output.exists()


@windows
def test_short_and_long_managed_paths_are_equivalent(tmp_path, monkeypatch, capsys, managed_roots):
    root = managed_roots[0]
    root.mkdir(parents=True)
    buf = ctypes.create_unicode_buffer(32768)
    assert 0 < ctypes.windll.kernel32.GetShortPathNameW(str(root), buf, len(buf)) < len(buf)
    short = Path(buf.value)
    if short == root:
        pytest.skip("fixture volume does not generate 8.3 aliases")
    ciphertext = tmp_path / "copies" / "backup.enc"
    for configured, selected in ((short, root), (root, short)):
        monkeypatch.setattr(cold_copy_cli, "ticketbox_program_data_root", lambda: configured)
        key = selected / "key.bin"
        result = _invoke("verify-encrypted-cold-copy", ciphertext, "--key-file", key, capsys=capsys, monkeypatch=monkeypatch)
        assert result["code"] == "cold_key_location_invalid"
        output = selected / "new.tbxcold"
        result = _invoke("decrypt-cold-copy", ciphertext, "--output", output, "--passphrase-stdin",
                         capsys=capsys, monkeypatch=monkeypatch)
        assert result["code"] == "cold_output_inside_source" and not output.exists()


def test_ciphertext_output_suffix_is_distinct(tmp_path, capsys, monkeypatch):
    output = tmp_path / "ciphertext.TbXcOlD"
    result = _invoke("encrypt-cold-copy", tmp_path / "input.tbxcold", "--output", output, "--passphrase-stdin",
                     capsys=capsys, monkeypatch=monkeypatch)
    assert result["code"] == "cold_path_invalid" and not output.exists()


@pytest.mark.parametrize("raw", [
    _PASSWORD + b"\nsecond", _PASSWORD + b"\r\n\r\n", _PASSWORD + b"\r",
    b"\xff\xfe" + _PASSWORD, "密钥".encode("gbk"), "test-only-key".encode("utf-16le"),
])
def test_stdin_requires_one_utf8_line(raw, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    assert cli.main(["verify-encrypted-cold-copy", "--source", str(tmp_path / "a.enc"), "--passphrase-stdin"]) == 2
    out, err = capsys.readouterr()
    assert not out and json.loads(err)["code"] == "cold_key_invalid" and _PASSWORD.decode() not in err


@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_stdin_preserves_utf8_at_limit(ending, tmp_path, monkeypatch):
    secret = "é".encode() * 32768
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(secret + ending)))
    args = Mock(key_file=None, passphrase_stdin=True)
    assert cold_copy_cli._read_secret(args, (tmp_path / "source",), ()) == secret


@pytest.mark.parametrize("options", [[], ["--passphrase-stdin"]])
def test_windowless_private_input(options, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", None)
    assert cli.main(["verify-encrypted-cold-copy", "--source", str(tmp_path / "a.enc"), *options]) == 2
    out, err = capsys.readouterr()
    assert not out and json.loads(err)["code"] == "cold_private_input_required"


def test_unexpected_private_input_failure_is_redacted(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cold_copy_cli, "_read_secret", Mock(side_effect=MemoryError(_PASSWORD.decode())))
    result = _invoke("verify-encrypted-cold-copy", tmp_path / "a.enc", "--passphrase-stdin",
                     capsys=capsys, monkeypatch=monkeypatch)
    assert result["code"] == "cold_io_or_corrupt"


@pytest.mark.parametrize("owner", [native.SYSTEM_SID, native.ADMINISTRATORS_SID])
def test_privileged_owner_has_exactly_one_ace_per_principal(owner, monkeypatch):
    monkeypatch.setattr(native, "current_process_user_sid", lambda: owner)
    assert private_file._archive_sddl(True) == f"O:{owner}D:P(A;;FA;;;SY)(A;;FA;;;BA)"


@windows
@pytest.mark.parametrize("kind,attributes,query_ok", [
    (2, 0, True), (1, stat.FILE_ATTRIBUTE_DIRECTORY, True), (1, stat.FILE_ATTRIBUTE_REPARSE_POINT, True),
    (1, 0, False),
])
def test_source_rejects_unusable_opened_handle(kind, attributes, query_ok, tmp_path, monkeypatch):
    kernel = Mock()
    kernel.CreateFileW.return_value = 4321
    kernel.GetFileType.return_value = kind
    def info(handle, info_class, pointer, size):
        assert handle == 4321 and info_class == 9 and size == ctypes.sizeof(private_file._FileAttributeTagInfo)
        ctypes.cast(pointer, ctypes.POINTER(private_file._FileAttributeTagInfo)).contents.attributes = attributes
        return query_ok
    kernel.GetFileInformationByHandleEx.side_effect = info
    monkeypatch.setattr(private_file, "_file_api", lambda: kernel)
    with pytest.raises(LifecycleError) as rejected, private_file.open_cold_source(tmp_path / "input"):
        pytest.fail("exposed an unverified source")
    assert rejected.value.code == "cold_source_unavailable"
    kernel.GetFileType.assert_called_once_with(4321)
    kernel.CloseHandle.assert_called_once_with(4321)


@windows
@pytest.mark.parametrize("mismatch", ["owner", "dacl"])
def test_private_output_rejects_handle_security_mismatch(mismatch, tmp_path, monkeypatch):
    dest = tmp_path / "new.enc"
    inspect = private_file._require_handle_security
    def check(kernel, advapi, handle, expected):
        # Substitute only the expected security. GetSecurityInfo still reads the actual exclusive handle.
        policy = private_file._archive_sddl(True)
        if mismatch == "owner":
            policy = "O:WD" + policy[policy.index("D:"):]
        else:
            policy += "(A;;FR;;;WD)"
        other = ctypes.c_void_p()
        assert advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(policy, 1, ctypes.byref(other), None)
        try:
            inspect(kernel, advapi, handle, other)
        finally:
            kernel.LocalFree(other)
    monkeypatch.setattr(private_file, "_require_handle_security", check)
    with pytest.raises(LifecycleError) as rejected, private_file.create_private_archive(dest, independent=True):
        pytest.fail("exposed a file with unverified owner or DACL")
    assert rejected.value.code == "cold_output_security" and not dest.exists()


@windows
def test_hidden_prompt_confirmation_and_fresh_salt_and_nonce(archive, tmp_path, monkeypatch, capsys):
    src, _ = archive
    monkeypatch.setattr(sys, "stdin", Mock(isatty=lambda: True))
    hidden = Mock(side_effect=[_PASSWORD.decode(), "typo", *([_PASSWORD.decode()] * 4)])
    monkeypatch.setattr(cold_copy_cli.getpass, "getpass", hidden)
    def run(dest, *extra):
        return cli.main(["encrypt-cold-copy", "--source", str(src), "--output", str(dest), *extra])
    a, b = tmp_path / "first.enc", tmp_path / "second.enc"
    assert run(a, "--passphrase-stdin") == 2
    assert json.loads(capsys.readouterr().err)["code"] == "cold_private_input_required"
    assert run(a) == 2 and not a.exists()
    assert json.loads(capsys.readouterr().err)["code"] == "cold_passphrase_mismatch"
    assert run(a) == run(b) == 0
    assert hidden.call_count == 6 and _PASSWORD.decode() not in capsys.readouterr().out
    _, salt_a, nonce_a, _ = enc.HEADER.unpack(a.read_bytes()[:enc.HEADER.size])
    _, salt_b, nonce_b, _ = enc.HEADER.unpack(b.read_bytes()[:enc.HEADER.size])
    assert salt_a != salt_b and nonce_a != nonce_b
