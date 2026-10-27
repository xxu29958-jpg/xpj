"""Explicit administrator cold retention; the installed sources are read only."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from ticketbox_lifecycle.domain.cold_copy import create_cold_copy
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.windows_cold_copy import WindowsColdCopy, verify_cold_copy


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Internal Beta cold retention and verification; no installation restore.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("cold-copy", help="Create a new copy after the administrator stops both services").add_argument("--output", required=True)
    commands.add_parser("verify-cold-copy", help="Read all archived bytes without extraction or restore").add_argument("--source", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "cold-copy":
            output = Path(args.output)
            result = create_cold_copy(output, WindowsColdCopy.for_output(output))
        else:
            result = verify_cold_copy(Path(args.source))
        print(json.dumps({"ok": True, "command": args.command, **result}))
        return 0
    except LifecycleError as exc:
        code = exc.code
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        code = "cold_io_or_corrupt"
    print(json.dumps({"ok": False, "code": code, "message": "Cold copy or verification incomplete. Keep original data; check stopped services and the output file. Failed files are not complete copies."}), file=sys.stderr)
    return 2
