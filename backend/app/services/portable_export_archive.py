"""Request-owned portable business records and original evidence, never a restore image."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Self
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from app.errors import AppError
from app.services.original_read_service import read_original_snapshot, recorded_original_digest

MAX_EXPORT_BYTES = 2 * 1024 * 1024 * 1024
MAX_EXPORT_SECONDS = 300
_README = """# Ticketbox 数据出口

manifest.json 说明范围、快照时间、记录数量和文件摘要；records/ 保存全部适用状态的业务记录。
每个 JSONL 文件一行一条记录。关联键沿用记录中的 id/public_id；集合名对应源业务记录。
金额保留整数最小货币单位；十进制汇率保留字符串精度；日期和时间不重新解释。
expenses.original_reference_id 对应 originals.jsonl；该索引列出每个原件的状态及包内文件。
缺失、损坏、已清理和旧件未核验分别说明，不用缩略图代替原件。
account_ 开头的集合是当前账号可见的收件箱和往来快照，不是对方私有账本的副本。
bill_split_change_proposals 保留各状态提议；bill_split_agreement_changes 保留双方已接受的约定变更。
同名 account_ 集合只含获准读取的跨账本关系。invitation_public_id、proposal_public_id 和
original_debt_public_id / return_debt_public_id 关联原约定、提议与两笔往来；调整使用 public_id 关联。
提议的返还往来可为空，而接受结果已建立返还往来；原邀请金额和已付款、已返还、免除仍是各自的历史事实。
历史回执的原件引用与当前记录分别列出；相同内容只保存一份文件。运行诊断不随回执导出。

