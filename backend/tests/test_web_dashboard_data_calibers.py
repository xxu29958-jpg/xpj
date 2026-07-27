"""Dashboard/overview 数据口径钉 (PR #253 R2/R3, 从 test_web_overview.py 拆出守 500 行债线)。

覆盖: backup lightweight 缓存/损坏/回退语义、分类溢出「其他」聚合、
pending 质量计数与旧物化口径逐字一致、recurring 候选排除已转正商家。
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from _web_overview_test_support import (
    create_pending_upload,
    seed_confirmed_expense,
    write_fake_dumps,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Expense, RecurringItem
from app.routes import web_common
from app.services import backup_service, backup_status_service, expense_service, web_stats_service
from app.services.data_quality_service import is_usable_pending_merchant
from app.services.identity_service import hash_secret
from app.services.insights_service import recurring_candidates, unclaimed_recurring_candidate_count
from app.services.merchant_service import normalize_merchant
from app.services.time_service import current_month, now_utc


def test_latest_backup_lightweight_validates_only_newest_once_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #253 R2 bot-P1: 只验最新一个 dump; (name, mtime, size) 缓存命中零重复验证。"""
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    backup_status_service._lightweight_backup_validation.clear()
    _older, newer = write_fake_dumps(tmp_path)
    validations: list[Path] = []

    def _fake_validate(path: Path) -> bool:
        validations.append(path)
        return True

    monkeypatch.setattr(backup_status_service, "_validate_dump_for_status", _fake_validate)

    first = backup_status_service.latest_backup_lightweight()
    second = backup_status_service.latest_backup_lightweight()
    assert first.state == "valid" and second.state == "valid"
    assert first.entry is not None and first.entry.file_name == "ticketbox-2026-07-20.dump"
    # 旧文件从不验证; 缓存命中 → 同一 dump 只验一次。
    assert validations == [newer]

    # (path, mtime, size) 变化 = 新 dump → 重新验证一次。
    newer.write_bytes(b"rewritten-dump-payload")
    third = backup_status_service.latest_backup_lightweight()
    assert third.state == "valid"
    assert validations == [newer, newer]


def test_latest_backup_lightweight_corrupt_newest_means_no_restorable_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全部归档畸形 → none 态: 状态卡按「无可恢复备份」呈现 (backup_available=False)。"""
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    backup_status_service._lightweight_backup_validation.clear()
    write_fake_dumps(tmp_path)
    monkeypatch.setattr(backup_status_service, "_validate_dump_for_status", lambda _path: False)

    status = backup_status_service.latest_backup_lightweight()
    assert status.state == "none"
    assert status.entry is None

    with SessionLocal() as db:
        block = web_common._dashboard_status_counts_block(db, "owner", now_utc())
    assert block["backup_available"] is False
    assert block["backup_unverified"] is False
    assert block["backup_age_days"] is None


def test_latest_backup_lightweight_tool_failure_is_not_cached_as_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #253 R4-3: 工具失败 (超时/不可用) 不缓存为 invalid — 下次成功即有效。"""
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    backup_status_service._lightweight_backup_validation.clear()
    _older, newer = write_fake_dumps(tmp_path)
    verdict = {"value": None}  # None=工具失败; True=验证通过
    calls: list[Path] = []

    def _flaky_validate(path: Path):
        calls.append(path)
        return verdict["value"]

    monkeypatch.setattr(backup_status_service, "_validate_dump_for_status", _flaky_validate)

    # 首次: 全部工具失败 → unverified 第三态 (有文件但无法判定), 不写缓存。
    first = backup_status_service.latest_backup_lightweight()
    assert first.state == "unverified"
    assert first.entry is None
    assert backup_status_service._lightweight_backup_validation == {}
    # 工具恢复后重试: 验证成功 → valid (且这次才缓存)。
    verdict["value"] = True
    second = backup_status_service.latest_backup_lightweight()
    assert second.state == "valid" and second.entry is not None
    assert second.entry.file_name == newer.name
    assert calls == [newer, _older, newer]
    assert list(backup_status_service._lightweight_backup_validation.values()) == [True]


def test_latest_backup_lightweight_falls_back_to_older_valid_dump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #253 R3-1: 最新 dump 损坏时向后找最新有效者 (与 latest_backup 同语义)。"""
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    backup_status_service._lightweight_backup_validation.clear()
    older, newer = write_fake_dumps(tmp_path)
    validations: list[Path] = []

    def _validate_by_name(path: Path) -> bool:
        validations.append(path)
        return path.name == older.name  # 新的坏, 旧的有效

    monkeypatch.setattr(backup_status_service, "_validate_dump_for_status", _validate_by_name)

    status = backup_status_service.latest_backup_lightweight()
    assert status.state == "valid"
    assert status.entry is not None and status.entry.file_name == older.name
    # 新→旧逐退, 每个文件只验一次 (再次调用全部缓存命中)。
    assert validations == [newer, older]
    assert backup_status_service.latest_backup_lightweight().state == "valid"
    assert validations == [newer, older]


