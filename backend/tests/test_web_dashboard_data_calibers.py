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
    seed_confirmed_expense_fact,
)
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Expense, RecurringItem
from app.routes import web_common
from app.services import dataset_backup_inventory, expense_service, web_stats_service
from app.services.data_quality_service import is_usable_pending_merchant
from app.services.identity_service import hash_secret
from app.services.insights_service import recurring_candidates, unclaimed_recurring_candidate_count
from app.services.merchant_service import normalize_merchant
from app.services.time_service import current_month, now_utc


def test_dashboard_backup_caliber_accepts_only_published_complete_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dataset_backup_inventory,
        "latest_published_backup_record",
        lambda: None,
    )
    with SessionLocal() as db:
        block = web_common._dashboard_status_counts_block(db, "owner", now_utc())
    assert block["backup_available"] is False
    assert block["backup_age_days"] is None
    assert block["backup_age_status"] == "absent"


def test_dashboard_backup_caliber_rejects_future_publication_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = dataset_backup_inventory.BackupEntry(
        file_name="ticketbox-backup-6f162355-9e37-4523-a090-8daf2835f9e4",
        backup_id="6f162355-9e37-4523-a090-8daf2835f9e4",
        dataset_id="1d096080-20db-4a74-a138-1e72217f7746",
        restore_epoch=0,
        size_bytes=4096,
        created_at=now_utc() + timedelta(hours=1),
        kind="scheduled",
    )
    monkeypatch.setattr(
        dataset_backup_inventory,
        "latest_published_backup_record",
        lambda: entry,
    )
    monkeypatch.setattr(web_stats_service, "recent_expense_count", lambda *_args: 0)
    monkeypatch.setattr(web_stats_service, "recent_confirmed_expense_count", lambda *_args: 0)
    monkeypatch.setattr(web_stats_service, "active_device_count", lambda *_args: 0)

    block = web_common._dashboard_status_counts_block(object(), "owner", now_utc())

    assert block["backup_available"] is True
    assert block["backup_age_days"] is None
    assert block["backup_age_status"] == "future"


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


def test_overview_backup_card_renders_complete_or_missing_state(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loose dump is never an intermediate backup status."""

    def _card_body(text: str) -> str:
        card = re.search(r'data-overview-card="backup_status">.*?</article>', text, re.S)
        assert card is not None
        return card.group(0)

    monkeypatch.setattr(
        dataset_backup_inventory,
        "latest_published_backup_record",
        lambda: None,
    )
    page = web_client.get("/web/overview?ledger_id=owner")
    assert page.status_code == 200
    assert "还没有备份" in _card_body(page.text)

    entry = dataset_backup_inventory.BackupEntry(
        file_name="ticketbox-backup-6f162355-9e37-4523-a090-8daf2835f9e4",
        backup_id="6f162355-9e37-4523-a090-8daf2835f9e4",
        dataset_id="1d096080-20db-4a74-a138-1e72217f7746",
        restore_epoch=0,
        size_bytes=4096,
        created_at=now_utc() - timedelta(days=1),
        kind="scheduled",
    )
    monkeypatch.setattr(
        dataset_backup_inventory,
        "latest_published_backup_record",
        lambda: entry,
    )
    page = web_client.get("/web/overview?ledger_id=owner")
    assert page.status_code == 200
    assert "天前生成最近备份" in _card_body(page.text)


@pytest.mark.currency_binding_unbound
def test_dashboard_reports_card_list_matches_donut_caliber_on_zero_fraction_currency(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """PR #253 R9: 旧首页 reports 卡清单改吃 amount_label, 与同卡环图 amount_major
    同 exponent 口径 — JPY 本位下 donut ¥1,234 而清单 ¥12 (amount_yuan=minor/100)
    的 100× 自相矛盾不再出现。撤掉任一消费点的 amount_label 本测试红。"""
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        seed_confirmed_expense_fact(
            currency_code="JPY", amount_minor=1234, merchant="すき家", category="餐饮"
        )
        # 数据层: amount_label / amount_major 同按 minor digits 投影 (donut 优先消费后者)。
        data = web_client.get("/web/dashboard/data?ledger_id=owner")
        assert data.status_code == 200, data.text
        row = data.json()["category_share"][0]
        assert row["amount_major"] == 1234
        assert row["amount_major_text"] == "1234"
        assert row["amount_label"] == "¥1,234"

        # 服务端渲染清单 (no-JS 路径): 与环图同为 ¥1,234; 旧键 amount_yuan 会渲染成 ¥12。
        # 218-D S4: /web 根改向收件域, 服务端清单由 /web/overview 的 reports 卡
        # 承接 (同一 amount_label 消费点, <strong class="cat-amt">)。
        page = web_client.get("/web/overview?ledger_id=owner")
        assert page.status_code == 200
        assert 'class="cat-amt">¥1,234</strong>' in page.text
        assert 'class="cat-amt">¥12</strong>' not in page.text
    finally:
        get_settings.cache_clear()

    # JS 渐进渲染同口径静态钉 (无 JS runner): 清单吃 amount_label (label 自带符号),
    # 不再用 homeCurrencySymbol()+moneyRounded 拼 amount_yuan。
    static_root = Path(__file__).resolve().parents[1] / "app"
    dashboard_js = (static_root / "static/web/desktop/dashboard.js").read_text(encoding="utf-8")
    assert 'el("div", "cat-amt", text(c.amount_label))' in dashboard_js
    assert "moneyRounded(c.amount_yuan)" not in dashboard_js
    dashboard_html = (static_root / "templates/web/dashboard.html").read_text(encoding="utf-8")
    assert "{{ c.amount_label }}" in dashboard_html
    assert "'%.0f' % c.amount_yuan" not in dashboard_html
