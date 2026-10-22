"""Frozen private IPC worker. Never initialize the backend or its database."""

from ocr_runtime.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
