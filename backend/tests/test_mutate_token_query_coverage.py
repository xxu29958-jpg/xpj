"""Binary original replenishment carries its required OCC basis in the query."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from _audit_mutate_token_coverage import _operation_carries_token  # noqa: E402


@pytest.mark.parametrize("location,required,name,expected", [
    ("query", True, "expected_row_version", True),
    ("query", False, "expected_row_version", False),
    ("query", True, "unrelated_version", False),
    ("header", True, "expected_row_version", False),
])
def test_required_occ_query_is_visible_without_an_exemption(location, required, name, expected):
    operation = {"parameters": [{"in": location, "name": name, "required": required, "schema": {"type": "integer"}}]}
    assert _operation_carries_token({}, operation) is expected
