"""Typed commands for actual funds; a missing opening amount means unknown."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas._money import NonNegativeMoneyMinor, PositiveMoneyMinor, SignedMoneyAggregate, SignedMoneyMinor
from app.schemas.credit_fee import CreditFeePaymentPart, CreditFeeView
from app.schemas.installment import CreditDrawPaymentPart, InstallmentPaymentPart
from app.services.currency_common import normalize_currency_code


class CreditTerms(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    credit_limit_minor: NonNegativeMoneyMinor | None = None
    available_credit_minor: NonNegativeMoneyMinor | None = None
    observed_on: date | None = None
    statement_day: int | None = Field(default=None, ge=1, le=31)
    payment_due_day: int | None = Field(default=None, ge=1, le=31)
    source: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_observation(self):
        if (self.credit_limit_minor is not None or self.available_credit_minor is not None) and (not self.observed_on or not self.source):
            raise ValueError("额度请同时填写查询日期与来源")
        return self


class AccountChoice(BaseModel):
    key: str
    name: str
    kind: str
    institution: str


class ExistingDebtChoice(BaseModel):
    public_id: str
    row_version: int
    name: str
    remaining_home_minor: SignedMoneyAggregate
    home_currency_code: str
    earliest_opening_date: date


class DebtAdoption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_id: str = Field(min_length=1, max_length=36)
    expected_row_version: int = Field(ge=1)


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["cash", "bank", "wallet", "credit"]
    currency_code: str
    visibility: Literal["private", "ledger"] = "private"
    institution: str | None = Field(default=None, max_length=120)
    tail: str | None = Field(default=None, pattern=r"^[0-9]{1,4}$")
    opening_amount_minor: SignedMoneyMinor | None = None
    opening_date: date
    opening_source: str = Field(min_length=1, max_length=255)
    credit_terms: CreditTerms | None = None
    existing_debt: DebtAdoption | None = None

    @model_validator(mode="after")
    def adoption_requires_reviewed_credit(self):
        if self.existing_debt is not None and (self.kind != "credit" or self.opening_amount_minor is None):
            raise ValueError("承接已有欠款时，请选择信用账户并核对实际币种与期初欠款，不能留空。")
        return self

    @field_validator("currency_code")
    @classmethod
    def currency(cls, value):
        return normalize_currency_code(value)


class AccountEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    institution: str | None = Field(default=None, max_length=120)
    tail: str | None = Field(default=None, pattern=r"^[0-9]{1,4}$")
    archived: bool = False
    credit_terms: CreditTerms | None = None
    visibility: Literal["private", "ledger"] | None = None


class FundingPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(min_length=1, max_length=36)
    account_public_id: str
    account_row_version: int = Field(ge=1)
    expense_amount_minor: PositiveMoneyMinor
    account_amount_minor: PositiveMoneyMinor
    included_in_opening: bool = False
    expense_currency_code: str | None = None
    account_currency_code: str | None = None

    @field_validator("expense_currency_code", "account_currency_code")
    @classmethod
    def currency(cls, value):
        return normalize_currency_code(value) if value is not None else None


class ExpenseFundingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    parts: list[FundingPart] = Field(min_length=1, max_length=8)
    reason: str = Field(min_length=1, max_length=255)


class FundingViewPart(BaseModel):
    component_id: str
    account_public_id: str | None
    account_row_version: int | None
    account_name: str
    currency_code: str | None
    expense_amount_minor: PositiveMoneyMinor
    account_amount_minor: PositiveMoneyMinor | None
    included_in_opening: bool


class ExpenseFundingView(BaseModel):
    expense_id: int
    expense_row_version: int
    currency_code: str
    total_minor: NonNegativeMoneyMinor | None
    can_edit: bool
    parts: list[FundingViewPart]


class CreditPayment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    calendar_revision: int = Field(ge=1)
    payer_public_id: str
    payer_row_version: int = Field(ge=1)
    principal_minor: NonNegativeMoneyMinor
    payer_amount_minor: NonNegativeMoneyMinor
    occurred_on: date
    note: str = Field(min_length=1, max_length=255)
    fee_payments: list[CreditFeePaymentPart] = Field(default_factory=list, max_length=120)
    payer_fee_amount_minor: NonNegativeMoneyMinor = 0
    new_fee_minor: NonNegativeMoneyMinor = 0
    fee_note: str | None = Field(default=None, max_length=255)
    period_allocations: list[InstallmentPaymentPart] = Field(default_factory=list, max_length=120)
    draw_allocations: list[CreditDrawPaymentPart] = Field(default_factory=list, max_length=120)
    overpayment_minor: NonNegativeMoneyMinor = 0
    source_repayment_draft_id: str | None = Field(default=None, min_length=1, max_length=36)
    source_amount_basis: Literal["payer_total", "principal", "corrected"] = "payer_total"
    source_review_reason: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def require_actual_payment(self):
        if not self.principal_minor and not self.new_fee_minor and not self.fee_payments:
            raise ValueError("请填写实际清偿本金、已记费用或本次新发生费用")
        if bool(self.fee_payments) != bool(self.payer_fee_amount_minor):
            raise ValueError("已记费用的清偿分配和实际扣款须同时填写")
        if bool(self.principal_minor) != bool(self.payer_amount_minor):
            raise ValueError("本金清偿与本金扣款须同时填写；仅付费用时两者填零")
        if self.source_repayment_draft_id is None and (self.source_amount_basis != "payer_total" or self.source_review_reason):
            raise ValueError("通知金额核对必须关联原还款采集")
        return self


class CreditPaymentVoid(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    repayment_public_id: str = Field(min_length=1, max_length=36)
    occurred_on: date
    reason: str = Field(min_length=1, max_length=255)


class AccountPosting(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    kind: Literal["income", "loan", "transfer", "reconciliation"]
    amount_minor: SignedMoneyMinor
    occurred_on: date
    note: str = Field(min_length=1, max_length=255)
    other_account_public_id: str | None = None
    other_account_row_version: int | None = Field(default=None, ge=1)
    other_amount_minor: PositiveMoneyMinor | None = None
    apply_adjustment: bool = False
    loan_name: str | None = Field(default=None, max_length=120)
    loan_currency_code: str | None = None
    loan_principal_minor: PositiveMoneyMinor | None = None
    calendar_revision: int = Field(ge=1)

    @field_validator("loan_currency_code")
    @classmethod
    def loan_currency(cls, value):
        return normalize_currency_code(value) if value else None


class RefundDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_public_id: str
    account_row_version: int = Field(ge=1)
    original_amount_minor: PositiveMoneyMinor
    received_amount_minor: PositiveMoneyMinor


class MovementView(BaseModel):
    public_id: str
    event_public_id: str
    kind: str
    amount_minor: SignedMoneyMinor
    occurred_on: date
    note: str
    expense_id: int | None = None
    repayment_public_id: str | None = None
    debt_public_id: str | None = None
    reversal_of_id: str | None = None
    can_void_repayment: bool = False


class BalanceObservationView(BaseModel):
    observed_minor: SignedMoneyMinor
    recorded_minor: SignedMoneyMinor
    difference_minor: SignedMoneyAggregate
    occurred_on: date
    source: str
    adjusted: bool


class FundsOverview(BaseModel):
    home_currency_code: str
    valuation_date: date
    assets_minor: SignedMoneyAggregate
    liabilities_minor: SignedMoneyAggregate
    net_worth_minor: SignedMoneyAggregate
    included_accounts: int
    unknown_accounts: int
    missing_rate_accounts: int


class FinancialAccountView(BaseModel):
    public_id: str
    name: str
    ledger_id: str
    calendar_revision: int
    kind: str
    currency_code: str
    visibility: str
    institution: str | None
    tail: str | None
    row_version: int
    archived: bool
    balance_minor: SignedMoneyAggregate | None
    recorded_change_minor: SignedMoneyAggregate
    unallocated_credit_minor: SignedMoneyAggregate = 0
    opening_date: date
    opening_source: str
    debt_public_id: str | None = None
    can_edit: bool
    credit_kind: str | None = None
    observation: BalanceObservationView | None = None
    movements: list[MovementView] = Field(default_factory=list)
    fee_obligations: list[CreditFeeView] = Field(default_factory=list)
    credit_terms: CreditTerms | None = None
