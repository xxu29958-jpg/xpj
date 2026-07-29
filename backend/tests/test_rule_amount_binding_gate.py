"""分类规则金额阈值的绑定写门钉族（P1-1 / #258-R2 项5/6/7，自
test_currency_binding_marker 拆出守 500 行门）。

覆盖：金额规则计入无绑定证据集、create/update 带金额条件过门（纯关键词窄豁免）、
双界清 null 修复路径放行、env 惰性读、金额规则墓碑恢复视同携币种语义写。
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import CategoryRule
from app.services.app_meta_service import get_value
from app.services.currency_binding_service import (
    INSTALLATION_HOME_CURRENCY_KEY,
    assert_currency_binding_consistent,
)
from app.services.rule_service import create_rule, undo_delete_rule, update_rule
from app.services.time_service import now_utc
from tests.test_currency_binding_marker import _seed_cny_expense_fact_row


def test_amount_rule_blocks_first_binding_under_jpy(monkeypatch) -> None:
    # P1-1：仅有金额规则的安装（无绑定事实/无标记/无其他无绑定行）env=JPY →
    # 首笔绑定写拒 unresolved（规则金额是 CNY 时代遗留整数，单位不可判定）。
    with SessionLocal() as db:
        db.add(
            CategoryRule(
                tenant_id="owner",
                keyword="交通",
                category="交通",
                enabled=True,
                priority=100,
                amount_min_cents=1200,
            )
        )
        db.commit()
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
        get_settings.cache_clear()
        try:
            with pytest.raises(AppError) as excinfo:
                assert_currency_binding_consistent(db, "JPY")
            assert excinfo.value.error == "currency_binding_unresolved"
        finally:
            monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
            get_settings.cache_clear()


def test_rule_write_gated_under_drift(monkeypatch) -> None:
    # P1-1：CNY 事实 + env=JPY → 带金额条件的规则写 409 drift（纯关键词规则窄豁免放行）。
    _seed_cny_expense_fact_row()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            with pytest.raises(AppError) as excinfo:
                create_rule(
                    db,
                    tenant_id="owner",
                    keyword="交通",
                    category="交通",
                    enabled=True,
                    priority=100,
                    amount_min_cents=1200,
                )
            assert excinfo.value.error == "currency_binding_drift"
            # 窄豁免：无金额条件的纯关键词规则不携币种语义，不过门。
            create_rule(db, tenant_id="owner", keyword="咖啡", category="餐饮", enabled=True, priority=100)
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_rule_write_passes_on_jpy_fresh_install(monkeypatch) -> None:
    # P1-1：JPY 新装（空库无标记）→ 带金额规则写放行 + 同事务 claim 标记=JPY。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            rule = create_rule(
                db,
                tenant_id="owner",
                keyword="交通",
                category="交通",
                enabled=True,
                priority=100,
                amount_min_cents=1200,
            )
            assert rule.amount_min_cents == 1200
            assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) == "JPY"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_rule_update_clearing_both_bounds_bypasses_gate_under_drift(monkeypatch) -> None:
    # #258-R2 项5：drift（CNY 事实 + env=JPY）下显式双界清 null（清除金额语义=修复遗留
    # 规则）放行；设值仍拒。
    _seed_cny_expense_fact_row()
    with SessionLocal() as db:
        db.add(
            CategoryRule(
                tenant_id="owner",
                keyword="交通",
                category="交通",
                enabled=True,
                priority=100,
                amount_min_cents=100,
                amount_max_cents=5000,
            )
        )
        db.commit()
        rule = db.query(CategoryRule).first()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            cleared = update_rule(db, rule, expected_row_version=rule.row_version, amount_min_cents=None, amount_max_cents=None)
            assert cleared.amount_min_cents is None
            assert cleared.amount_max_cents is None
            with pytest.raises(AppError) as excinfo:
                update_rule(db, cleared, expected_row_version=cleared.row_version, amount_min_cents=1200)
            assert excinfo.value.error == "currency_binding_drift"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_keyword_rule_write_skips_env_read_when_env_misconfigured(monkeypatch) -> None:
    # #258-R2 项6：env 配错（支持集外）时纯关键词规则不读 env 创建成功；
    # 金额规则仍 fail-fast（currency_not_supported 先于门）。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "ZZZ")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            rule = create_rule(db, tenant_id="owner", keyword="咖啡", category="餐饮", enabled=True, priority=100)
            assert rule.id is not None
            with pytest.raises(AppError) as excinfo:
                create_rule(
                    db,
                    tenant_id="owner",
                    keyword="交通",
                    category="交通",
                    enabled=True,
                    priority=100,
                    amount_min_cents=1200,
                )
            assert excinfo.value.error == "currency_not_supported"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_amount_rule_tombstone_restore_rejected_without_marker(monkeypatch) -> None:
    # #258-R2 项7 + #258-R3/R4：无标记 + env=JPY → 金额墓碑恢复拒（unresolved）；
    # 纯关键词墓碑豁免不依赖标记，恢复放行。（标记==env 的放行回归见 ③。）
    with SessionLocal() as db:
        amount_rule = CategoryRule(
            tenant_id="owner",
            keyword="r27金额墓碑",
            category="交通",
            enabled=True,
            priority=100,
            amount_min_cents=1200,
            deleted_at=now_utc(),
        )
        keyword_rule = CategoryRule(
            tenant_id="owner",
            keyword="r27关键词墓碑",
            category="餐饮",
            enabled=True,
            priority=100,
            deleted_at=now_utc(),
        )
        db.add_all([amount_rule, keyword_rule])
        db.flush()
        amount_rule_id, keyword_rule_id = amount_rule.id, keyword_rule.id
        db.commit()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            with pytest.raises(AppError) as excinfo:
                undo_delete_rule(db, tenant_id="owner", rule_id=amount_rule_id)
            assert excinfo.value.error == "currency_binding_unresolved"
            restored_keyword = undo_delete_rule(db, tenant_id="owner", rule_id=keyword_rule_id)
            assert restored_keyword.deleted_at is None
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()


def test_amount_tombstone_blocks_first_jpy_binding(monkeypatch) -> None:
    # #258-R4 ①：legacy 安装仅含已软删金额规则（墓碑）→ env=JPY 首写拒 unresolved
    # （墓碑计入 unresolved 证据集 —— 标记永不覆盖 legacy 墓碑认领）。
    with SessionLocal() as db:
        db.add(
            CategoryRule(
                tenant_id="owner",
                keyword="交通",
                category="交通",
                enabled=True,
                priority=100,
                amount_min_cents=1200,
                deleted_at=now_utc(),
            )
        )
        db.commit()
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
        get_settings.cache_clear()
        try:
            with pytest.raises(AppError) as excinfo:
                assert_currency_binding_consistent(db, "JPY")
            assert excinfo.value.error == "currency_binding_unresolved"
            assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) is None
        finally:
            monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
            get_settings.cache_clear()


def test_amount_tombstone_self_heals_marker_on_cny() -> None:
    # #258-R4 ②：同情形 env=CNY → 放行 + 自愈补标=CNY（legacy CNY 时代整数定义上即 CNY）。
    with SessionLocal() as db:
        db.add(
            CategoryRule(
                tenant_id="owner",
                keyword="交通",
                category="交通",
                enabled=True,
                priority=100,
                amount_min_cents=1200,
                deleted_at=now_utc(),
            )
        )
        db.commit()
        assert_currency_binding_consistent(db, "CNY")
        assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) == "CNY"


def test_tombstone_restore_passes_when_marker_matches_env(monkeypatch) -> None:
    # #258-R4 ③（R3-4 回归）：JPY 标记安装创建金额规则 → 删除 → undo 恢复放行
    # （标记==env → 走主门，墓碑系标记后创建、币种无歧义）。
    from app.services.rule_service import delete_rule

    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            rule = create_rule(
                db,
                tenant_id="owner",
                keyword="交通",
                category="交通",
                enabled=True,
                priority=100,
                amount_min_cents=1200,
            )
            assert get_value(db, INSTALLATION_HOME_CURRENCY_KEY) == "JPY"
            delete_rule(db, rule, expected_row_version=rule.row_version)
        with SessionLocal() as db:
            restored = undo_delete_rule(db, tenant_id="owner", rule_id=rule.id)
            assert restored.deleted_at is None
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()
