package com.ticketbox.data.local

internal class ExpenseFactInputFake : ExpenseFactInputDao {
    private val rows = mutableListOf<ExpenseFactInputEntity>()
    override suspend fun pendingReviewInputs(owner: String, ledger: String) =
        rows.filter { it.ownerKey == owner && it.ledgerId == ledger && it.formKey.startsWith("pending_") }
    override suspend fun factInputs(owner: String, ledger: String, expense: Long) =
        rows.filter { it.ownerKey == owner && it.ledgerId == ledger && it.expenseId == expense }
    override suspend fun putFactInput(input: ExpenseFactInputEntity) {
        deleteFactInput(input.ownerKey, input.ledgerId, input.expenseId, input.formKey)
        rows += input
    }
    override suspend fun deleteFactInput(owner: String, ledger: String, expense: Long, form: String) {
        rows.removeAll { it.ownerKey == owner && it.ledgerId == ledger && it.expenseId == expense && it.formKey == form }
    }
}
