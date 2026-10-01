"""Public task reads and portable bytes retain counts without local manifests."""

import json
from datetime import UTC, datetime
from zipfile import ZipFile

import pytest

from app.models import BackgroundTask
from app.services.background_task_response import _to_response_dict
from app.services.orphan_task_results import DISPOSE_ORPHANS, INSPECT_ORPHANS
from app.services.portable_export_archive import create_portable_archive


@pytest.mark.parametrize("kind", [INSPECT_ORPHANS, DISPOSE_ORPHANS])
def test_public_task_and_download_hide_private_manifest_but_keep_results(kind):
    private_reference = "uploads/owner/private-original-name.png"
    result = {"candidate_files": 2, "deleted_files": 1,
        "_candidates": [{"reference": private_reference, "inode": 123}], "_outcomes": {private_reference: "deleted"}}
    row = BackgroundTask(id=1, public_id="public-task", task_type=kind, status="failed",
        error_code="OSError", error_message=f"Unable to access {private_reference}",
        result_summary_json=json.dumps(result))
    response = _to_response_dict(row, source_expense_id=None)
    assert response["result_summary"] == {"candidate_files": 2, "deleted_files": 1}
    assert private_reference not in json.dumps(response, default=str)
    section = [("background_task_observations", iter([{"public_id": row.public_id, "task_type": kind,
        "status": row.status, "result_summary_json": row.result_summary_json}]))]
    with create_portable_archive(ledger_id="owner", snapshot_at=datetime.now(UTC), account_public_id="owner",
            sections=section, originals=iter([])) as archive, ZipFile(archive.path) as package:
        content = package.read("records/background_task_observations.jsonl")
        exported = json.loads(content)
        assert json.loads(exported["result_summary_json"]) == response["result_summary"]
        assert private_reference.encode() not in content and b"_candidates" not in content and b"_outcomes" not in content
