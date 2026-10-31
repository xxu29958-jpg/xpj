"""A recalled suggestion is not the original reading: the Web note compares against the parser's own value."""
import json
from pathlib import Path

from fastapi.responses import FileResponse
from sqlalchemy import select

from app.models import Expense, LedgerLearningEvent
from app.routes import web_expense_edit
from app.schemas._recognition_fields import RecognitionFieldChoice
from app.services.learning_service import read_ocr_facts
from app.services.recognition_field_service import recognition_fields, record_field_choices
from tests._web_expense_review_test_support import _run_review_page
from tests._web_expense_review_test_support import review_browser as review_browser
from tests.test_recognition_field_choice import _seed
from tests.web_expense_fact_test_support import confirmation_actor
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store
from tests.web_expense_fact_test_support import confirmation_web as confirmation_web


def _correct_earlier_original(db, actor):
    # The same actor once corrected a similar original: 1800 -> 180, 海棠咖吽 -> 海棠咖啡.
    row = db.get(Expense, _seed(merchant="海棠咖吽"))
    readings = {(item.field, item.value): item for item in recognition_fields(
        read_ocr_facts(db, tenant_id="owner", expenses=[row])[row.id])}
    row.original_amount_minor = row.amount_cents = 180
    row.merchant = "海棠咖啡"
    record_field_choices(db, expense=row, actor_account_id=actor.account_id, choices=[
        RecognitionFieldChoice(field=item.field, candidate_id=item.id, evidence_public_id=item.evidence_public_id,
            parser_version=item.parser_version, intent="original_correction")
        for item in (readings[("amount_cents", 1800)], readings[("merchant", "海棠咖吽")])])
    db.commit()


def test_browser_note_compares_the_source_reading_not_the_recalled_value(
        review_browser, confirmation_store, monkeypatch, tmp_path):
    client, _ = review_browser
    with confirmation_store() as db:
        actor = confirmation_actor(db)
        _correct_earlier_original(db, actor)
    target = _seed(merchant="海棠咖吽")
    monkeypatch.setattr(web_expense_edit, "resolve_web_actor", lambda *args: (actor.account_id, actor.device_id))
    client.app.state.expense_review_probe = "correction-note-probe.js"

    @client.app.get("/correction-note-probe.js")
    def note_probe():
        return FileResponse(Path(__file__).parent / "fixtures/recognition_correction_note_probe.js", media_type="text/javascript")

    result = _run_review_page(client, tmp_path, f"/web/expenses/{target}/edit?ledger_id=owner&return_to=pending")
    assert not result.get("error") and result["completed"], result
    with confirmation_store() as db:
        row = db.get(Expense, target)
        events = [json.loads(event.after_payload) for event in db.scalars(select(LedgerLearningEvent).where(
            LedgerLearningEvent.subject_id == target, LedgerLearningEvent.signal_type == "recognition_field_choice"))]
    assert (row.original_amount_minor, row.merchant) == (180, "海棠咖啡")
    assert sorted((item["field"], item["intent"], item["_learning_qualified"]) for item in events) == [
        ("amount_cents", "original_correction", True), ("merchant", "original_correction", True)]
    assert {item["selected"]["value"] for item in events} == {1800, "海棠咖吽"}, "The note must point at the source reading"
    assert all(item["presentation"] and item["_history_exposed"] for item in events), [
        (item["field"], item["presentation"], item["_history_exposed"]) for item in events]


def test_browser_abstained_source_order_is_saved_with_the_deliberate_choice(
        review_browser, confirmation_store, monkeypatch, tmp_path):
    client, _ = review_browser
    with confirmation_store() as db:
        actor = confirmation_actor(db)
    target = _seed(raw_override="实付25.00元\n实付18.00元\n商户：海棠咖啡")
    monkeypatch.setattr(web_expense_edit, "resolve_web_actor", lambda *args: (actor.account_id, actor.device_id))
    client.app.state.expense_review_probe = "source-order-probe.js"

    @client.app.get("/source-order-probe.js")
    def source_probe():
        return FileResponse(Path(__file__).parent / "fixtures/recognition_source_order_probe.js", media_type="text/javascript")

    result = _run_review_page(client, tmp_path, f"/web/expenses/{target}/edit?ledger_id=owner&return_to=pending")
    assert not result.get("error") and result["completed"], result
    with confirmation_store() as db:
        row = db.get(Expense, target)
        event = db.scalar(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == target,
            LedgerLearningEvent.signal_type == "recognition_field_choice"))
        payload = json.loads(event.after_payload)
    assert row.amount_cents == 2500
    assert payload["presentation"] == "source-order-v1:text"
    assert payload["candidate_id"] == result["chosen"]["candidate_id"]
    assert payload["_history_exposed"] is False and payload["_learning_qualified"] is True
