"""Hermetic pytest hook for the ordinary PostgreSQL shard boundary."""

from __future__ import annotations

import pytest

from scripts.run_postgres_pytest_lane import (
    PARALLEL_POSTGRES_PYTEST_LANE,
    POSTGRES_PYTEST_LANE_DEST,
    POSTGRES_PYTEST_SHARD_COUNT_DEST,
    POSTGRES_PYTEST_SHARD_INDEX_DEST,
    partition_shard_items,
)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Select one complete, deterministic ordinary-lane shard."""
    lane = config.getoption(POSTGRES_PYTEST_LANE_DEST)
    shard_index = config.getoption(POSTGRES_PYTEST_SHARD_INDEX_DEST)
    shard_count = config.getoption(POSTGRES_PYTEST_SHARD_COUNT_DEST)
    if lane != PARALLEL_POSTGRES_PYTEST_LANE or shard_count == 1:
        return

    selected, deselected = partition_shard_items(
        items,
        shard_index=shard_index,
        shard_count=shard_count,
        nodeid_of=lambda item: item.nodeid,
    )
    if not selected:
        raise pytest.UsageError(
            f"ordinary PostgreSQL shard {shard_index}/{shard_count} selected no tests"
        )
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
