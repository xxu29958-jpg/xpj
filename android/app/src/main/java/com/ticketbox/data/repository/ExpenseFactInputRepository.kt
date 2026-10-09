package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.ticketbox.data.local.ExpenseFactInputEntity

/** Raw input and its original identity, not a fact projection or a second command queue. */
data class ExpenseFactOriginalInput(
    val binding: LogicalSessionBinding,
    val expenseId: Long,
    val formKey: String,
    val originalKey: String,
    val json: String,
)

interface ExpenseFactInputActions {
    suspend fun loadPendingReviewInputs(binding: LogicalSessionBinding): Result<List<ExpenseFactOriginalInput>>
    suspend fun loadFactInputs(binding: LogicalSessionBinding, id: Long): Result<List<ExpenseFactOriginalInput>>
    suspend fun saveFactInput(expected: ExpenseFactOriginalInput?, input: ExpenseFactOriginalInput): Result<Unit>
    suspend fun discardFactInput(binding: LogicalSessionBinding, input: ExpenseFactOriginalInput): Result<Unit>
}

internal class ExpenseFactInputRepository(private val core: ExpenseRepositoryCore) : ExpenseFactInputActions {
    private val bindingAdapter = Moshi.Builder().build().adapter(LogicalSessionBinding::class.java)

    override suspend fun loadFactInputs(binding: LogicalSessionBinding, id: Long) = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        core.offlineMutations.outbox.withActiveBinding(bound) {
            core.expenseDao.factInputs(binding.ownerKey, binding.ledgerId, id)
                .filterNot { it.formKey.startsWith("original_") }.map(::original)
        }
    }

    override suspend fun loadPendingReviewInputs(binding: LogicalSessionBinding) = core.errorHandler.safeCall {
        core.offlineMutations.outbox.withActiveBinding(core.ledgerRequestGuard.bindExact(binding)) {
            core.expenseDao.pendingReviewInputs(binding.ownerKey, binding.ledgerId).map(::original)
        }
    }

    private fun original(row: ExpenseFactInputEntity) = ExpenseFactOriginalInput(
        requireNotNull(bindingAdapter.fromJson(row.bindingJson)), row.expenseId, row.formKey, row.originalKey, row.inputJson)

    override suspend fun saveFactInput(expected: ExpenseFactOriginalInput?, input: ExpenseFactOriginalInput) = core.errorHandler.safeCall {
        require(input.expenseId > 0 && input.formKey.isNotBlank() && input.originalKey.isNotBlank() && !input.formKey.startsWith("original_"))
        require(expected == null || expected.binding.ownerKey == input.binding.ownerKey &&
            expected.binding.ledgerId == input.binding.ledgerId && expected.expenseId == input.expenseId && expected.formKey == input.formKey)
        // A captured edit may finish after navigation or an identity switch. It stays in its
        // original private scope; it cannot become a command without the active binding guard.
        // Only an explicit adoption can replace the binding of an existing input.
        if (expected != null && expected.binding != input.binding) core.ledgerRequestGuard.bindExact(input.binding)
        core.expenseDao.replaceFactInput(expected?.entity(), input.entity())
    }

    override suspend fun discardFactInput(binding: LogicalSessionBinding, input: ExpenseFactOriginalInput) = core.errorHandler.safeCall {
        require(!input.formKey.startsWith("original_"))
        require(input.binding.ownerKey == binding.ownerKey && input.binding.ledgerId == binding.ledgerId)
        core.offlineMutations.outbox.withActiveBinding(core.ledgerRequestGuard.bindExact(binding)) {
            core.expenseDao.consumeFactInput(input.entity())
        }
    }

    /** Called inside the existing Outbox insert transaction: both the command and consumption commit, or neither does. */
    suspend fun consume(input: ExpenseFactOriginalInput?, binding: LogicalSessionBinding, expenseId: Long, form: String) {
        if (input == null) return
        require(input.binding == binding && input.expenseId == expenseId && input.formKey == form) { "请核对原输入所属账单。" }
        core.expenseDao.consumeFactInput(input.entity())
    }

    private fun ExpenseFactOriginalInput.entity() = ExpenseFactInputEntity(binding.ownerKey, binding.ledgerId, expenseId,
        formKey, bindingAdapter.toJson(binding), originalKey, json)
}
