package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.flow.update

internal suspend fun FundsViewModel.refreshAccounts(binding: LogicalSessionBinding) {
    mutable.update { it.copy(loading = true) }
    val result = repository.reads.accounts(binding)
    if (mutable.value.access?.binding != binding) return
    result.fold(onSuccess = { read -> mutable.update { it.copy(accounts = read.value, fromCache = read.fromCache, loading = false, error = null) } },
        onFailure = { error -> mutable.update { it.copy(loading = false, error = error.toUiText()) } })
    val choices = repository.reads.accountChoices(binding)
    if (mutable.value.access?.binding != binding) return
    choices.onSuccess { read -> mutable.update { it.copy(accountChoices = read.value) } }
    val existing = repository.reads.existingDebts(binding)
    if (mutable.value.access?.binding != binding) return
    existing.fold(onSuccess = { read -> mutable.update { it.copy(existingDebts = read.value, fromCache = it.fromCache || read.fromCache) } },
        onFailure = { error -> mutable.update { it.copy(error = error.toUiText()) } })
    if (repaymentDraftId != null) {
        val captured = captures?.readDrafts(binding) ?: return
        if (mutable.value.access?.binding == binding) captured.fold(
            onSuccess = { read -> mutable.update { it.copy(repaymentCapture = read.value.find { row -> row.publicId == repaymentDraftId },
                fromCache = it.fromCache || read.fromCache) } },
            onFailure = { error -> mutable.update { it.copy(repaymentCapture = null, error = error.toUiText()) } })
        return
    }
    if (expenseId != null) {
        val funding = repository.reads.funding(binding, expenseId)
        if (mutable.value.access?.binding == binding) funding.fold(
            onSuccess = { read -> mutable.update { it.copy(funding = read.value, fromCache = it.fromCache || read.fromCache) } },
            onFailure = { error -> mutable.update { it.copy(funding = null, error = error.toUiText()) } })
        return
    }
    val overview = repository.reads.overview(binding)
    if (mutable.value.access?.binding == binding) overview.fold(
        onSuccess = { read -> mutable.update { it.copy(overview = read.value, fromCache = it.fromCache || read.fromCache) } },
        onFailure = { error -> mutable.update { it.copy(overview = null, error = error.toUiText()) } })
}

internal suspend fun FundsViewModel.reloadSchedule(binding: LogicalSessionBinding, accountId: String) {
    val target = repository.reads.detail(binding, accountId).getOrNull()?.value ?: return
    if (target.kind != "credit") return
    repository.reads.installments(binding, accountId).fold(
        onSuccess = { read -> if (state.value.access?.binding == binding && state.value.task.input?.accountId == accountId)
            mutable.update { it.copy(installments = read.value, fromCache = it.fromCache || read.fromCache) } },
        onFailure = { error -> if (state.value.access?.binding == binding) mutable.update { it.copy(error = error.toUiText()) } })
}
