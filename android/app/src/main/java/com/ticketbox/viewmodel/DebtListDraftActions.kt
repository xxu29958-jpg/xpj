package com.ticketbox.viewmodel

enum class DebtDraftField {
    Direction,
    Counterparty,
    Amount,
    Kind,
    InstallmentCount,
    InstallmentPeriod,
}

fun DebtListViewModel.updateDraftDirection(value: String) =
    updateDraftField(DebtDraftField.Direction, value)

fun DebtListViewModel.updateDraftCounterparty(value: String) =
    updateDraftField(DebtDraftField.Counterparty, value)

fun DebtListViewModel.updateDraftAmount(value: String) =
    updateDraftField(DebtDraftField.Amount, value)

fun DebtListViewModel.updateDraftKind(value: String) =
    updateDraftField(DebtDraftField.Kind, value)

fun DebtListViewModel.updateDraftInstallmentCount(value: String) =
    updateDraftField(DebtDraftField.InstallmentCount, value)

fun DebtListViewModel.updateDraftInstallmentPeriod(value: String) =
    updateDraftField(DebtDraftField.InstallmentPeriod, value)
