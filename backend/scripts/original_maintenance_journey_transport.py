"""Cloud-only checkpoint latch around the real durable orphan task handler."""

import os
import time
from pathlib import Path

from app.main import app as app
from app.services import orphan_maintenance_tasks

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise RuntimeError("The interruption probe requires its isolated cloud installation")

_checkpoint = orphan_maintenance_tasks._checkpoint


def _pause_after_durable_chunk(db, task, result, **progress):
    _checkpoint(db, task, result, **progress)
    gate = Path(os.environ["TICKETBOX_DATA_DIR"]) / "orphan-pause-after-checkpoint"
    if task.task_type == "orphan_disposal" and gate.exists():
        gate.with_suffix(".reached").write_text(task.public_id, encoding="utf-8")
        while gate.exists():
            time.sleep(0.05)


orphan_maintenance_tasks._checkpoint = _pause_after_durable_chunk
