from __future__ import annotations

import json
from pathlib import Path

import scripts.android_dependency_audit as dependency_audit

PLUGIN_VERSION = "12.2.2"
CONTRACT_DIGEST = "a" * 64


def _seed_database(path: Path, content: str = "trusted") -> None:
    data_dir = path / "11.0"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "odc.mv.db").write_text(content, encoding="utf-8")


def test_producer_rebuilds_when_seed_plugin_version_is_incompatible(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed"
    _seed_database(seed)
    dependency_audit._write_artifact_manifest(
        seed,
        plugin_version=PLUGIN_VERSION,
        contract_digest=CONTRACT_DIGEST,
    )
    manifest_path = seed / dependency_audit.ARTIFACT_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pluginVersion"] = "11.1.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "output"
    observed: list[tuple[str, bool]] = []

    def run_task(task: str, database: Path) -> int:
        observed.append((task, (database / "11.0" / "odc.mv.db").exists()))
        _seed_database(database, task)
        return 0

    dependency_audit.produce_dependency_database(
        output=output,
        seed=seed,
        run_task=run_task,
        plugin_version=PLUGIN_VERSION,
        contract_digest=CONTRACT_DIGEST,
    )

    assert observed[0] == ("dependencyCheckUpdate", False)
    dependency_audit._require_artifact_payload(
        output,
        plugin_version=PLUGIN_VERSION,
        contract_digest=CONTRACT_DIGEST,
    )
