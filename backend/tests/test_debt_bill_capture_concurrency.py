"""Independent HTTP transactions arbitrate original adoption against late inference."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Debt, DebtBillCapture
from app.services import debt_bill_source_parse
from app.services.debt_bill_parse_service import MockDebtBillProvider
from tests.test_debt_bill_capture import capture, create, create_body, parse

pytestmark = pytest.mark.real_db


def test_adoption_can_commit_during_inference_and_late_suggestion_cannot_overwrite_it(client, identity, monkeypatch):
    source = capture(client, identity)
    started, release = Event(), Event()

    class BlockedProvider(MockDebtBillProvider):
        def parse(self, data, media_type):
            started.set()
            assert release.wait(15), "test failed to release the controlled provider"
            return super().parse(data, media_type)

    monkeypatch.setattr(debt_bill_source_parse, "get_debt_bill_provider", BlockedProvider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        suggestion = pool.submit(parse, client, identity, source)
        assert started.wait(10)
        try:
            accepted = pool.submit(create, client, identity, create_body(source)).result(timeout=10)
            assert accepted.status_code == 201, accepted.text
        finally:
            release.set()
        late = suggestion.result(timeout=10)
    assert late.status_code == 409 and late.json()["error"] == "state_conflict"
    with SessionLocal() as db:
        original = db.scalar(select(DebtBillCapture))
        assert original.status == "confirmed" and original.row_version == 2 and original.parse_outcome is None
        assert original.adopted_debt_public_id == accepted.json()["public_id"]
        assert db.scalar(select(func.count()).select_from(Debt)) == 1


def test_two_same_key_admissions_and_adoptions_replay_one_original_and_one_fact(client, identity):
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = [future.result(timeout=15) for future in
            [pool.submit(capture, client, identity), pool.submit(capture, client, identity)]]
        assert one == two
        body = create_body(one)
        first, second = [future.result(timeout=15) for future in
            [pool.submit(create, client, identity, body), pool.submit(create, client, identity, body)]]
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 1
        assert db.scalar(select(func.count()).select_from(DebtBillCapture)) == 1