本包不包含尚未提交到服务器的手机或浏览器草稿，也不包含有效登录凭据。
这是可阅读的业务数据和原件出口，不是安装恢复包或可执行命令队列。
文件内容是敏感的个人财务资料，请保存在你控制的位置。
"""


@dataclass
class _ExportBudget:
    used: int = 0
    started: float = field(default_factory=monotonic)

    def consume(self, size: int) -> None:
        self.used += size
        if self.used > MAX_EXPORT_BYTES or monotonic() - self.started > MAX_EXPORT_SECONDS:
            raise AppError("portable_export_limit", status_code=503)


@dataclass(frozen=True)
class PortableArchive:
    path: Path
    manifest: dict[str, object]
    _cleanup: ExitStack = field(repr=False, compare=False)

    def close(self) -> None:
        self._cleanup.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def _json_value(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    raise TypeError(f"Unsupported portable value type: {type(value).__name__}")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, default=_json_value, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _record(collection: str, row: Mapping[str, object]) -> dict[str, object]:
    result = dict(row)
    if collection == "accepted_operations":
        return _receipt_record(result)
    if collection != "expenses":
        return result
    result.pop("image_path", None)
    result["thumbnail_reference_present"] = bool(result.pop("thumbnail_path", None))
    result["original_reference_id"] = f"expense:{row['id']}:current"
    cleanup = row.get("attachment_cleanup_request")
    if isinstance(cleanup, dict):
        exported = dict(cleanup)
        for kind in ("image", "thumbnail"):
            item = cleanup.get(kind)
            if isinstance(item, dict):
                exported[kind] = {key: value for key, value in item.items() if key != "reference"}
                exported[kind]["reference_id"] = f"expense:{row['id']}:cleanup:{cleanup['request_id']}:{kind}"
        result["attachment_cleanup_request"] = exported
    return result


def _receipt_record(result: dict[str, object]) -> dict[str, object]:
    body = result.get("response_body")
    resource = result.get("resource_type")
    if not isinstance(body, dict) or resource not in {"expense", "expense_offset", "upload_receipt"}:
        return result
    exported = dict(body)
    source = body.get("root") if resource == "expense_offset" else body
    if not isinstance(source, dict):
        return result
    node = dict(source)
    if "image_path" in node:
        node.pop("image_path")
        node["original_reference_id"] = f"expense:{node['id']}:accepted:{result['id']}"
    if "thumbnail_path" in node:
        node["thumbnail_reference_present"] = bool(node.pop("thumbnail_path"))
    if isinstance(node.get("fx_task"), dict):
        node["fx_task"] = {key: value for key, value in node["fx_task"].items() if key != "error_message"}
        node["fx_task"]["error_message_omission_reason"] = "runtime_diagnostic"
    if resource == "expense_offset":
        exported["root"] = node
    else:
        exported = node
    return {**result, "response_body": exported}


def _write_records(package: ZipFile, name: str, rows: Iterable[Mapping[str, object]],
                   budget: _ExportBudget) -> dict[str, object]:
    if re.fullmatch(r"[a-z][a-z0-9_]{0,80}", name) is None:
        raise ValueError("Invalid portable collection name")
    path = f"records/{name}.jsonl"
    if path in package.namelist():
        raise ValueError("Duplicate portable collection")
    digest, size, count = hashlib.sha256(), 0, 0
    with package.open(path, "w", force_zip64=True) as output:
        for row in rows:
            data = _json_bytes(_record(name, row))
            budget.consume(len(data))
            output.write(data)
            digest.update(data)
            size += len(data)
            count += 1
    return {"name": name, "path": path, "records": count, "size_bytes": size, "sha256": digest.hexdigest()}


def _reference_rows(expense: Mapping[str, object]) -> Iterable[dict[str, object]]:
    root = f"expense:{expense['id']}"
    yield {"reference_id": f"{root}:current", "expense_id": expense["id"], "kind": "original",
        "source": expense.get("image_path"), "expected_sha256": expense.get("image_hash"),
        "cleaned": expense.get("image_deleted_at") is not None, "slot": "current"}
    cleanup = expense.get("attachment_cleanup_request")
    if not isinstance(cleanup, dict):
        return
    for kind in ("image", "thumbnail"):
        item = cleanup.get(kind)
        if isinstance(item, dict):
            yield {"reference_id": f"{root}:cleanup:{cleanup['request_id']}:{kind}",
                "expense_id": expense["id"], "kind": "original" if kind == "image" else "derived",
                "source": item.get("reference"), "expected_sha256": None,
                "cleaned": item.get("outcome") == "deleted", "slot": f"cleanup-{kind}"}


def _observe_original(package: ZipFile, reference: dict[str, object], ledger_id: str,
                      budget: _ExportBudget, included: dict[str, str]) -> dict[str, object]:
    result = {key: value for key, value in reference.items() if key not in {"source", "cleaned", "slot"}}
    result.update(path=None, sha256=None, size_bytes=None, observed_at=datetime.now(UTC))
    if reference["kind"] == "derived":
        return {**result, "state": "derived_not_included"}
    if reference["cleaned"]:
        return {**result, "state": "cleaned"}
    if not reference["source"]:
        return {**result, "state": "none"}
    result["expected_sha256"] = recorded_original_digest(reference["expected_sha256"])
    try:
        with read_original_snapshot(relative_path=reference["source"], tenant_id=ledger_id,
                                    expected_sha256=reference["expected_sha256"]) as snapshot:
            path = included.get(snapshot.sha256)
            if path is None:
                path = f"originals/{snapshot.sha256}{snapshot.path.suffix.lower()}"
                budget.consume(snapshot.size_bytes)
                package.write(snapshot.path, path)
                included[snapshot.sha256] = path
            result.update(path=path, sha256=snapshot.sha256, size_bytes=snapshot.size_bytes,
                          state="verified" if snapshot.verified else "unverified")
    except AppError as exc:
        if exc.error == "portable_export_limit":
            raise
        states = {"image_not_found": "missing", "image_integrity_mismatch": "corrupt"}
        result.update(state=states.get(exc.error, "unreadable"), error_code=exc.error)
    return result


def _history_reference(row: Mapping[str, object]) -> dict[str, object]:
    source = row.get("image_path")
    cleaned = row.get("image_deleted_at") is not None
    if source and source == row.get("current_image_path") and row.get("current_image_deleted_at") is not None:
        cleaned = True
    cleanup = row.get("attachment_cleanup_request")
    image = cleanup.get("image") if isinstance(cleanup, dict) else None
    if isinstance(image, dict) and image.get("reference") == source and image.get("outcome") == "deleted":
        cleaned = True
    return {"reference_id": f"expense:{row['expense_id']}:accepted:{row['accepted_operation_id']}",
        "expense_id": row["expense_id"], "accepted_operation_id": row["accepted_operation_id"],
        "accepted_at": row.get("accepted_at"), "kind": "original", "source": source,
        "expected_sha256": row.get("image_hash"), "cleaned": cleaned}


def _write_originals(package: ZipFile, directory: Path, ledger_id: str,
                     rows: Iterable[Mapping[str, object]], historical: Iterable[Mapping[str, object]],
                     budget: _ExportBudget) -> dict[str, object]:
    index_path = directory / "originals.jsonl"
    digest, size, count = hashlib.sha256(), 0, 0
    states: Counter[str] = Counter()
    included: dict[str, str] = {}
    current = (reference for expense in rows for reference in _reference_rows(expense))
    with index_path.open("xb") as output:
        for reference in chain(current, (_history_reference(row) for row in historical)):
            observation = _observe_original(package, reference, ledger_id, budget, included)
            data = _json_bytes(observation)
            budget.consume(len(data))
            output.write(data)
            digest.update(data)
            states[observation["state"]] += 1
            size += len(data)
            count += 1
    package.write(index_path, "originals.jsonl")
    return {"path": "originals.jsonl", "records": count, "size_bytes": size,
            "sha256": digest.hexdigest(), "states": dict(states)}


def create_portable_archive(*, ledger_id: str, snapshot_at: datetime, account_public_id: str,
                            sections: Iterable[tuple[str, Iterable[Mapping[str, object]]]],
                            originals: Iterable[Mapping[str, object]],
                            historical_originals: Iterable[Mapping[str, object]] = ()) -> PortableArchive:
    """Consume one authorized DB snapshot; publish only a closed, complete record package."""
    budget = _ExportBudget()
    with ExitStack() as cleanup:
        directory = Path(cleanup.enter_context(TemporaryDirectory(prefix="ticketbox-portable-")))
        path = directory / "ticketbox-data.zip"
        with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=1, allowZip64=True) as package:
            collections = [_write_records(package, name, rows, budget) for name, rows in sections]
            originals_index = _write_originals(package, directory, ledger_id, originals, historical_originals, budget)
            incomplete_states = set(originals_index["states"]) - {"verified", "none", "derived_not_included"}
            manifest = {"format": "ticketbox-portable-data", "version": 1, "ledger_id": ledger_id,
                "snapshot_at": snapshot_at, "records_complete": True, "originals_complete": not incomplete_states,
                "record_scope": {"account_public_id": account_public_id,
                    "ledger_collections": [item["name"] for item in collections if not item["name"].startswith("account_")],
                    "account_collections": [item["name"] for item in collections if item["name"].startswith("account_")],
                    "permission_basis": "current_authenticated_read_scope",
                    "excluded": ["other_members_private_records", "owner_console_audit",
                        "credentials", "machine_configuration", "client_unsubmitted_intents"]},
                "includes_client_unsubmitted_intents": False, "restore_image": False,
                "collections": collections, "originals_index": originals_index}
            for name, content in (("README.md", _README.encode("utf-8")), ("manifest.json", _json_bytes(manifest))):
                budget.consume(len(content))
                package.writestr(name, content)
        return PortableArchive(path, manifest, cleanup.pop_all())
