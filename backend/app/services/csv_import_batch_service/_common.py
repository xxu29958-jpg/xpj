"""Shared constants for the CSV import batch lifecycle.

Leaf module: no intra-package imports.
"""

from __future__ import annotations

MAX_CSV_IMPORT_ROWS = 20_000
DEFAULT_BATCH_FILE_NAME = "import.csv"
APPLY_LEASE_MINUTES = 5
ROW_APPLY_LEASE_MINUTES = 2
CREATE_BATCH_INSERT_CHUNK_SIZE = 1000
