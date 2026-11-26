"""Exercise the frozen C1 commands with a synthetic retention archive."""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lifecycle"))
from ticketbox_lifecycle.runtime.cold_archive import COMPONENTS, _REQUIRED_FILES, write_archive


def probe(executable: Path, directory: Path) -> dict:
    roots = {name: directory / "inputs" / name for name in COMPONENTS}
    for root in roots.values():
        root.mkdir(parents=True)
    for name in _REQUIRED_FILES:
        member = directory / "inputs" / name
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(b"synthetic build probe")
    identity = {"dataset_id": str(uuid4()), "install_id": str(uuid4()), "restore_epoch": 0}
    copies = directory / "archives"
    copies.mkdir()
    source = copies / "input.tbxcold"
    with source.open("x+b") as stream:
        write_archive(stream, roots, identity, lambda: None)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    keys = directory / "keys"
    keys.mkdir()
    key_file = keys / "recovery.key"
    key_file.write_bytes(secrets.token_bytes(32))
    passphrase = secrets.token_urlsafe(32).encode("ascii") + b"\n"
    commands = _round_trip(executable, source, expected, identity, "passphrase", ["--passphrase-stdin"], passphrase)
    key_file_commands = _round_trip(executable, source, expected, identity, "key-file", ["--key-file", str(key_file)], b"")
    return {"contract": "ticketbox-encrypted-cold-copy-roundtrip-v1", "commands": commands,
            "key_file_commands": key_file_commands, "verified": True}


def _round_trip(executable, source, expected, identity, name, key_args, private_input):
    encrypted = source.with_name(f"{name}.enc")
    decrypted = source.with_name(f"{name}.tbxcold")
    commands = []
    for command, path, output in (
        ("encrypt-cold-copy", source, encrypted),
        ("verify-encrypted-cold-copy", encrypted, None),
        ("decrypt-cold-copy", encrypted, decrypted),
    ):
        args = [str(executable), command, "--source", str(path), *key_args]
        if output is not None:
            args.extend(["--output", str(output)])
        run = subprocess.run(args, input=private_input, capture_output=True, timeout=60, check=True)
        result = json.loads(run.stdout)
        if (run.stderr or result.get("ok") is not True or result.get("command") != command
                or result.get("sha256") != expected or result.get("identity") != identity):
            raise ValueError(f"frozen {command} returned an invalid recovery point")
        commands.append(command)
    if decrypted.read_bytes() != source.read_bytes():
        raise ValueError("frozen C1 plaintext readback differs")
    return commands


if __name__ == "__main__":
    with TemporaryDirectory(dir=sys.argv[2]) as directory:
        print(json.dumps(probe(Path(sys.argv[1]), Path(directory))))
