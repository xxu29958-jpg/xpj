"""Frozen 20260524_0001 baseline statement groups."""

from __future__ import annotations

from .schema_01 import STATEMENTS as SCHEMA_01
from .schema_02 import STATEMENTS as SCHEMA_02
from .schema_03 import STATEMENTS as SCHEMA_03
from .schema_04 import STATEMENTS as SCHEMA_04
from .schema_05 import STATEMENTS as SCHEMA_05

STATEMENT_GROUPS: tuple[tuple[str, ...], ...] = (
    SCHEMA_01,
    SCHEMA_02,
    SCHEMA_03,
    SCHEMA_04,
    SCHEMA_05,
)
