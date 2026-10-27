package com.ticketbox.domain.model

data class BillSplitInviteRequest(
    val receiverAccountId: Long,
    val amountCents: Long,
    val expectedRowVersion: Long,
)

data class DebtGoalLinksReplaceRequest(
    val expectedRowVersion: Long,
    val debtPublicIds: List<String>,
)

data class DebtGoalTargetDateRequest(
    val expectedRowVersion: Long,
    val targetDate: String? = null,
)

data class GoalCreateRequest(
    val name: String,
    val goalType: String = "spending_limit",
    val period: String = "monthly",
    val month: String? = null,
    val targetAmountCents: Long? = null,
    val category: String? = null,
    val debtPublicIds: List<String>? = null,
    val homeCurrencyCode: String? = null,
)

data class GoalUpdateRequest(
    val expectedRowVersion: Long,
    val name: String? = null,
    val month: String? = null,
    val category: String? = null,
    val targetAmountCents: Long? = null,
    
    val homeCurrencyCode: String? = null,
)

data class IncomePlanUpdateRequest(
    val intentMonth: String,
    val expectedRowVersion: Long,
    val label: String? = null,
    val sourceType: String? = null,
    val frequency: String? = null,
    val incomeMonth: String? = null,
    val amountCents: Long? = null,
    val payDay: Int? = null,
)
