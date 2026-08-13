"""Stable tenant identity facts shared by schema and runtime code.

This module is deliberately free of runtime configuration and I/O so model
registration can consume tenant defaults without loading machine state.
"""

from __future__ import annotations

import re

DEFAULT_TENANT_ID = "owner"
DEFAULT_TENANT_NAME = "我的小票夹"
TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