def test_overview_category_share_aggregates_overflow_into_other(
    web_client: TestClient, *, identity
) -> None:
    """PR #253 R3-2: 前 5 + 第 6 名起聚合为「其他」片, 环图/清单按全量总额算占比。"""
    categories = ["餐饮", "交通", "居家", "购物", "娱乐", "医疗", "教育"]
    for index, category in enumerate(categories):
        seed_confirmed_expense(
            web_client,
            identity=identity,
            amount_cents=(index + 1) * 1000,
            merchant=f"商家{category}",
            category=category,
        )

    with SessionLocal() as db:
        rows = web_common._dashboard_category_share(db, "owner")
    assert len(rows) == 6
    assert [row["name"] for row in rows[:5]] == ["教育", "医疗", "娱乐", "购物", "居家"]
    other = rows[-1]
    assert other["name"] == "其他"
    # 聚合口径 = 全量总额 (7000+6000+5000+4000+3000 + 2000+1000)。
    assert sum(int(row["amount_cents"]) for row in rows) == 28000
    assert other["amount_cents"] == 3000
    assert other["count"] == 2


def test_dashboard_pending_counts_match_legacy_materialized_caliber(
    web_client: TestClient, *, identity
) -> None:
    """PR #253 R3-4: 聚合查询计数与旧「物化全行+Python 计数」口径逐字一致。"""
    from api_contract_helpers import web_save_expense

    # p1: 金额+可用商家 (三项质量问题都不沾)。
    p1 = create_pending_upload(web_client, identity=identity)
    resp = web_save_expense(
        web_client, p1, identity=identity,
        data={"amount_yuan": "10.00", "merchant": "海底捞", "category": "其他",
              "note": "", "ledger_id": "owner"},
    )
    assert resp.status_code in {303, 307}, resp.text
    # p2: 缺金额 + 缺商家 (原始上传态)。
    create_pending_upload(web_client, identity=identity)
    # p3: 有金额但商家不可用 (纯数字, Kotlin 谓词判 unusable)。
    p3 = create_pending_upload(web_client, identity=identity)
    resp = web_save_expense(
        web_client, p3, identity=identity,
        data={"amount_yuan": "5.00", "merchant": "12", "category": "其他",
              "note": "", "ledger_id": "owner"},
    )
    assert resp.status_code in {303, 307}, resp.text
    # p4: 疑似重复。
    p4 = create_pending_upload(web_client, identity=identity)
    with SessionLocal() as db:
        row = db.get(Expense, p4)
        assert row is not None
        row.duplicate_status = "suspected"
        db.commit()

    with SessionLocal() as db:
        legacy_rows = expense_service.list_pending(db, "owner")
        legacy = {
            "pending_count": len(legacy_rows),
            "needs_amount_count": sum(1 for e in legacy_rows if e.amount_cents is None),
            "needs_merchant_count": sum(
                1 for e in legacy_rows if not is_usable_pending_merchant(e.merchant)
            ),
            "suspected_duplicate_count": sum(
                1 for e in legacy_rows if (getattr(e, "duplicate_status", None) or "") == "suspected"
            ),
        }
        assert web_stats_service.pending_quality_counts(db, "owner") == legacy == {
            # 4 张相同 PNG: p2/p3/p4 哈希相同被判疑似重复; p2/p4 缺金额,
            # p2(None)/p3("12")/p4(None) 商家不可用。
            "pending_count": 4,
            "needs_amount_count": 2,
            "needs_merchant_count": 3,
            "suspected_duplicate_count": 3,
        }
        cards = web_common._dashboard_cards(db, "owner")
        for key, value in legacy.items():
            assert cards[key] == value


def test_recurring_candidate_count_excludes_formalized_merchants(
    web_client: TestClient, *, identity
) -> None:
    """PR #253 R3-5: 已转正 (active RecurringItem) 的商家不再占候选计数。"""
    month = current_month("Asia/Shanghai")
    prev_month = f"{int(month[:4]) - (1 if month[5:7] == '01' else 0):04d}-" + (
        "12" if month[5:7] == "01" else f"{int(month[5:7]) - 1:02d}"
    )
    for target_month in (prev_month, month):
        resp = web_client.post(
            "/api/expenses/manual",
            headers=identity.app_headers,
            json={
                "amount_cents": 9900,
                "merchant": "国家电网",
                "category": "居家",
                "expense_time": f"{target_month}-10T04:00:00Z",
            },
        )
        assert resp.status_code == 200, resp.text

    with SessionLocal() as db:
        assert unclaimed_recurring_candidate_count(db, tenant_id="owner") == 1
        db.add(
            RecurringItem(
                tenant_id="owner",
                merchant_key=normalize_merchant("国家电网"),
                merchant_name="国家电网",
                baseline_amount_cents=9900,
                last_amount_cents=9900,
                status="active",
            )
        )
        db.commit()
        # 确认转正后候选清零; R4 起 claimed 过滤在共享装配内, 原函数同口径。
        assert unclaimed_recurring_candidate_count(db, tenant_id="owner") == 0
        assert len(recurring_candidates(db, tenant_id="owner")) == 0


