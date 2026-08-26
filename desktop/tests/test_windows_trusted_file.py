from __future__ import annotations

import os

import pytest

from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_trusted_file import open_exclusive_file

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")


def test_readers_share_read_without_allowing_replacement(tmp_path) -> None:
    binding = tmp_path / "installation.json"
    replacement = tmp_path / "replacement.json"
    binding.write_bytes(b"binding")
    replacement.write_bytes(b"replacement")

    with (
        open_exclusive_file(binding, writable=False) as first,
        open_exclusive_file(binding, writable=False) as second,
    ):
        assert first.read() == b"binding"
        assert second.read() == b"binding"
        with pytest.raises(OSError) as blocked:
            os.replace(replacement, binding)
        assert blocked.value.winerror in {5, 32}

    os.replace(replacement, binding)
    assert binding.read_bytes() == b"replacement"


def test_writable_handle_remains_exclusive(tmp_path) -> None:
    channel = tmp_path / "result.json"
    channel.write_bytes(b"result")

    with (
        open_exclusive_file(channel, writable=True),
        pytest.raises(RuntimeControlError, match="无法独占打开文件"),
        open_exclusive_file(channel, writable=False),
    ):
        pass
