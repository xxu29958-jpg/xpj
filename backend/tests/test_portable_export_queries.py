"""Pure SQL boundary tests; SQLite rows exercise predicates, not PG snapshot claims."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import visitors

from app import models as m
from app.services.portable_export_queries import portable_original_history_query, portable_projections, portable_queries
from app.tenants import AuthContext

AUTH = AuthContext(account_id=7, account_public_id="actor", account_name="Actor",
    ledger_id="selected", ledger_name="Selected", device_id=1, device_public_id="device",
    device_name="Device", role="viewer", scope="app")


def _queries(auth=AUTH):
    return dict(portable_queries(auth))


@pytest.fixture
def records():
    # Deliberately no production DB/config/fixtures. These unconstrained seed tables
    # test the actual SELECT predicates; actual FK/snapshot qualification uses PG.
    engine = create_engine("sqlite://")
    metadata = MetaData()
    sources = {node.name: node for query in _queries(replace(AUTH, role="owner")).values()
        for node in visitors.iterate(query) if isinstance(node, Table)}
    tables = {name: Table(name, metadata, *(
        Column(column.name, Integer if isinstance(column.type, Integer) else String)
        for column in source.columns)) for name, source in sources.items()}
    metadata.create_all(engine)
    with engine.begin() as connection:
        yield connection, tables
    engine.dispose()


def _seed(records, model, **values):
    connection, tables = records
    connection.execute(tables[model.__tablename__].insert().values(**values))


def _rows(records, name, auth=AUTH):
    return records[0].execute(_queries(auth)[name]).mappings().all()


def test_export_covers_retained_domains_without_screen_limits_or_orm_entities():
    queries = _queries()
    assert {"expenses", "expense_items", "expense_splits", "expense_tags", "expense_revisions",
        "expense_offset_facts", "expense_offset_revisions", "csv_import_batches", "csv_import_rows",
        "csv_import_events", "budgets", "budget_categories", "goals", "debt_goal_links",
        "monthly_income_plans", "income_plan_revisions", "recurring_items", "recurring_occurrences",
        "recurring_occurrence_revisions", "debts", "repayments", "repayment_voids", "debt_voids",
        "debt_adjustments", "debt_forgivenesses", "member_repayment_proposals", "repayment_drafts",
        "merchant_catalog", "merchant_aliases", "category_preferences", "tags", "category_rules",
        "rule_application_batches", "rule_application_changes", "tag_mutation_undo_groups",
        "tag_mutation_undo_items", "ocr_facts", "algorithm_decisions", "ledger_learning_events",
        "ledger_calendar_revisions", "accepted_operations"} <= queries.keys()
    for statement in queries.values():
        assert statement._limit_clause is None
        assert statement._offset_clause is None
        assert statement.selected_columns
        assert all(description["expr"] is not description.get("entity")
            for description in statement.column_descriptions)
        assert str(statement.compile(dialect=postgresql.dialect())).startswith("SELECT ")


def test_all_projections_execute_as_mapping_reads_and_identity_refs_stay_authorized(records):
    _seed(records, m.Account, id=7, public_id="actor", display_name="Actor")
    _seed(records, m.Account, id=8, public_id="historical-member", display_name="Historical member")
    _seed(records, m.Account, id=9, public_id="unrelated", display_name="Private account")
    _seed(records, m.LedgerMember, id=1, ledger_id="selected", account_id=7, role="viewer")
    _seed(records, m.LedgerMember, id=2, ledger_id="selected", account_id=8, role="member",
        disabled_at="2026-09-01 00:00:00")
    _seed(records, m.LedgerMember, id=3, ledger_id="other", account_id=9, role="owner")
    for role in ("viewer", "owner"):
        for statement in _queries(replace(AUTH, role=role)).values():
            records[0].execute(statement).mappings().all()
    assert {row["public_id"] for row in _rows(records, "accounts")} == {"actor", "historical-member"}


def test_no_credentials_machine_settings_or_import_claims_are_selected():
    queries = _queries(replace(AUTH, role="owner"))
    assert not {"auth_tokens", "devices", "app_meta", "upload_links", "invitations",
        "installation_idempotency_keys", "dataset_authority", "ai_member_anon_maps"} & queries.keys()
    for statement in queries.values():
        assert not {"token_hash", "cloud_subject_id", "identity_provider", "credential_hash",
            "apply_token", "locked_until", "input_payload_json", "base_url"} & set(statement.selected_columns.keys())
    assert {"image_path", "thumbnail_path", "image_hash", "attachment_cleanup_request",
        "image_replenished_at", "accounting_date", "calendar_revision"} <= set(queries["expenses"].selected_columns.keys())
    assert "response_body" in queries["accepted_operations"].selected_columns


def test_all_expense_states_and_revision_history_stay_in_selected_ledger(records):
    for index, status in enumerate(("pending", "confirmed", "rejected"), 1):
        _seed(records, m.Expense, id=index, public_id=f"local-{status}", tenant_id="selected", status=status)
        _seed(records, m.ExpenseRevision, id=index, tenant_id="selected", expense_id=index,
            revision_number=index, public_id=f"history-{status}")
    _seed(records, m.Expense, id=99, public_id="private", tenant_id="other", status="confirmed")
    _seed(records, m.ExpenseRevision, id=99, tenant_id="other", expense_id=99, public_id="private-history")
    assert {row["status"] for row in _rows(records, "expenses")} == {"pending", "confirmed", "rejected"}
    assert {row["expense_id"] for row in _rows(records, "expense_revisions")} == {1, 2, 3}


def test_repayment_drafts_are_personal_even_for_owner_and_include_resolved_history(records):
    for id_, actor, ledger, status in ((1, 7, "selected", "pending"), (2, 7, "selected", "confirmed"),
        (3, 8, "selected", "pending"), (4, 7, "other", "pending")):
        _seed(records, m.RepaymentDraft, id=id_, public_id=str(id_), tenant_id=ledger,
            created_by_account_id=actor, status=status)
    for role in ("viewer", "member", "owner"):
        assert {row["id"] for row in _rows(records, "repayment_drafts", replace(AUTH, role=role))} == {1, 2}


def test_debt_children_use_the_authorized_parent_and_keep_void_history(records):
    _seed(records, m.Debt, id=1, public_id="local", tenant_id="selected", status="voided")
    _seed(records, m.Debt, id=2, public_id="private", tenant_id="other", counterparty_account_id=7)
    _seed(records, m.Repayment, id=10, public_id="paid", debt_id=1)
    _seed(records, m.Repayment, id=20, public_id="private-paid", debt_id=2)
    _seed(records, m.RepaymentVoid, id=11, public_id="void", repayment_id=10)
    _seed(records, m.RepaymentVoid, id=21, public_id="private-void", repayment_id=20)
    assert [row["public_id"] for row in _rows(records, "repayments")] == ["paid"]
    assert [row["public_id"] for row in _rows(records, "repayment_voids")] == ["void"]


def test_split_projection_never_exports_the_other_partys_private_ledger(records):
    common = {"sender_ledger_id": "selected", "sender_expense_id": 1, "receiver_account_id": 8,
        "receiver_ledger_id": "secret-destination", "received_expense_id": 55, "status": "accepted"}
    _seed(records, m.BillSplitInvitation, id=1, public_id="mine", sender_account_id=7, **common)
    _seed(records, m.BillSplitInvitation, id=2, public_id="coworker", sender_account_id=9, **common)
    _seed(records, m.BillSplitInvitation, id=3, public_id="received", sender_account_id=8,
        sender_ledger_id="secret-source", sender_expense_id=99, receiver_account_id=7,
        receiver_ledger_id="selected", received_expense_id=5, status="accepted")
    _seed(records, m.BillSplitInvitation, id=4, public_id="unassigned-inbox", sender_account_id=8,
        sender_ledger_id="other", receiver_account_id=7, status="invited")
    sent = _rows(records, "bill_split_sent")
    inbox = _rows(records, "account_bill_split_inbox")
    assert [row["public_id"] for row in sent] == ["mine"]
    assert [row["public_id"] for row in inbox] == ["received", "unassigned-inbox"]
    assert [row["local_received_expense_id"] for row in inbox] == [5, None]
    assert not {"receiver_ledger_id", "receiver_member_id", "received_expense_id"} & sent[0].keys()
    assert not {"sender_ledger_id", "sender_member_id", "sender_expense_id"} & inbox[0].keys()
    assert {row["invitation_public_id"] for row in _rows(records, "bill_split_source_relationships")} == {"mine", "coworker"}


def test_account_participant_records_are_explicitly_separate_and_exclude_private_fields(records):
    _seed(records, m.Account, id=8, public_id="other-actor", display_name="Other party")
    _seed(records, m.Debt, id=1, public_id="shared-obligation", tenant_id="secret-ledger",
        owner_account_id=8, counterparty_account_id=7, counterparty_label="Actor", note="Agreed note")
    _seed(records, m.Debt, id=2, public_id="inaccessible", tenant_id="secret-ledger", counterparty_account_id=9)
    _seed(records, m.Repayment, id=10, public_id="shared-payment", debt_id=1, actor_account_id=8,
        idempotency_key="private-execution-key")
    _seed(records, m.RepaymentVoid, id=11, public_id="shared-void", repayment_id=10, reason="Mistake")
    _seed(records, m.MemberRepaymentProposal, id=12, public_id="shared-proposal", debt_id=1,
        committed_repayment_id=10, note="Payment note", proposed_by_account_id=8)
    debts = _rows(records, "account_debt_relationships")
    assert [(row["public_id"], row["counterparty_label"]) for row in debts] == [("shared-obligation", "Other party")]
    assert not {"id", "tenant_id", "owner_account_id", "created_by_account_id"} & debts[0].keys()
    payments = _rows(records, "account_repayments")
    assert payments[0]["debt_public_id"] == "shared-obligation"
    assert not {"debt_id", "actor_account_id", "idempotency_key", "proposal_id"} & payments[0].keys()
    assert _rows(records, "account_repayment_voids")[0]["repayment_public_id"] == "shared-payment"
    proposals = _rows(records, "account_repayment_proposals")
    assert proposals[0]["committed_repayment_public_id"] == "shared-payment"
    assert not {"debt_id", "proposed_by_account_id", "idempotency_key"} & proposals[0].keys()


def test_governance_audit_keeps_existing_owner_permission():
    for role in ("viewer", "member"):
        assert "ledger_audit_logs" not in _queries(replace(AUTH, role=role))
        assert "budget_advisor_audit_logs" not in _queries(replace(AUTH, role=role))
    assert "ledger_audit_logs" in _queries(replace(AUTH, role="owner"))
    # A ledger owner is not the LocalOnly Owner Console identity.
    assert "budget_advisor_audit_logs" not in _queries(replace(AUTH, role="owner"))


def test_upload_acceptance_survives_lost_ack_without_disclosing_private_task_receipt(records):
    for id_, actor in ((1, 7), (2, 8)):
        _seed(records, m.BackgroundTask, id=id_, public_id=f"task-{id_}", tenant_id="selected",
            initiated_by_account_id=actor)
        _seed(records, m.ApiIdempotencyKey, id=id_, tenant_id="selected", resource_type="upload_receipt",
            resource_id=f"expense-{id_}", status="succeeded",
            response_body=json.dumps({"public_id": f"expense-{id_}", "enrichment_task_public_id": f"task-{id_}"}))
    results = _rows(records, "accepted_operations")
    assert results[0]["response_body"]["enrichment_task_public_id"] == "task-1"
    assert results[0]["response_body_omission_reason"] is None
    assert results[1]["resource_id"] == "expense-2"
    assert results[1]["response_body"] is None
    assert results[1]["response_body_omission_reason"] == "personal_task_scope"


def test_participant_balance_uses_existing_owner_and_preserves_failure(records, monkeypatch):
    from app.services import debt_service

    _seed(records, m.Debt, id=1, public_id="shared", tenant_id="other", counterparty_account_id=7)
    _seed(records, m.Debt, id=2, public_id="private", tenant_id="other", counterparty_account_id=8)
    calls = []

    def read(_db, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(public_id="shared", home_currency_code="USD", principal_amount_cents=100,
            remaining_amount_cents=0, paid_amount_cents=40, status="cleared", is_forgiven=True,
            installment_paid_count=None, installment_payoff_date=None, viewer_is_debtor=False, row_version=3)

    monkeypatch.setattr(debt_service, "get_participant_debt_response", read)
    name, result = portable_projections(records[0], AUTH)[0]
    assert name == "account_debt_balances"
    assert list(result)[0]["is_forgiven"] is True
    assert calls == [{"public_id": "shared", "ledger_id": "selected", "account_id": 7}]

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("read unavailable")

    monkeypatch.setattr(debt_service, "get_participant_debt_response", unavailable)
    with pytest.raises(RuntimeError, match="read unavailable"):
        list(portable_projections(records[0], AUTH)[0][1])


def test_old_receipt_original_is_not_replaced_with_current_file(records):
    _seed(records, m.Expense, id=1, public_id="expense", tenant_id="selected", image_path="new-image.png",
        thumbnail_path="new-thumb.png", image_hash="b" * 64)
    old = {"id": 1, "public_id": "expense", "image_path": "old-image.png", "thumbnail_path": "old-thumb.png",
        "image_hash": "a" * 64, "image_deleted_at": None, "thumbnail_deleted_at": None}
    for id_, ledger, kind, body in ((1, "selected", "expense", old),
        (2, "selected", "expense_offset", {"root": old}), (3, "other", "expense", old),
        (4, "selected", "repayment_draft", old)):
        _seed(records, m.ApiIdempotencyKey, id=id_, tenant_id=ledger, resource_type=kind,
            status="succeeded", response_body=json.dumps(body))
    statement = portable_original_history_query(AUTH)
    assert "LEFT OUTER JOIN" in str(statement.compile(dialect=postgresql.dialect()))
    results = records[0].execute(statement).mappings().all()
    assert [row["accepted_operation_id"] for row in results] == [1, 2]
    assert all(row["image_path"] == "old-image.png" and row["image_hash"] == "a" * 64 for row in results)
    assert all(row["current_image_path"] == "new-image.png" for row in results)


def test_history_keeps_explicit_no_attachment_without_treating_original_command_as_expense_snapshot(records):
    _seed(records, m.ApiIdempotencyKey, id=1, tenant_id="selected", resource_type="expense", status="succeeded",
        response_body=json.dumps({"id": 1, "public_id": "manual", "image_path": None, "thumbnail_path": None}))
    _seed(records, m.ApiIdempotencyKey, id=2, tenant_id="selected", resource_type="expense", status="succeeded",
        response_body=json.dumps({"expense_id": 1, "public_id": "manual", "operation": "verify_original"}))
    results = records[0].execute(portable_original_history_query(AUTH)).mappings().all()
    assert len(results) == 1
    assert results[0]["accepted_operation_id"] == 1
    assert results[0]["expense_id"] == 1
    assert results[0]["image_path"] is None
    assert results[0]["thumbnail_path"] is None


def test_history_shares_cleanup_evidence_only_for_the_same_expense_and_path(records):
    _seed(records, m.Expense, id=1, public_id="expense", tenant_id="selected", image_path="new.png")
    old = {"id": 1, "public_id": "expense", "image_path": "old.png", "image_deleted_at": None}
    bodies = [old, {"root": {**old, "image_deleted_at": "2026-09-19T00:00:00Z"}},
        {**old, "image_path": "new.png"}, {**old, "id": 2, "public_id": "unrelated"}]
    for id_, body in enumerate(bodies, 1):
        _seed(records, m.ApiIdempotencyKey, id=id_, tenant_id="selected", status="succeeded",
            resource_type="expense_offset" if "root" in body else "expense", response_body=json.dumps(body))
    results = records[0].execute(portable_original_history_query(AUTH)).mappings().all()
    assert [bool(row["historical_image_cleaned"]) for row in results] == [True, True, False, False]
    assert results[0]["image_deleted_at"] is None
    assert results[0]["current_image_path"] == "new.png"


def test_success_receipts_do_not_disclose_another_members_private_draft_or_invitation(records):
    _seed(records, m.RepaymentDraft, id=1, public_id="own-draft", tenant_id="selected", created_by_account_id=7)
    _seed(records, m.RepaymentDraft, id=2, public_id="private-draft", tenant_id="selected", created_by_account_id=8)
    _seed(records, m.BillSplitInvitation, id=1, public_id="own-invitation", sender_ledger_id="selected", sender_account_id=7)
    _seed(records, m.BillSplitInvitation, id=2, public_id="private-invitation", sender_ledger_id="selected", sender_account_id=8)
    for id_, resource_type, resource_id in ((1, "repayment_draft", "own-draft"),
        (2, "repayment_draft", "private-draft"), (3, "bill_split_invitation", "own-invitation"),
        (4, "bill_split_invitation", "private-invitation"), (5, "expense", "1")):
        _seed(records, m.ApiIdempotencyKey, id=id_, tenant_id="selected", status="succeeded",
            resource_type=resource_type, resource_id=resource_id)
    _seed(records, m.ApiIdempotencyKey, id=6, tenant_id="selected", status="in_progress", resource_type="expense")
    _seed(records, m.ApiIdempotencyKey, id=7, tenant_id="other", status="succeeded", resource_type="expense")
    _seed(records, m.ApiIdempotencyKey, id=8, tenant_id="selected", status="succeeded", resource_type="auth_token",
        response_body=json.dumps({"token": "never-export-this"}))
    assert {row["id"] for row in _rows(records, "accepted_operations")} == {1, 3, 5}


def test_split_agreement_records_keep_both_legs_and_permission_boundary_in_zip(records):
    from datetime import UTC, datetime
    from zipfile import ZipFile

    from app.services.portable_export_archive import create_portable_archive

    names = {"bill_split_change_proposals", "bill_split_agreement_changes",
             "account_bill_split_change_proposals", "account_bill_split_agreement_changes"}
    assert names <= _queries().keys(), "The portable snapshot must retain bilateral agreement history"
    for index, ledger, counterparty in ((1, "selected", 8), (2, "secret-ledger", 7), (3, "secret-ledger", 9)):
        _seed(records, m.BillSplitInvitation, id=index, public_id=f"invitation-{index}", status="accepted",
              home_currency_code="CNY", sender_ledger_id="private-source", sender_expense_id=99)
        for leg, source in ((index * 10, "bill_split"), (index * 10 + 1, "bill_split_return")):
            _seed(records, m.Debt, id=leg, public_id=f"debt-{leg}", tenant_id=ledger,
                  counterparty_account_id=counterparty, source_type=source, source_id=f"invitation-{index}")
        _seed(records, m.DebtAdjustment, id=index, public_id=f"adjustment-{index}", debt_id=index * 10)
        _seed(records, m.BillSplitChangeProposal, id=index, public_id=f"proposal-{index}", invitation_id=index,
              original_debt_id=index * 10, return_debt_id=None, status="accepted", original_debt_row_version=7,
              share_before_amount_cents=4000, new_share_amount_cents=2000, settlement_net_amount_cents=-1000,
              original_paid_amount_cents=3000, return_paid_amount_cents=0, reason="共同确认退款后的结算")
        _seed(records, m.BillSplitAgreementChange, id=index, public_id=f"change-{index}", invitation_id=index,
              proposal_id=index, original_debt_id=index * 10, return_debt_id=index * 10 + 1,
              original_adjustment_id=index, new_share_amount_cents=2000, settlement_net_amount_cents=-1000)
    _seed(records, m.BillSplitChangeProposal, id=4, public_id="old-rejected", invitation_id=1,
          original_debt_id=10, status="rejected", new_share_amount_cents=2500)
    queries = _queries()
    sections = ((name, records[0].execute(queries[name]).mappings()) for name in sorted(names))
    with create_portable_archive(ledger_id="selected", account_public_id="actor",
            snapshot_at=datetime(2026, 9, 20, tzinfo=UTC), sections=sections, originals=()) as archive, \
            ZipFile(archive.path) as package:
        rows = {name: [json.loads(line) for line in package.read(f"records/{name}.jsonl").splitlines()]
                for name in names}
        assert [row["public_id"] for row in rows["bill_split_change_proposals"]] == ["proposal-1", "old-rejected"]
        assert [row["public_id"] for row in rows["account_bill_split_change_proposals"]] == ["proposal-2"]
        change = rows["account_bill_split_agreement_changes"][0]
        assert change["proposal_public_id"] == "proposal-2"
        assert change["original_debt_public_id"] == "debt-20"
        assert change["return_debt_public_id"] == "debt-21"
        assert change["original_adjustment_public_id"] == "adjustment-2"
        assert change["invitation_public_id"] == "invitation-2"
        assert change["home_currency_code"] == "CNY"
        assert change["settlement_net_amount_cents"] == -1000
        assert rows["account_bill_split_change_proposals"][0]["return_debt_public_id"] is None
        assert "secret-ledger" not in json.dumps(rows) and "private-source" not in json.dumps(rows)
        for exported in rows.values():
            for row in exported:
                assert not {"id", "invitation_id", "proposal_id", "original_debt_id", "return_debt_id",
                            "sender_expense_id", "received_expense_id", "idempotency_key"} & row.keys()
        manifest = json.loads(package.read("manifest.json"))
        assert set(manifest["record_scope"]["account_collections"]) == {name for name in names if name.startswith("account_")}


def test_split_change_receipts_require_actual_debt_visibility(records):
    for index, ledger, party in ((1, "selected", 8), (2, "private", 7), (3, "private", 8)):
        _seed(records, m.Debt, id=index, public_id=f"debt-{index}", tenant_id=ledger, counterparty_account_id=party)
        _seed(records, m.ApiIdempotencyKey, id=index, tenant_id="selected", resource_type="debt",
              resource_id=f"debt-{index}", target_type="bill_split_change", status="succeeded",
              response_body=json.dumps({"reason": f"split-{index}"}))
    assert {row["id"] for row in _rows(records, "accepted_operations")} == {1, 2}


def test_debt_receipts_require_access_to_the_parent_relationship(records):
    for id_, public_id, ledger, counterparty in (
        (1, "local-debt", "selected", 8),
        (2, "shared-debt", "other", 7),
        (3, "private-debt", "other", 8),
    ):
        _seed(records, m.Debt, id=id_, public_id=public_id, tenant_id=ledger,
            counterparty_account_id=counterparty)
        _seed(records, m.Repayment, id=id_, public_id=f"{public_id}-repayment", debt_id=id_)
        _seed(records, m.MemberRepaymentProposal, id=id_, public_id=f"{public_id}-proposal", debt_id=id_)
    receipt_id = 0
    for resource_type, suffix in (
        ("debt", ""),
        ("repayment", "-repayment"),
        ("debt_repayment_proposal", "-proposal"),
    ):
        for debt_public_id in ("local-debt", "shared-debt", "private-debt"):
            receipt_id += 1
            _seed(records, m.ApiIdempotencyKey, id=receipt_id, tenant_id="selected", status="succeeded",
                resource_type=resource_type, resource_id=f"{debt_public_id}{suffix}")

    results = _rows(records, "accepted_operations")
    assert {(row["resource_type"], row["resource_id"]) for row in results} == {
        ("debt", "local-debt"),
        ("debt", "shared-debt"),
        ("repayment", "local-debt-repayment"),
        ("repayment", "shared-debt-repayment"),
        ("debt_repayment_proposal", "local-debt-proposal"),
        ("debt_repayment_proposal", "shared-debt-proposal"),
    }


def test_merchant_alias_receipts_remain_exportable_after_the_catalog_row_is_deleted(records):
    for id_, operation, ledger in ((1, "update_merchant_alias", "selected"),
        (2, "delete_merchant_alias", "selected"), (3, "delete_merchant_alias", "other")):
        _seed(records, m.ApiIdempotencyKey, id=id_, tenant_id=ledger, status="succeeded",
            resource_type="merchant_alias", resource_id="deleted-alias", operation=operation)
    assert [(row["id"], row["operation"]) for row in _rows(records, "accepted_operations")] == [
        (1, "update_merchant_alias"), (2, "delete_merchant_alias")]
