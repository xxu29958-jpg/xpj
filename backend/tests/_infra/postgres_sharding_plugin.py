"""Hermetic pytest hook for declared PostgreSQL lane shard boundaries."""

from __future__ import annotations

import pytest

from scripts.run_postgres_pytest_lane import (
    POSTGRES_PYTEST_LANE_DEST,
    POSTGRES_PYTEST_SHARD_COUNT_DEST,
    POSTGRES_PYTEST_SHARD_INDEX_DEST,
    SHARDED_POSTGRES_PYTEST_LANES,
    partition_shard_items,
)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Select one complete, deterministic PostgreSQL responsibility shard."""
    lane = config.getoption(POSTGRES_PYTEST_LANE_DEST)
    shard_index = config.getoption(POSTGRES_PYTEST_SHARD_INDEX_DEST)
    shard_count = config.getoption(POSTGRES_PYTEST_SHARD_COUNT_DEST)
    if lane not in SHARDED_POSTGRES_PYTEST_LANES or shard_count == 1:
        return

    selected, deselected = partition_shard_items(
        items,
        shard_index=shard_index,
        shard_count=shard_count,
        nodeid_of=lambda item: item.nodeid,
    )
    if not selected:
        raise pytest.UsageError(
            f"{lane} PostgreSQL shard {shard_index}/{shard_count} selected no tests"
        )
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
