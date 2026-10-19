package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding

internal suspend fun FundsViewModel.refreshAccounts(binding: LogicalSessionBinding) {
    mutable.value = mutable.value.copy(loading = true)
    val result = repository.reads.accounts(binding)
    if (mutable.value.access?.binding != binding) return
    result.fold(onSuccess = { read -> mutable.value = mutable.value.copy(accounts = read.value, fromCache = read.fromCache, loading = false, error = null) },
        onFailure = { error -> mutable.value = mutable.value.copy(loading = false, error = error.toUiText()) })
    val choices = repository.reads.accountChoices(binding)
    if (mutable.value.access?.binding != binding) return
    choices.onSuccess { read -> mutable.value = mutable.value.copy(accountChoices = read.value) }
    val existing = repository.reads.existingDebts(binding)
    if (mutable.value.access?.binding != binding) return
    existing.fold(onSuccess = { read -> mutable.value = mutable.value.copy(existingDebts = read.value, fromCache = mutable.value.fromCache || read.fromCache) },
        onFailure = { error -> mutable.value = mutable.value.copy(error = error.toUiText()) })
    if (repaymentDraftId != null) {
        val captured = captures?.readDrafts(binding) ?: return
        if (mutable.value.access?.binding == binding) captured.fold(
            onSuccess = { read -> mutable.value = mutable.value.copy(repaymentCapture = read.value.find { row -> row.publicId == repaymentDraftId },
                fromCache = mutable.value.fromCache || read.fromCache) },
            onFailure = { error -> mutable.value = mutable.value.copy(repaymentCapture = null, error = error.toUiText()) })
        return
    }
    if (expenseId != null) {
        val funding = repository.reads.funding(binding, expenseId)
        if (mutable.value.access?.binding == binding) funding.fold(
            onSuccess = { read -> mutable.value = mutable.value.copy(funding = read.value, fromCache = mutable.value.fromCache || read.fromCache) },
            onFailure = { error -> mutable.value = mutable.value.copy(funding = null, error = error.toUiText()) })
        return
    }
    val overview = repository.reads.overview(binding)
    if (mutable.value.access?.binding == binding) overview.fold(
        onSuccess = { read -> mutable.value = mutable.value.copy(overview = read.value, fromCache = mutable.value.fromCache || read.fromCache) },
        onFailure = { error -> mutable.value = mutable.value.copy(overview = null, error = error.toUiText()) })
}

internal suspend fun FundsViewModel.reloadAccount(binding: LogicalSessionBinding, accountId: String, stillCurrent: () -> Boolean) {
    val target = repository.reads.detail(binding, accountId).onFailure { error ->
        if (state.value.access?.binding == binding && stillCurrent()) mutable.value = mutable.value.copy(error = error.toUiText())
    }.getOrNull() ?: return
    if (state.value.access?.binding != binding || !stillCurrent()) return
    mutable.value = mutable.value.copy(detail = target.value, fromCache = mutable.value.fromCache || target.fromCache)
    if (target.value.kind != "credit") return
    repository.reads.installments(binding, accountId).fold(
        onSuccess = { read -> if (state.value.access?.binding == binding && stillCurrent())
            mutable.value = mutable.value.copy(installments = read.value, fromCache = mutable.value.fromCache || read.fromCache) },
        onFailure = { error -> if (state.value.access?.binding == binding && stillCurrent()) mutable.value = mutable.value.copy(error = error.toUiText()) })
}
