"""Fresh PostgreSQL metadata protects the same threshold meaning as upgrades."""

import pytest
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models import CategoryRule
from app.services.currency_binding_service import resolve_write_capability


def _rule(**fields):
    return CategoryRule(tenant_id="owner", keyword="currency-storage", category="购物", enabled=True,
        priority=1, **fields)


def test_fresh_metadata_rejects_currencyless_money_but_allows_keyword_rules(identity):
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.add(_rule())
        db.commit()
    with SessionLocal() as db, pytest.raises(DBAPIError, match="monetary rule requires its captured currency"):
        resolve_write_capability(db)
        db.add(_rule(amount_min_cents=0))
        db.flush()


def test_fresh_metadata_keeps_original_units_after_clearing_thresholds(identity):
    with SessionLocal() as db:
        resolve_write_capability(db)
        rule = _rule(amount_min_cents=1200, home_currency_code="JPY")
        db.add(rule)
        db.commit()
        resolve_write_capability(db)
        rule.amount_min_cents = None
        db.commit()
        assert rule.home_currency_code == "JPY"
        resolve_write_capability(db)
        rule.home_currency_code = "CNY"
        with pytest.raises(DBAPIError, match="rule currency cannot relabel"):
            db.flush()
