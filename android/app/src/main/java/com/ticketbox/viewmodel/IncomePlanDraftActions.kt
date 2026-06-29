package com.ticketbox.viewmodel

enum class IncomePlanDraftField {
    Label,
    IncomeMonth,
    Amount,
    PayDay,
}

fun IncomePlanViewModel.updateDraftLabel(value: String) =
    updateDraftField(IncomePlanDraftField.Label, value)

fun IncomePlanViewModel.updateDraftIncomeMonth(value: String) =
    updateDraftField(IncomePlanDraftField.IncomeMonth, value)

fun IncomePlanViewModel.updateDraftAmount(value: String) =
    updateDraftField(IncomePlanDraftField.Amount, value)

fun IncomePlanViewModel.updateDraftPayDay(value: String) =
    updateDraftField(IncomePlanDraftField.PayDay, value)