def test_overview_category_share_merges_overflow_into_existing_other_bucket(
    web_client: TestClient, *, identity
) -> None:
    """复审 P2a: 规范「其他」桶已进前 5 时, 溢出并入该桶而非另起同名双片。"""
    # 「其他」(normalize_category 缺省桶) 金额第 2 高 → 进前 5; 第 6/7 名溢出应并入。
    seeds = [
        ("餐饮", 9000),
        ("其他", 8000),
        ("交通", 7000),
        ("居家", 6000),
        ("购物", 5000),
        ("娱乐", 3000),
        ("医疗", 2000),
    ]
    for category, amount_cents in seeds:
        seed_confirmed_expense(
            web_client,
            identity=identity,
            amount_cents=amount_cents,
            merchant=f"商家{category}",
            category=category,
        )

    with SessionLocal() as db:
        rows = web_common._dashboard_category_share(db, "owner")
    names = [row["name"] for row in rows]
    # 同名只出现一次: 合并后共 5 行, 环图无「其他」双片。
    assert names.count("其他") == 1
    assert len(rows) == 5
    other = rows[names.index("其他")]
    assert other["amount_cents"] == 8000 + 3000 + 2000
    assert other["count"] == 3
    # 金额仍按全量总额口径 (9000+8000+7000+6000+5000+3000+2000)。
    assert sum(int(row["amount_cents"]) for row in rows) == 40000


def test_active_device_count_excludes_pending_and_expired_tokens(
    web_client: TestClient, *, identity
) -> None:
    """PR #253 R4-4: 连接设备只计可认证会话 (app/admin scope 且未过期未吊销)。"""
    with SessionLocal() as db:
        baseline = web_stats_service.active_device_count(db, "owner")
        owner_account = db.query(Account).order_by(Account.id.asc()).first()
        assert owner_account is not None
        desktop = Device(account_id=owner_account.id, device_name="pytest-desktop", platform="windows")
        old_phone = Device(account_id=owner_account.id, device_name="pytest-old-phone", platform="android")
        db.add_all([desktop, old_phone])
        db.flush()
        future = now_utc() + timedelta(days=7)
        past = now_utc() - timedelta(days=1)
        db.add_all(
            [
                # 待激活 desktop_pending: 不计。
                AuthToken(
                    token_hash=hash_secret("pending-tok"),
                    account_id=owner_account.id,
                    device_id=desktop.id,
                    ledger_id="owner",
                    scope="desktop_pending",
                    expires_at=future,
                ),
                # 已过期未吊销 app: 不计。
                AuthToken(
                    token_hash=hash_secret("expired-tok"),
                    account_id=owner_account.id,
                    device_id=old_phone.id,
                    ledger_id="owner",
                    scope="app",
                    expires_at=past,
                ),
                # 有效 app: 计。
                AuthToken(
                    token_hash=hash_secret("valid-tok"),
                    account_id=owner_account.id,
                    device_id=desktop.id,
                    ledger_id="owner",
                    scope="app",
                    expires_at=future,
                ),
            ]
        )
        db.commit()
        assert web_stats_service.active_device_count(db, "owner") == baseline + 1


def test_overview_backup_card_renders_all_three_states(
    web_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #253 R5-1: 备份卡三态落 UI — 有效=已备份天数, 工具失败=尚未验证, 无文件=还没有备份。"""
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    backup_status_service._lightweight_backup_validation.clear()

    def _card_body(text: str) -> str:
        card = re.search(r'data-overview-card="backup_status">.*?</article>', text, re.S)
        assert card is not None
        return card.group(0)

    # 1) 无 dump 文件 → 现有「还没有备份」空态。
    page = web_client.get("/web/overview?ledger_id=owner")
    assert page.status_code == 200
    assert "还没有备份" in _card_body(page.text)

    # 2) 有文件但工具失败 → 第三态 (不绿不红, 不谎称可用也不谎称没有)。
    write_fake_dumps(tmp_path)
    monkeypatch.setattr(backup_status_service, "_validate_dump_for_status", lambda _path: None)
    page = web_client.get("/web/overview?ledger_id=owner")
    assert page.status_code == 200
    body = _card_body(page.text)
    assert "检测到备份文件，尚未验证" in body
    assert "product-status--info" in body
    assert "天前生成最近备份" not in body
    assert "还没有备份" not in body

    # 3) 验证通过 → 已备份天数。
    monkeypatch.setattr(backup_status_service, "_validate_dump_for_status", lambda _path: True)
    backup_status_service._lightweight_backup_validation.clear()
    page = web_client.get("/web/overview?ledger_id=owner")
    assert page.status_code == 200
    assert "天前生成最近备份" in _card_body(page.text)
