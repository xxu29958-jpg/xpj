package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode

/** Identity and editor generation accepted before asynchronous image preparation. */
class DebtBillParseAttempt internal constructor(
    val binding: LogicalSessionBinding,
    val homeCurrency: CurrencyCode,
    internal val generation: Long,
)

enum class DebtDraftField {
    Direction,
    Counterparty,
    Note,
    Amount,
    Kind,
    InstallmentCount,
    InstallmentPeriod,
}

fun DebtListViewModel.updateDraftDirection(value: String) =
    updateDraftField(DebtDraftField.Direction, value)

fun DebtListViewModel.updateDraftCounterparty(value: String) =
    updateDraftField(DebtDraftField.Counterparty, value)

fun DebtListViewModel.updateDraftNote(value: String) =
    updateDraftField(DebtDraftField.Note, value)

fun DebtListViewModel.updateDraftAmount(value: String) =
    updateDraftField(DebtDraftField.Amount, value)

fun DebtListViewModel.updateDraftKind(value: String) =
    updateDraftField(DebtDraftField.Kind, value)

fun DebtListViewModel.updateDraftInstallmentCount(value: String) =
    updateDraftField(DebtDraftField.InstallmentCount, value)

fun DebtListViewModel.updateDraftInstallmentPeriod(value: String) =
    updateDraftField(DebtDraftField.InstallmentPeriod, value)
