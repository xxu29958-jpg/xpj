package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseFactOriginalInput
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.readExpenseFunding
import com.ticketbox.data.repository.fundingInputAdapter
import com.ticketbox.data.repository.FundsRepository
import com.ticketbox.data.repository.canReviewFunding
import com.ticketbox.data.repository.reviewedFundingInputs
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The pending editor retains funding in the existing Room input owner until Outbox admission. */
internal fun ExpenseEditViewModel.loadPendingFunding(expense: Expense) {
    val binding = fxBinding ?: return
    if (fundingInputSession != null) return
    viewModelScope.launch {
        repository.originalInputs.loadFactInputs(binding, expense.id).onSuccess { inputs ->
            if (binding != repository.captureDeferredLedgerBinding()) return@onSuccess
            runCatching {
                val originals = inputs.filter { it.formKey == "pending_funding" }
                val json = originals.singleOrNull()?.let { ExpenseFactInputCodec.decode(it.json, expense.id).fundingJson } ?: "[]"
                requireNotNull(fundingInputAdapter.fromJson(json)) { "付款来源原稿无法读取，原输入仍保留在本机。" }
                lateinit var session: ExpenseFactInputSession
                session = ExpenseFactInputSession(binding, expense.id, repository.originalInputs, viewModelScope, originals) {
                    if (fundingInputSession === session) _uiState.update { it.copy(fundingWriting = session.writing,
                        fundingMessage = session.error?.toUiText(R.string.expense_fact_input_save_failed)) }
                }
                fundingInputSession = session
                _uiState.update { it.copy(fundingJson = json, fundingReady = true, fundingMessage = null) }
            }.onFailure { error ->
                _uiState.update { it.copy(fundingMessage = error.toUiText(R.string.expense_fact_input_load_failed)) }
            }
        }.onFailure { error ->
            _uiState.update { it.copy(fundingMessage = error.toUiText(R.string.expense_fact_input_load_failed)) }
        }
    }
}

fun ExpenseEditViewModel.editFunding(json: String) {
    val state = uiState.value
    val expense = state.expense ?: return
    if (!state.fundingReady || state.readOnly || state.saving || state.commandRowIds.isNotEmpty()) return
    _uiState.update { it.copy(fundingJson = json) }
    fundingInputSession?.keep("pending_funding", ExpenseFactInputDraft(expense, fundingJson = json))
}

fun ExpenseEditViewModel.reviewPendingFunding(funds: FundsRepository) {
    val state = uiState.value
    val expense = state.expense ?: return
    val binding = fxBinding ?: return
    if (state.saving || state.readOnly || state.fundingWriting) return
    val rejected = commandObservation?.commands?.filter { it.row.targetId == "expense:${expense.id}" &&
        it.row.status != com.ticketbox.data.local.PendingMutationStatus.Done }?.singleOrNull()?.row
    if (state.commandRowIds.isNotEmpty() && rejected?.canReviewFunding() != true) return
    _uiState.update { it.copy(saving = true, fundingMessage = null) }
    viewModelScope.launch {
        runCatching {
            fundingInputSession?.flush()?.getOrThrow()
            val fresh = repository.fetchExpenseForFxReview(binding, expense.id).getOrThrow()
            require(fresh.status == "pending") { "这笔消费已不在待确认状态，请返回查看最新账单；原提交仍保留。" }
            val accounts = funds.reads.accounts(binding).getOrThrow()
            require(!accounts.fromCache) { "请联网核对账户；原金额和币种已保留。" }
            val json = if (rejected != null) reviewedFundingInputs(rejected, accounts.value)
                else refreshedPendingFunding(state.fundingJson, accounts.value)
            require(binding == repository.captureDeferredLedgerBinding()) { "身份已变化，请回到原账本核对。" }
            val draft = ExpenseFactInputDraft(fresh, fundingJson = json)
            if (rejected != null) {
                val input = ExpenseFactOriginalInput(binding, expense.id, "pending_funding",
                    java.util.UUID.randomUUID().toString(), ExpenseFactInputCodec.encode(draft))
                funds.reopenExpenseConfirmation(binding, rejected, input, repository.originalInputs).getOrThrow()
                fundingInputSession = null
                savedState.remove<LongArray>("expense_command_ids")
            } else {
                requireNotNull(fundingInputSession).keep("pending_funding", draft, review = true)
                requireNotNull(fundingInputSession).flush().getOrThrow()
            }
            _uiState.update { it.copy(expense = fresh, saving = false, fundingJson = json,
                fundingReviewAvailable = false, commandRowIds = emptyList(), commandsCompleted = false,
                done = false, confirmationReceipt = null, originalBaselineRequired = false, formRevision = it.formRevision + 1,
                message = null, fundingMessage = UiText.raw("已读取最新消费和账户。原付款金额与币种已保留，请核对后再确认。")) }
            if (rejected != null) loadPendingFunding(fresh)
        }.onFailure { error ->
            if (binding == repository.captureDeferredLedgerBinding()) _uiState.update {
                it.copy(saving = false, fundingMessage = error.toUiText(R.string.expense_fact_input_load_failed))
            }
        }
    }
}

internal suspend fun ExpenseEditViewModel.readyPendingFunding(draft: ExpenseDraft): Result<ExpenseFactOriginalInput?> {
    val session = fundingInputSession ?: return Result.failure(RepositoryException("付款来源尚未读取完成，请稍后重试。"))
    val stored = session.flush()
    if (stored.isFailure) return Result.failure(requireNotNull(stored.exceptionOrNull()))
    val original = session.original("pending_funding") ?: return if (draft.funding.isEmpty()) Result.success(null)
        else Result.failure(RepositoryException("付款来源原稿尚未保存，请保留输入重试。"))
    val ready = session.ready("pending_funding")
    if (ready.isFailure) return Result.failure(requireNotNull(ready.exceptionOrNull()))
    val values = session.draft("pending_funding") ?: return Result.failure(RepositoryException("付款来源原稿无法读取。"))
    return runCatching {
        require(readExpenseFunding(values.fundingJson, requireNotNull(draft.originalCurrencyCode)) == draft.funding) {
            "付款来源已变化，请重新核对原输入。"
        }
        original
    }
}

private fun refreshedPendingFunding(json: String, accounts: List<com.ticketbox.data.remote.dto.FinancialAccountDto>) =
    fundingInputAdapter.toJson(requireNotNull(fundingInputAdapter.fromJson(json)).map { part ->
        val account = accounts.firstOrNull { it.publicId == part.accountId && !it.archived && it.currencyCode == part.accountCurrency }
        part.copy(accountVersion = account?.rowVersion ?: part.accountVersion, accountName = account?.name ?: "原付款账户（现不可用）")
    })
