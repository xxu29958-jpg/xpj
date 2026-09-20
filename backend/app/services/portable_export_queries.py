"""Audited, read-only record projections for one ledger's portable outlet.

This is a fixed product inventory, not ORM/database enumeration. New model fields
are not exported implicitly. The caller authenticates current membership and
executes every SELECT in its one read snapshot; no domain writer or fold runs here.
Account-scoped relationship collections are named separately from ledger facts.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Select, and_, case, func, or_, select, union
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app import models as m
from app.database_model_registry import Base
from app.services.permission_service import can_manage_members
from app.tenants import AuthContext

# These explicit fields have been reviewed as ledger business records. Retained
# inactive states are intentionally unrestricted. Runtime CSV claims are omitted;
# source cells, errors, captured interpretation and accepted mappings are retained.
_LEDGER_RECORDS = (
    (m.Expense, "id tenant_id public_id amount_cents home_currency_code original_currency_code "
        "original_amount_minor exchange_rate_to_cny exchange_rate_date exchange_rate_source fx_status "
        "merchant category note source image_path thumbnail_path image_hash image_perceptual_hash raw_text "
        "confidence ocr_draft_fields draft_idempotency_key draft_request_fingerprint duplicate_status "
        "duplicate_of_id duplicate_reason tags value_score regret_score status expense_time accounting_date "
        "calendar_revision user_local_date time_precision source_timezone source_utc_offset_seconds "
        "accounting_date_basis created_at updated_at row_version fact_revision confirmed_at rejected_at "
        "image_deleted_at thumbnail_deleted_at attachment_cleanup_request image_replenished_at "
        "items_sum_status split_origin_invitation_id"),
    (m.ExpenseItem, "id public_id tenant_id expense_id position kind name quantity_text unit_price_cents "
        "amount_cents category raw_text confidence is_ocr_draft created_at updated_at"),
    (m.ExpenseSplit, "id public_id tenant_id expense_id member_id position amount_cents note created_at updated_at"),
    (m.ExpenseTag, "id tenant_id expense_id tag_id created_at"),
    (m.ExpenseRevision, "id public_id tenant_id expense_id revision_number change_kind reason idempotency_key "
        "actor_account_id actor_device_public_id actor_device_name changed_fields before_snapshot after_snapshot "
        "previous_row_version resulting_row_version created_at"),
    (m.ExpenseOffsetFact, "id public_id tenant_id expense_id kind status original_currency_code original_amount_minor "
        "home_currency_code amount_cents exchange_rate_to_cny exchange_rate_date exchange_rate_source accounting_date "
        "calendar_revision user_local_date time_precision source_timezone source_utc_offset_seconds accounting_date_basis "
        "category reason row_version fact_revision created_actor_account_id created_device_public_id created_device_name "
        "created_at updated_at voided_at"),
    (m.ExpenseOffsetRevision, "id public_id tenant_id expense_id offset_id revision_number change_kind reason "
        "idempotency_key actor_account_id actor_device_public_id actor_device_name before_snapshot after_snapshot "
        "previous_row_version resulting_row_version created_at"),
    (m.CsvImportBatch, "id public_id tenant_id file_name calendar_revision status total_rows valid_rows error_rows "
        "applied_rows inserted_count last_error created_at updated_at applied_at"),
    (m.CsvImportRow, "id tenant_id batch_id line_number status error_code error_message entry_kind offset_kind "
        "source_event_public_id source_root_public_id accounting_date stream_amount_cents lineage_status "
        "lineage_home_net_cents event_input time_input expense_time_input review_reason amount_cents home_currency_code "
        "original_currency_code original_amount_minor exchange_rate_to_cny exchange_rate_date exchange_rate_source "
        "merchant category note expense_time tags source expense_id created_at updated_at"),
    (m.CsvImportEvent, "id tenant_id entry_kind source_event_public_id source_row_id expense_id offset_id created_at"),
    (m.Budget, "id public_id tenant_id month home_currency_code total_amount_cents non_monthly_amount_cents "
        "rollover_amount_cents excluded_categories created_at updated_at row_version archived_at"),
    (m.BudgetCategory, "id public_id tenant_id month category amount_cents created_at updated_at"),
    (m.Goal, "id public_id tenant_id name goal_type period month category target_amount_cents home_currency_code "
        "status created_at updated_at row_version archived_at goal_version achieved_at achieved_version "
        "integrity_reviewed_version target_date"),
    (m.MonthlyIncomePlan, "id public_id tenant_id label source_type frequency income_month home_currency_code "
        "amount_cents pay_day status created_at updated_at row_version archived_at"),
    (m.IncomePlanRevision, "id tenant_id plan_id revision_number effective_month intent_month change_kind label "
        "source_type frequency income_month home_currency_code amount_cents pay_day status actor_account_id recorded_at"),
    (m.RecurringItem, "id public_id tenant_id merchant_key merchant_name frequency home_currency_code baseline_amount_cents "
        "last_amount_cents occurrence_count last_seen_at next_expected_date status confidence source created_at updated_at "
        "row_version paused_at archived_at"),
    (m.RecurringOccurrence, "tenant_id series_id period_start expense_id row_version updated_at"),
    (m.RecurringOccurrenceRevision, "id tenant_id series_id period_start revision_number previous_expense_id "
        "expense_id actor_account_id idempotency_key created_at"),
    (m.MerchantAlias, "id public_id tenant_id canonical_merchant canonical_key alias alias_key enabled created_at "
        "updated_at row_version deleted_at"),
    (m.MerchantCatalog, "id public_id tenant_id display_name merchant_key status merged_into_public_id created_at "
        "updated_at row_version deleted_at"),
    (m.CategoryPreference, "id public_id tenant_id name key kind created_at updated_at row_version deleted_at"),
    (m.Tag, "id public_id tenant_id name key created_at updated_at row_version deleted_at"),
    (m.TagMutationUndoGroup, "id mutation_public_id tenant_id op source_tag_public_id source_tag_name "
        "target_tag_public_id target_tag_name created_at consumed_at"),
    (m.TagMutationUndoItem, "id tenant_id group_id expense_public_id original_tags original_tag_ids original_row_version created_at"),
    (m.DuplicateIgnore, "id tenant_id expense_id duplicate_of_id kind created_at"),
    (m.CategoryRule, "id tenant_id keyword category enabled priority amount_min_cents amount_max_cents home_currency_code "
        "source_contains tag_contains created_at updated_at row_version deleted_at"),
    (m.RuleApplicationBatch, "id public_id tenant_id status pending_scanned changed_count actor_account_id "
        "actor_device_id created_at rolled_back_at"),
    (m.RuleApplicationChange, "id public_id tenant_id batch_id expense_id rule_id matched_keyword before_category "
        "after_category status created_at rolled_back_at"),
    (m.DashboardCardPreference, "id public_id tenant_id surface card_key position visible created_at updated_at"),
    (m.ExchangeRate, "id public_id tenant_id currency_code home_currency_code rate_date rate_to_cny source "
        "created_at updated_at row_version"),
    (m.OcrFact, "id public_id tenant_id expense_id ocr_provider ocr_model raw_text parsed_amount_cents "
        "parsed_merchant parsed_category parsed_expense_time parse_confidence extracted_at created_at retention_days"),
    (m.AlgorithmDecision, "id public_id tenant_id decision_type algorithm_version subject_kind subject_id "
        "subject_public_id score output_payload status superseded_by_id created_at retention_days"),
    (m.LedgerLearningEvent, "id public_id tenant_id decision_id event_type actor_account_id subject_kind subject_id "
        "before_payload after_payload signal_type signal_hash signal_payload created_at retention_days"),
    (m.Debt, "id public_id tenant_id owner_account_id created_by_account_id direction counterparty_type "
        "counterparty_account_id counterparty_label note principal_amount_cents home_currency_code original_currency_code "
        "original_amount_minor exchange_rate_to_cny exchange_rate_date exchange_rate_source status debt_kind "
        "installment_count installment_period_months source_type source_id created_at updated_at row_version"),
)

_DEBT_CHILDREN = (
    (m.Repayment, "id public_id debt_id amount_cents original_currency_code original_amount_minor exchange_rate_to_cny "
        "exchange_rate_date exchange_rate_source paid_at actor_account_id proposal_id idempotency_key created_at"),
    (m.DebtAdjustment, "id public_id debt_id amount_cents reason actor_account_id idempotency_key created_at"),
    (m.DebtVoid, "id public_id debt_id reason actor_account_id idempotency_key created_at"),
    (m.DebtForgiveness, "id public_id debt_id amount_cents actor_account_id idempotency_key created_at"),
    (m.MemberRepaymentProposal, "id public_id debt_id debtor_account_id creditor_account_id proposed_by_account_id "
        "proposed_amount_cents home_currency_code original_currency_code original_amount_minor exchange_rate_to_cny "
        "exchange_rate_date exchange_rate_source paid_at note status confirmed_amount_cents committed_repayment_id "
        "supersedes_proposal_id idempotency_key created_at expires_at resolved_at resolved_by_account_id"),
)

_SPLIT_SNAPSHOT_FIELDS = (
    "public_id status amount_cents home_currency_code original_currency_code original_amount_minor exchange_rate_to_cny "
    "exchange_rate_date exchange_rate_source merchant_snapshot category_suggestion expense_time_snapshot "
    "accounting_time_snapshot expires_at created_at accepted_at rejected_at cancelled_at cancellation_reason_code expired_at"
)


def _record(model: type[Base], fields: str, predicate: ColumnElement[bool]) -> Select:
    table = model.__table__
    return select(*(table.c[field] for field in fields.split())).where(predicate).order_by(*table.primary_key.columns)


def _owned_drafts(auth: AuthContext) -> ColumnElement[bool]:
    return and_(m.RepaymentDraft.tenant_id == auth.ledger_id, m.RepaymentDraft.created_by_account_id == auth.account_id)


def _sent(auth: AuthContext) -> ColumnElement[bool]:
    return and_(m.BillSplitInvitation.sender_ledger_id == auth.ledger_id,
        m.BillSplitInvitation.sender_account_id == auth.account_id)


def _ledger_relationships(auth: AuthContext) -> tuple[tuple[str, Select], ...]:
    debts = select(m.Debt.id).where(m.Debt.tenant_id == auth.ledger_id)
    repayments = select(m.Repayment.id).where(m.Repayment.debt_id.in_(debts))
    children = tuple((model.__tablename__, _record(model, fields, model.debt_id.in_(debts)))
        for model, fields in _DEBT_CHILDREN)
    return (*children,
        ("repayment_voids", _record(m.RepaymentVoid,
            "id public_id repayment_id reason actor_account_id idempotency_key created_at",
            m.RepaymentVoid.repayment_id.in_(repayments))),
        ("debt_goal_links", _record(m.DebtGoalLink, "id goal_id goal_version debt_id created_at",
            m.DebtGoalLink.goal_id.in_(select(m.Goal.id).where(m.Goal.tenant_id == auth.ledger_id)))),
        ("repayment_drafts", _record(m.RepaymentDraft, "id public_id tenant_id created_by_account_id source "
            "amount_cents home_currency_code merchant_label captured_at draft_idempotency_key status "
            "committed_debt_public_id committed_repayment_public_id resolved_at resolved_by_account_id created_at",
            _owned_drafts(auth))),
    )


def _split_queries(auth: AuthContext) -> tuple[tuple[str, Select], ...]:
    invitation = m.BillSplitInvitation
    debt_id = select(m.Debt.public_id).where(m.Debt.source_type == "bill_split",
        m.Debt.source_id == invitation.public_id).scalar_subquery()
    sent = _record(invitation, _SPLIT_SNAPSHOT_FIELDS +
        " receiver_account_id receiver_display_name_snapshot sender_expense_id", _sent(auth))
    inbox = _record(invitation, _SPLIT_SNAPSHOT_FIELDS + " sender_account_id sender_display_name",
        invitation.receiver_account_id == auth.account_id).add_columns(case(
            (and_(invitation.receiver_ledger_id == auth.ledger_id, invitation.status == "accepted"),
                invitation.received_expense_id),
            else_=None).label("local_received_expense_id"))
    source_links = select(invitation.public_id.label("invitation_public_id"), invitation.sender_expense_id,
        invitation.receiver_display_name_snapshot, invitation.amount_cents.label("agreed_share_home_minor"),
        debt_id.label("debt_public_id")).where(invitation.sender_ledger_id == auth.ledger_id,
            invitation.status == "accepted").order_by(invitation.id)
    return (("bill_split_sent", sent), ("account_bill_split_inbox", inbox),
        ("bill_split_source_relationships", source_links))


def _participant_queries(auth: AuthContext) -> tuple[tuple[str, Select], ...]:
    """The existing participant DTO fields, never the other ledger's private rows.

    No balance fold is reconstructed: these are retained shared snapshots/events.
    Internal IDs are replaced with public relationship references at this edge.
    """
    debt = m.Debt
    participant = _cross_ledger_participant(auth)
    ids = select(debt.id).where(participant)
    owner_name = select(m.Account.display_name).where(m.Account.id == debt.owner_account_id).scalar_subquery()
    debts = _record(debt, "public_id direction counterparty_type counterparty_account_id note principal_amount_cents "
        "home_currency_code original_currency_code original_amount_minor exchange_rate_to_cny exchange_rate_date "
        "exchange_rate_source status debt_kind installment_count installment_period_months source_type source_id "
        "created_at updated_at row_version", participant).add_columns(owner_name.label("counterparty_label"))
    repayment = m.Repayment
    debt_public_id = select(debt.public_id).where(debt.id == repayment.debt_id).scalar_subquery()
    repayments = _record(repayment, "public_id amount_cents original_currency_code original_amount_minor "
        "exchange_rate_to_cny exchange_rate_date exchange_rate_source paid_at created_at",
        repayment.debt_id.in_(ids)).add_columns(debt_public_id.label("debt_public_id"))
    voids = _record(m.RepaymentVoid, "public_id reason created_at", m.RepaymentVoid.repayment_id.in_(
        select(repayment.id).where(repayment.debt_id.in_(ids)))).add_columns(select(repayment.public_id).where(
            repayment.id == m.RepaymentVoid.repayment_id).scalar_subquery().label("repayment_public_id"))
    proposal = m.MemberRepaymentProposal
    previous = proposal.__table__.alias("previous_proposal")
    proposals = _record(proposal, "public_id status proposed_amount_cents confirmed_amount_cents home_currency_code "
        "original_currency_code original_amount_minor paid_at note expires_at created_at resolved_at",
        proposal.debt_id.in_(ids)).add_columns(
            select(debt.public_id).where(debt.id == proposal.debt_id).scalar_subquery().label("debt_public_id"),
            select(previous.c.public_id).where(previous.c.id == proposal.supersedes_proposal_id)
                .scalar_subquery().label("supersedes_proposal_public_id"),
            select(repayment.public_id).where(repayment.id == proposal.committed_repayment_id)
                .scalar_subquery().label("committed_repayment_public_id"))
    return (("account_debt_relationships", debts), ("account_repayments", repayments),
        ("account_repayment_voids", voids), ("account_repayment_proposals", proposals))


def _cross_ledger_participant(auth: AuthContext) -> ColumnElement[bool]:
    return and_(m.Debt.tenant_id != auth.ledger_id, m.Debt.counterparty_account_id == auth.account_id)


def _split_agreement_queries(auth: AuthContext) -> tuple[tuple[str, Select], ...]:
    """Shared agreement history follows the original Debt's read boundary.

    Public links join the selected ledger's facts or its participant shells;
    they never authorize a private expense, ledger or adjustment-row export.
    """
    proposal = m.BillSplitChangeProposal
    change = m.BillSplitAgreementChange
    proposal_fields = ("public_id status original_debt_row_version return_debt_row_version "
        "share_before_amount_cents new_share_amount_cents settlement_before_net_amount_cents "
        "settlement_net_amount_cents original_paid_amount_cents return_paid_amount_cents "
        "original_forgiven_amount_cents return_forgiven_amount_cents reason created_at expires_at resolved_at")
    change_fields = "public_id share_before_amount_cents new_share_amount_cents settlement_net_amount_cents created_at"

    def reference(model, foreign_key, label):
        return select(model.public_id).where(model.id == foreign_key).scalar_subquery().label(label)

    result = []
    for prefix, visible in (("", m.Debt.tenant_id == auth.ledger_id), ("account_", _cross_ledger_participant(auth))):
        debts = select(m.Debt.id).where(visible)
        for model, fields in ((proposal, proposal_fields), (change, change_fields)):
            query = _record(model, fields, model.original_debt_id.in_(debts)).add_columns(
                reference(m.BillSplitInvitation, model.invitation_id, "invitation_public_id"),
                select(m.BillSplitInvitation.home_currency_code).where(m.BillSplitInvitation.id == model.invitation_id)
                    .scalar_subquery().label("home_currency_code"),
                reference(m.Debt, model.original_debt_id, "original_debt_public_id"),
                reference(m.Debt, model.return_debt_id, "return_debt_public_id"),
                reference(m.Account, model.proposed_by_account_id, "proposed_by_account_public_id"))
            if model is proposal:
                query = query.add_columns(reference(m.Account, proposal.resolved_by_account_id,
                                                    "resolved_by_account_public_id"))
            else:
                query = query.add_columns(reference(proposal, change.proposal_id, "proposal_public_id"),
                    reference(m.Account, change.accepted_by_account_id, "accepted_by_account_public_id"),
                    reference(m.DebtAdjustment, change.original_adjustment_id, "original_adjustment_public_id"),
                    reference(m.DebtAdjustment, change.return_adjustment_id, "return_adjustment_public_id"))
            result.append((prefix + model.__tablename__, query))
    return tuple(result)


def _authorized_debt_receipts(auth: AuthContext) -> ColumnElement[bool]:
    receipt = m.ApiIdempotencyKey
    debts = select(m.Debt.id).where(or_(m.Debt.tenant_id == auth.ledger_id, _cross_ledger_participant(auth)))
    debt = and_(receipt.resource_type == "debt", receipt.resource_id.in_(
        select(m.Debt.public_id).where(m.Debt.id.in_(debts))))
    repayment = and_(receipt.resource_type == "repayment", receipt.resource_id.in_(
        select(m.Repayment.public_id).where(m.Repayment.debt_id.in_(debts))))
    proposal = and_(receipt.resource_type == "debt_repayment_proposal", receipt.resource_id.in_(
        select(m.MemberRepaymentProposal.public_id).where(m.MemberRepaymentProposal.debt_id.in_(debts))))
    return or_(debt, repayment, proposal)


def _accepted_operations(auth: AuthContext) -> Select:
    receipt = m.ApiIdempotencyKey
    # Every listed resource kind is a ledger-shared business result. Private
    # resource results require the same actor predicates as their read owner.
    shared = receipt.resource_type.in_(("expense", "expense_batch", "expense_offset", "monthly_budget", "goal",
        "income_plan", "recurring_item", "recurring_occurrence", "category_rule", "exchange_rate",
        "ledger_calendar_revision", "upload_receipt"))
    debt_relationships = _authorized_debt_receipts(auth)
    drafts = and_(receipt.resource_type == "repayment_draft", receipt.resource_id.in_(
        select(m.RepaymentDraft.public_id).where(_owned_drafts(auth))))
    splits = and_(receipt.resource_type == "bill_split_invitation", receipt.resource_id.in_(
        select(m.BillSplitInvitation.public_id).where(_sent(auth))))
    # Upload receipts name a personal enrichment task. Its exact durable source
    # proves access to the body; other ledger members still retain the accepted
    # business resource/result reference without the private task identifier.
    own_upload_task = select(m.BackgroundTask.id).where(
        m.BackgroundTask.public_id == receipt.response_body["enrichment_task_public_id"].as_string(),
        m.BackgroundTask.tenant_id == auth.ledger_id,
        m.BackgroundTask.initiated_by_account_id == auth.account_id).exists()
    redacted_upload = and_(receipt.resource_type == "upload_receipt", ~own_upload_task)
    return _record(receipt, "id tenant_id idempotency_key operation target_type target_id request_fingerprint "
        "status resource_type resource_id created_at completed_at expires_at",
        and_(receipt.tenant_id == auth.ledger_id, receipt.status == "succeeded",
            or_(shared, debt_relationships, drafts, splits))).add_columns(
            case((redacted_upload, None), else_=receipt.response_body).label("response_body"),
            case((redacted_upload, "personal_task_scope"), else_=None).label("response_body_omission_reason"))


def _history_queries(auth: AuthContext) -> tuple[tuple[str, Select], ...]:
    tasks = _record(m.BackgroundTask, "id public_id tenant_id task_type initiated_by_account_id source_expense_id "
        "status progress_current progress_total progress_message error_code result_summary_json "
        "created_at started_at completed_at last_progress_at cancellation_requested_at",
        and_(m.BackgroundTask.tenant_id == auth.ledger_id, m.BackgroundTask.initiated_by_account_id == auth.account_id))
    queries = (("accepted_operations", _accepted_operations(auth)), ("background_task_observations", tasks))
    if not can_manage_members(auth):
        return queries
    return (*queries,
        ("ledger_audit_logs", _record(m.LedgerAuditLog, "id public_id ledger_id action actor_account_id "
            "target_account_id target_member_id invitation_public_id resource_type resource_public_id "
            "previous_role new_role result detail created_at", m.LedgerAuditLog.ledger_id == auth.ledger_id)),
    )


def _identity_queries(auth: AuthContext, business: tuple[tuple[str, Select], ...]) -> tuple[tuple[str, Select], ...]:
    ledger = _record(m.Ledger, "id ledger_id name owner_account_id created_at archived_at calendar_revision",
        m.Ledger.ledger_id == auth.ledger_id)
    members = _record(m.LedgerMember, "id ledger_id account_id role created_at disabled_at",
        m.LedgerMember.ledger_id == auth.ledger_id)
    calendar = _record(m.LedgerCalendarRevision, "ledger_id revision timezone_name basis adopted_at actor_account_id",
        m.LedgerCalendarRevision.ledger_id == auth.ledger_id)
    # Resolve only identity references already exposed by these authorized
    # projections. Do not enumerate accounts, other memberships or devices.
    references = {"account_id", "owner_account_id", "created_by_account_id", "actor_account_id",
        "target_account_id", "created_actor_account_id", "counterparty_account_id", "sender_account_id",
        "receiver_account_id", "debtor_account_id", "creditor_account_id", "proposed_by_account_id",
        "resolved_by_account_id", "initiated_by_account_id"}
    account_ids = []
    for _, query in (*business, ("ledger", ledger), ("members", members), ("calendar", calendar)):
        rows = query.order_by(None).subquery()
        account_ids.extend(select(rows.c[field]) for field in sorted(references.intersection(rows.c.keys())))
    accounts = _record(m.Account, "id public_id display_name", m.Account.id.in_(union(*account_ids)))
    devices = _record(m.Device, "id public_id device_name", m.Device.id.in_(select(m.RuleApplicationBatch.actor_device_id)
        .where(m.RuleApplicationBatch.tenant_id == auth.ledger_id)))
    currency = _record(m.InstallationCurrencyBinding,
        "state home_currency_code minor_unit_exponent rounding_mode currency_contract_version binding_revision provenance "
        "evidence_sha256 created_at updated_at activated_at", m.InstallationCurrencyBinding.singleton_id == 1)
    return (("ledgers", ledger), ("ledger_members", members), ("accounts", accounts), ("device_references", devices),
        ("ledger_calendar_revisions", calendar), ("currency_interpretation", currency))


def portable_queries(auth: AuthContext) -> tuple[tuple[str, Select], ...]:
    """Return explicit mapping SELECTs after the caller's normal read authorization.

    No pagination, current-month/default status filters, writes, secret settings,
    credentials or executable task inputs are part of this record inventory.
    Original storage references are internal input to the package owner, which
    substitutes package reference IDs before serializing any user-facing record.
    """
    business = (
        *((model.__tablename__, _record(model, fields, model.tenant_id == auth.ledger_id))
            for model, fields in _LEDGER_RECORDS),
        *_ledger_relationships(auth), *_split_queries(auth), *_split_agreement_queries(auth),
        *_participant_queries(auth), *_history_queries(auth),
    )
    return (*_identity_queries(auth, business), *business)


def _participant_balances(db: Session, auth: AuthContext) -> Iterator[dict[str, object]]:
    from app.services.debt_service import get_participant_debt_response

    fields = ("public_id", "home_currency_code", "principal_amount_cents", "remaining_amount_cents",
        "paid_amount_cents", "status", "is_forgiven", "installment_paid_count", "installment_payoff_date",
        "viewer_is_debtor", "row_version")
    for public_id in db.scalars(select(m.Debt.public_id).where(_cross_ledger_participant(auth)).order_by(m.Debt.id)):
        result = get_participant_debt_response(db, public_id=public_id,
            ledger_id=auth.ledger_id, account_id=auth.account_id)
        yield {field: getattr(result, field) for field in fields}


def portable_projections(db: Session, auth: AuthContext) -> tuple[tuple[str, Iterator[dict[str, object]]], ...]:
    """Read derived participant balances through their existing owner in this snapshot.

    A participant cannot read private adjustments/forgiveness rows, so the public
    shared events alone cannot reconstruct these balances. Failures propagate;
    neither partial answers nor a newly computed export-side fold substitute.
    The caller must consume the iterator before closing its snapshot transaction.
    """
    return (("account_debt_balances", _participant_balances(db, auth)),)


def portable_original_history_query(auth: AuthContext) -> Select:
    """Internal file-copy inputs frozen in authorized accepted expense receipts.

    LEFT JOIN current metadata only to explain observed cleanup/replacement. An
    old receipt's reference and digest remain independent of the current file.
    Paths from this query are never directly serialized into the portable records.
    """
    receipt = _accepted_operations(auth).order_by(None).subquery("accepted_original_receipts")
    body = case((receipt.c.resource_type == "expense_offset", receipt.c.response_body["root"]),
        else_=receipt.c.response_body)
    expense_id = body["id"].as_integer()
    expense_public_id = body["public_id"].as_string()
    image_path = body["image_path"].as_string()
    image_deleted_at = body["image_deleted_at"].as_string()
    # Later retained receipts can prove an earlier reference was cleaned, even
    # after replenishment moved the current attachment to another path.
    historical_image_cleaned = func.max(case((image_deleted_at.is_not(None), 1), else_=0)).over(
        partition_by=(expense_id, expense_public_id, image_path))
    return select(
        receipt.c.id.label("accepted_operation_id"), receipt.c.completed_at.label("accepted_at"),
        expense_id.label("expense_id"), expense_public_id.label("expense_public_id"),
        image_path.label("image_path"), body["image_hash"].as_string().label("image_hash"),
        image_deleted_at.label("image_deleted_at"), historical_image_cleaned.label("historical_image_cleaned"),
        body["thumbnail_path"].as_string().label("thumbnail_path"),
        body["thumbnail_deleted_at"].as_string().label("thumbnail_deleted_at"),
        m.Expense.image_path.label("current_image_path"), m.Expense.thumbnail_path.label("current_thumbnail_path"),
        m.Expense.image_deleted_at.label("current_image_deleted_at"),
        m.Expense.thumbnail_deleted_at.label("current_thumbnail_deleted_at"),
        m.Expense.attachment_cleanup_request, m.Expense.image_replenished_at,
    ).select_from(receipt).outerjoin(m.Expense, and_(m.Expense.tenant_id == auth.ledger_id,
        m.Expense.id == expense_id, m.Expense.public_id == expense_public_id)).where(
            receipt.c.resource_type.in_(("expense", "expense_offset")),
            expense_id.is_not(None),
        ).order_by(receipt.c.id)
