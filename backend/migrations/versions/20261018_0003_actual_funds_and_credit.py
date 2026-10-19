"""Actual funds accounts, native credit draws and one atomic settlement source."""
import sqlalchemy as sa
from alembic import op

revision = "20261018_0003"
down_revision = "20261018_0002"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision = :target WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the funds migration edge")


def upgrade():
    op.execute("CREATE TABLE financial_accounts (\n\tid SERIAL NOT NULL, \n\tpublic_id VARCHAR(36) NOT NULL, \n\ttenant_id VARCHAR(64) NOT NULL, \n\towner_account_id INTEGER NOT NULL, \n\tname VARCHAR(120) NOT NULL, \n\tkind VARCHAR(12) NOT NULL, \n\tcurrency_code VARCHAR(3) NOT NULL, \n\tvisibility VARCHAR(12) NOT NULL, \n\tinstitution VARCHAR(120), \n\ttail VARCHAR(4), \n\tcredit_limit_minor BIGINT, \n\tavailable_credit_minor BIGINT, \n\tcredit_observed_on DATE, \n\tcredit_source VARCHAR(255), \n\tstatement_day INTEGER, \n\tpayment_due_day INTEGER, \n\tbalance_known BOOLEAN NOT NULL, \n\topening_date DATE NOT NULL, \n\topening_source VARCHAR(255) NOT NULL, \n\tarchived_at TIMESTAMP WITH TIME ZONE, \n\trow_version INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_financial_accounts_available_credit_minor_money_bounds CHECK (available_credit_minor IS NULL OR (available_credit_minor BETWEEN 0 AND 9000000000000)), \n\tCONSTRAINT ck_financial_accounts_credit_limit_minor_money_bounds CHECK (credit_limit_minor IS NULL OR (credit_limit_minor BETWEEN 0 AND 9000000000000)), \n\tCONSTRAINT ck_financial_accounts_kind CHECK (kind IN ('cash','bank','wallet','credit')), \n\tCONSTRAINT ck_financial_accounts_visibility CHECK (visibility IN ('private','ledger')), \n\tCONSTRAINT ck_financial_accounts_version CHECK (row_version > 0), \n\tCONSTRAINT ck_financial_accounts_tail CHECK (tail IS NULL OR length(tail) BETWEEN 1 AND 4), \n\tCONSTRAINT ck_financial_accounts_statement_day CHECK (statement_day IS NULL OR statement_day BETWEEN 1 AND 31), \n\tCONSTRAINT ck_financial_accounts_due_day CHECK (payment_due_day IS NULL OR payment_due_day BETWEEN 1 AND 31), \n\tUNIQUE (public_id), \n\tFOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id), \n\tFOREIGN KEY(owner_account_id) REFERENCES accounts (id)\n)")
    op.execute('CREATE INDEX ix_financial_accounts_owner_account_id ON financial_accounts (owner_account_id)')
    op.execute('CREATE INDEX ix_financial_accounts_tenant_id ON financial_accounts (tenant_id)')
    op.execute('CREATE TABLE credit_facilities (\n\tid SERIAL NOT NULL, \n\taccount_id INTEGER NOT NULL, \n\tdebt_id INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (account_id), \n\tFOREIGN KEY(account_id) REFERENCES financial_accounts (id), \n\tUNIQUE (debt_id), \n\tFOREIGN KEY(debt_id) REFERENCES debts (id)\n)')
    op.execute('CREATE TABLE expense_funding (\n\tid SERIAL NOT NULL, \n\ttenant_id VARCHAR(64) NOT NULL, \n\texpense_id INTEGER NOT NULL, \n\taccount_id INTEGER NOT NULL, \n\tcomponent_id VARCHAR(36) NOT NULL, \n\texpense_amount_minor BIGINT NOT NULL, \n\taccount_amount_minor BIGINT NOT NULL, \n\texpense_row_version INTEGER NOT NULL, \n\tactor_account_id INTEGER NOT NULL, \n\tincluded_in_opening BOOLEAN NOT NULL, \n\tvoided_at TIMESTAMP WITH TIME ZONE, \n\tvoid_reason VARCHAR(500), \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_expense_funding_account_amount_minor_money_bounds CHECK (account_amount_minor BETWEEN 1 AND 9000000000000), \n\tCONSTRAINT ck_expense_funding_expense_amount_minor_money_bounds CHECK (expense_amount_minor BETWEEN 1 AND 9000000000000), \n\tCONSTRAINT uq_expense_funding_component UNIQUE (expense_id, expense_row_version, component_id), \n\tFOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id), \n\tFOREIGN KEY(expense_id) REFERENCES expenses (id), \n\tFOREIGN KEY(account_id) REFERENCES financial_accounts (id), \n\tFOREIGN KEY(actor_account_id) REFERENCES accounts (id)\n)')
    op.execute('CREATE INDEX ix_expense_funding_expense_id ON expense_funding (expense_id)')
    op.execute("CREATE TABLE account_movements (\n\tid SERIAL NOT NULL, \n\tpublic_id VARCHAR(36) NOT NULL, \n\ttenant_id VARCHAR(64) NOT NULL, \n\taccount_id INTEGER NOT NULL, \n\tevent_public_id VARCHAR(36) NOT NULL, \n\tcomponent_id VARCHAR(36) NOT NULL, \n\tkind VARCHAR(20) NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\thome_amount_cents BIGINT, \n\thome_currency_code VARCHAR(3) NOT NULL, \n\tvaluation_snapshot JSON, \n\tsettlement_targets JSON, \n\toccurred_on DATE NOT NULL, \n\tnote VARCHAR(255) NOT NULL, \n\tactor_account_id INTEGER NOT NULL, \n\tfunding_id INTEGER, \n\trepayment_id INTEGER, \n\toffset_id INTEGER, \n\tdebt_id INTEGER, \n\treversal_of_id INTEGER, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_account_movements_amount_minor_money_bounds CHECK (amount_minor BETWEEN -9000000000000 AND 9000000000000), \n\tCONSTRAINT ck_account_movements_home_amount_cents_money_bounds CHECK (home_amount_cents IS NULL OR (home_amount_cents BETWEEN -9000000000000 AND 9000000000000)), \n\tCONSTRAINT uq_account_movement_event_component UNIQUE (event_public_id, component_id), \n\tCONSTRAINT uq_account_movement_funding UNIQUE (funding_id), \n\tCONSTRAINT uq_account_movement_reversal UNIQUE (reversal_of_id), \n\tCONSTRAINT ck_account_movement_kind CHECK (kind IN ('opening','expense','credit_draw','repayment','income','loan','transfer','refund','reconciliation','reversal')), \n\tUNIQUE (public_id), \n\tFOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id), \n\tFOREIGN KEY(account_id) REFERENCES financial_accounts (id), \n\tFOREIGN KEY(actor_account_id) REFERENCES accounts (id), \n\tFOREIGN KEY(funding_id) REFERENCES expense_funding (id), \n\tFOREIGN KEY(repayment_id) REFERENCES repayments (id), \n\tFOREIGN KEY(offset_id) REFERENCES expense_offset_facts (id), \n\tFOREIGN KEY(debt_id) REFERENCES debts (id), \n\tFOREIGN KEY(reversal_of_id) REFERENCES account_movements (id)\n)")
    op.execute('CREATE INDEX ix_account_movements_account_id ON account_movements (account_id)')
    op.execute('CREATE INDEX ix_account_movements_event_public_id ON account_movements (event_public_id)')
    op.execute('CREATE INDEX ix_account_movements_repayment_id ON account_movements (repayment_id)')
    op.execute('CREATE TABLE credit_settlement_allocations (\n\tid SERIAL NOT NULL, \n\trepayment_id INTEGER, \n\tcredit_movement_id INTEGER NOT NULL, \n\tdraw_movement_id INTEGER NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\thome_amount_cents BIGINT, \n\tinvalidated_by_movement_id INTEGER, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_credit_settlement_allocations_amount_minor_money_bounds CHECK (amount_minor BETWEEN 1 AND 9000000000000), \n\tCONSTRAINT ck_credit_settlement_allocations_home_amount_cents_money_bounds CHECK (home_amount_cents IS NULL OR (home_amount_cents BETWEEN 0 AND 9000000000000)), \n\tFOREIGN KEY(repayment_id) REFERENCES repayments (id), \n\tFOREIGN KEY(credit_movement_id) REFERENCES account_movements (id), \n\tFOREIGN KEY(draw_movement_id) REFERENCES account_movements (id), \n\tFOREIGN KEY(invalidated_by_movement_id) REFERENCES account_movements (id)\n)')
    op.execute('CREATE TABLE account_balance_observations (\n\tid SERIAL NOT NULL, \n\taccount_id INTEGER NOT NULL, \n\tobserved_minor BIGINT NOT NULL, \n\trecorded_minor BIGINT NOT NULL, \n\toccurred_on DATE NOT NULL, \n\tsource VARCHAR(255) NOT NULL, \n\tadjustment_movement_id INTEGER, \n\tactor_account_id INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_account_balance_observations_observed_minor_money_bounds CHECK (observed_minor BETWEEN -9000000000000 AND 9000000000000), \n\tCONSTRAINT ck_account_balance_observations_recorded_minor_money_bounds CHECK (recorded_minor BETWEEN -9000000000000 AND 9000000000000), \n\tFOREIGN KEY(account_id) REFERENCES financial_accounts (id), \n\tUNIQUE (adjustment_movement_id), \n\tFOREIGN KEY(adjustment_movement_id) REFERENCES account_movements (id), \n\tFOREIGN KEY(actor_account_id) REFERENCES accounts (id)\n)')
    op.execute('CREATE INDEX ix_account_balance_observations_account_id ON account_balance_observations (account_id)')
    op.execute('CREATE TABLE installment_agreements (\n\tid SERIAL NOT NULL, \n\tpublic_id VARCHAR(36) NOT NULL, \n\taccount_id INTEGER NOT NULL, \n\tseries_id VARCHAR(36) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tsupersedes_id INTEGER, \n\tname VARCHAR(120) NOT NULL, \n\tsource VARCHAR(500) NOT NULL, \n\tagreed_on DATE NOT NULL, \n\tactor_account_id INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_installment_revision UNIQUE (series_id, revision), \n\tUNIQUE (public_id), \n\tFOREIGN KEY(account_id) REFERENCES financial_accounts (id), \n\tUNIQUE (supersedes_id), \n\tFOREIGN KEY(supersedes_id) REFERENCES installment_agreements (id), \n\tFOREIGN KEY(actor_account_id) REFERENCES accounts (id)\n)')
    op.execute('CREATE INDEX ix_installment_agreements_account_id ON installment_agreements (account_id)')
    op.execute('CREATE TABLE installment_draws (\n\tid SERIAL NOT NULL, \n\tagreement_id INTEGER NOT NULL, \n\tmovement_id INTEGER NOT NULL, \n\tprincipal_minor BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_installment_draws_principal_minor_money_bounds CHECK (principal_minor BETWEEN 1 AND 9000000000000), \n\tCONSTRAINT uq_installment_draw UNIQUE (agreement_id, movement_id), \n\tFOREIGN KEY(agreement_id) REFERENCES installment_agreements (id), \n\tFOREIGN KEY(movement_id) REFERENCES account_movements (id)\n)')
    op.execute('CREATE TABLE installment_periods (\n\tid SERIAL NOT NULL, \n\tpublic_id VARCHAR(36) NOT NULL, \n\tagreement_id INTEGER NOT NULL, \n\tposition INTEGER NOT NULL, \n\tdue_on DATE NOT NULL, \n\tprincipal_minor BIGINT NOT NULL, \n\tplanned_fee_minor BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_installment_periods_planned_fee_minor_money_bounds CHECK (planned_fee_minor BETWEEN 0 AND 9000000000000), \n\tCONSTRAINT ck_installment_periods_principal_minor_money_bounds CHECK (principal_minor BETWEEN 1 AND 9000000000000), \n\tCONSTRAINT uq_installment_period_position UNIQUE (agreement_id, position), \n\tUNIQUE (public_id), \n\tFOREIGN KEY(agreement_id) REFERENCES installment_agreements (id)\n)')
    op.execute('CREATE TABLE installment_payments (\n\tid SERIAL NOT NULL, \n\tperiod_id INTEGER NOT NULL, \n\trepayment_id INTEGER NOT NULL, \n\tprincipal_minor BIGINT NOT NULL, \n\tfee_minor BIGINT NOT NULL, \n\tfee_expense_id INTEGER, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_installment_payments_fee_minor_money_bounds CHECK (fee_minor BETWEEN 0 AND 9000000000000), \n\tCONSTRAINT ck_installment_payments_principal_minor_money_bounds CHECK (principal_minor BETWEEN 0 AND 9000000000000), \n\tCONSTRAINT ck_installment_payment_nonempty CHECK (principal_minor > 0 OR fee_minor > 0), \n\tCONSTRAINT uq_installment_payment UNIQUE (period_id, repayment_id), \n\tFOREIGN KEY(period_id) REFERENCES installment_periods (id), \n\tFOREIGN KEY(repayment_id) REFERENCES repayments (id), \n\tFOREIGN KEY(fee_expense_id) REFERENCES expenses (id)\n)')
    op.drop_constraint('ck_debts_source_type_valid', "debts", type_="check")
    op.create_check_constraint('ck_debts_source_type_valid', "debts", "source_type IN ('manual', 'bill_split', 'bill_split_return', 'credit_facility')")
    op.drop_constraint('ck_debts_bill_split_has_source_id', "debts", type_="check")
    op.create_check_constraint('ck_debts_bill_split_has_source_id', "debts", "(source_type IN ('bill_split', 'bill_split_return', 'credit_facility')) = (source_id IS NOT NULL)")
    op.drop_constraint('ck_debts_principal_amount_cents_money_bounds', "debts", type_="check")
    op.create_check_constraint('ck_debts_principal_amount_cents_money_bounds', "debts", "principal_amount_cents BETWEEN 0 AND 9000000000000 AND (source_type = 'credit_facility' OR principal_amount_cents > 0)")
    op.drop_constraint('ck_debts_original_amount_minor_money_bounds', "debts", type_="check")
    op.create_check_constraint('ck_debts_original_amount_minor_money_bounds', "debts", "original_amount_minor IS NULL OR (original_amount_minor BETWEEN 0 AND 9000000000000 AND (source_type = 'credit_facility' OR original_amount_minor > 0))")
    op.add_column("repayments", sa.Column("settlement_kind", sa.String(12), nullable=False, server_default="ordinary"))
    op.create_check_constraint('ck_repayments_settlement_kind', "repayments", "settlement_kind IN ('ordinary', 'credit')")
    op.create_check_constraint('ck_repayments_credit_native_amount', "repayments", "settlement_kind != 'credit' OR (original_currency_code IS NOT NULL AND original_amount_minor IS NOT NULL)")
    op.drop_constraint('ck_repayments_amount_cents_money_bounds', "repayments", type_="check")
    op.create_check_constraint('ck_repayments_amount_cents_money_bounds', "repayments", "amount_cents BETWEEN 0 AND 9000000000000 AND (settlement_kind = 'credit' OR amount_cents > 0)")
    op.drop_constraint('ck_repayments_original_amount_minor_money_bounds', "repayments", type_="check")
    op.create_check_constraint('ck_repayments_original_amount_minor_money_bounds', "repayments", "original_amount_minor IS NULL OR (original_amount_minor BETWEEN 0 AND 9000000000000 AND (settlement_kind = 'credit' OR original_amount_minor > 0))")
    _set_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if any(bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM " + table + ")")) for table in
        ('financial_accounts', 'credit_facilities', 'expense_funding', 'account_movements', 'credit_settlement_allocations', 'account_balance_observations', 'installment_agreements', 'installment_draws', 'installment_periods', 'installment_payments')):
        raise RuntimeError("cannot erase actual funds or credit facts; retain a supported reader")
    for table in ('installment_payments', 'installment_periods', 'installment_draws', 'installment_agreements', 'account_balance_observations', 'credit_settlement_allocations', 'account_movements', 'expense_funding', 'credit_facilities', 'financial_accounts'):
        op.drop_table(table)
    op.drop_constraint('ck_debts_source_type_valid', "debts", type_="check")
    op.create_check_constraint('ck_debts_source_type_valid', "debts", "source_type IN ('manual', 'bill_split', 'bill_split_return')")
    op.drop_constraint('ck_debts_bill_split_has_source_id', "debts", type_="check")
    op.create_check_constraint('ck_debts_bill_split_has_source_id', "debts", "(source_type IN ('bill_split', 'bill_split_return')) = (source_id IS NOT NULL)")
    op.drop_constraint('ck_debts_principal_amount_cents_money_bounds', "debts", type_="check")
    op.create_check_constraint('ck_debts_principal_amount_cents_money_bounds', "debts", 'principal_amount_cents BETWEEN 1 AND 9000000000000')
    op.drop_constraint('ck_debts_original_amount_minor_money_bounds', "debts", type_="check")
    op.create_check_constraint('ck_debts_original_amount_minor_money_bounds', "debts", 'original_amount_minor IS NULL OR (original_amount_minor BETWEEN 1 AND 9000000000000)')
    op.drop_constraint('ck_repayments_amount_cents_money_bounds', "repayments", type_="check")
    op.create_check_constraint('ck_repayments_amount_cents_money_bounds', "repayments", 'amount_cents BETWEEN 1 AND 9000000000000')
    op.drop_constraint('ck_repayments_original_amount_minor_money_bounds', "repayments", type_="check")
    op.create_check_constraint('ck_repayments_original_amount_minor_money_bounds', "repayments", 'original_amount_minor IS NULL OR (original_amount_minor BETWEEN 1 AND 9000000000000)')
    op.drop_constraint("ck_repayments_credit_native_amount", "repayments", type_="check")
    op.drop_constraint("ck_repayments_settlement_kind", "repayments", type_="check")
    op.drop_column("repayments", "settlement_kind")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    for table in ('financial_accounts', 'credit_facilities', 'expense_funding', 'account_movements', 'credit_settlement_allocations', 'account_balance_observations', 'installment_agreements', 'installment_draws', 'installment_periods', 'installment_payments'):
        if not inspector.has_table(table):
            raise RuntimeError("funds schema is incomplete: " + table)
    if not {"account_id", "debt_id"} <= {column for item in inspector.get_unique_constraints("credit_facilities") for column in item["column_names"]}:
        raise RuntimeError("credit facility must have one account and one Debt")
