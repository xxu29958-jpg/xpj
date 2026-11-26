"""Explicit administrator cold retention; the installed sources are read only."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import warnings
from pathlib import Path

from ticketbox_lifecycle.domain.cold_copy import create_cold_copy
from ticketbox_lifecycle.domain.encrypted_cold_copy import require_separate_key
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.windows_cold_copy import WindowsColdCopy, verify_cold_copy
from ticketbox_lifecycle.runtime.windows_cold_file import open_cold_source
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_control_root,
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components

_KEY_LIMIT = 65536
_ENCRYPTED_COMMANDS = ("encrypt-cold-copy", "decrypt-cold-copy", "verify-encrypted-cold-copy")


class _PrivateArguments(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse normally echoes unrecognized argv, which may contain a mistyped passphrase.
        self.exit(2, '{"ok":false,"code":"cold_arguments_invalid","message":"Invalid arguments. See command --help."}\n')


def _local_path(value: str) -> Path:
    path = Path(value)
    if (not path.is_absolute() or path.drive.startswith("\\\\") or ":" in str(path)[len(path.drive):]
            or any(part == ".." or part.endswith((" ", ".")) or Path(part).is_reserved() for part in path.parts)):
        raise LifecycleError("cold_path_invalid", "select an absolute local file")
    reject_reparse_components(path)
    return path.resolve()


def _read_secret(args: argparse.Namespace, targets: tuple[Path, ...], managed_roots: tuple[Path, ...]) -> bytes:
    if args.key_file is not None:
        key = _local_path(args.key_file)
        require_separate_key(key, targets, managed_roots)
        with open_cold_source(key) as stream:
            if os.fstat(stream.fileno()).st_nlink != 1:
                raise LifecycleError("cold_key_location_invalid", "select a separate key file with a single link")
            secret = stream.read(_KEY_LIMIT + 1)
    elif sys.stdin is None:
        raise LifecycleError("cold_private_input_required", "a private input stream is required")
    elif args.passphrase_stdin:
        if sys.stdin.isatty():
            raise LifecycleError("cold_private_input_required", "redirect a private stream or use the hidden prompt")
        raw = sys.stdin.buffer.read(_KEY_LIMIT + 3)
        secret = raw.removesuffix(b"\r\n") if raw.endswith(b"\r\n") else raw.removesuffix(b"\n")
        if b"\r" in secret or b"\n" in secret or b"\0" in secret:
            raise LifecycleError("cold_key_invalid", "supply one UTF-8 passphrase line")
        try:
            secret.decode("utf-8")
        except UnicodeDecodeError:
            raise LifecycleError("cold_key_invalid", "supply one UTF-8 passphrase line") from None
    else:
        if not sys.stdin.isatty():
            raise LifecycleError("cold_private_input_required", "use a private terminal, redirected stdin or separate key")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            secret = getpass.getpass("Recovery passphrase: ").encode("utf-8")
            if args.command == "encrypt-cold-copy" and secret != getpass.getpass("Confirm passphrase: ").encode("utf-8"):
                raise LifecycleError("cold_passphrase_mismatch", "passphrase confirmation did not match")
    if not 0 < len(secret) <= _KEY_LIMIT:
        raise LifecycleError("cold_key_invalid", "supply 1 to 65536 bytes of recovery key material")
    return secret


def _validate_encrypted_paths(
    command: str,
    source: Path,
    output: Path | None,
    has_key_file: bool,
) -> tuple[bool, tuple[Path, ...]]:
    encrypt = command == "encrypt-cold-copy"
    archive = source if encrypt else output
    if archive is not None and archive.suffix.lower() != ".tbxcold":
        raise LifecycleError("cold_path_invalid", "select a .tbxcold plaintext archive")
    if encrypt and output is not None and output.suffix.lower() == ".tbxcold":
        raise LifecycleError("cold_path_invalid", "use a distinct extension for ciphertext")
    managed_roots: tuple[Path, ...] = ()
    if output is not None or has_key_file:
        managed_roots = tuple(
            root.resolve()
            for root in (
                ticketbox_program_data_root(),
                ticketbox_install_root(),
                ticketbox_control_root(),
            )
        )
    if output is not None and any(output.is_relative_to(root) for root in managed_roots):
        raise LifecycleError("cold_output_inside_source", "cold copy destination must be outside the installation")
    if output is not None and output.exists():
        raise LifecycleError("cold_output_exists", "select a new file for the result")
    return encrypt, managed_roots


def _encrypted_command(args: argparse.Namespace) -> dict[str, object]:
    from ticketbox_lifecycle.runtime.cold_copy_encryption import encrypt_cold_copy, read_encrypted_cold_copy

    source = _local_path(args.source)
    output = _local_path(args.output) if args.command != "verify-encrypted-cold-copy" else None
    encrypt, managed_roots = _validate_encrypted_paths(
        args.command,
        source,
        output,
        args.key_file is not None,
    )
    targets = (source,) if output is None else (source, output)
    secret = _read_secret(args, targets, managed_roots)
    if encrypt:
        return encrypt_cold_copy(source, output, secret)
    return read_encrypted_cold_copy(source, secret, output=output)


def main(argv: list[str]) -> int:
    parser = _PrivateArguments(description="Local cold retention, independent encryption and verification.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("cold-copy", help="Create a new copy after the administrator stops both services").add_argument("--output", required=True)
    commands.add_parser("verify-cold-copy", help="Read all archived bytes without extraction or restore").add_argument("--source", required=True)
    for name in _ENCRYPTED_COMMANDS:
        command = commands.add_parser(name, allow_abbrev=False, description="Use an independent recovery key or hidden passphrase prompt.")
        command.add_argument("--source", required=True, help="Absolute local input path")
        if name != "verify-encrypted-cold-copy":
            command.add_argument("--output", required=True, help="New absolute local output path")
        keys = command.add_mutually_exclusive_group()
        keys.add_argument("--passphrase-stdin", action="store_true", help="Read one UTF-8 passphrase line from private redirected stdin")
        keys.add_argument("--key-file", help="Separate local file containing 1 to 65536 exact key bytes")
    args = parser.parse_args(argv)
    try:
        if args.command == "cold-copy":
            output = Path(args.output)
            result = create_cold_copy(output, WindowsColdCopy.for_output(output))
        elif args.command == "verify-cold-copy":
            result = verify_cold_copy(Path(args.source))
        else:
            result = _encrypted_command(args)
        print(json.dumps({"ok": True, "command": args.command, **result}))
        return 0
    except LifecycleError as exc:
        code = exc.code
    except Exception:
        code = "cold_io_or_corrupt"
    print(json.dumps({"ok": False, "code": code, "message": "Cold copy operation incomplete. Keep the source and check the selected inputs and destination."}), file=sys.stderr)
    return 2
