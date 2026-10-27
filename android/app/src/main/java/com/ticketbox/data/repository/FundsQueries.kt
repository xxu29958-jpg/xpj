package com.ticketbox.data.repository

/** Session-bound funds projections; no command publication or input ownership. */
class FundsQueries internal constructor(private val queries: DebtQueryReader) {
    // Earlier account/detail/overview snapshots included other ledgers owned by the same person.
    // These read tags require one authorized refresh; raw inputs and Outbox keys are unchanged.
    suspend fun envelopeHistory(binding: LogicalSessionBinding, before: Long?) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "envelope_history", before?.toString() ?: "latest")),
        DebtReadSpec(FundsWire.envelopeHistory, { envelopeHistory(before) }, validate = { rows ->
            require(rows.all { it.rowVersion > 0 && (before == null || it.rowVersion < before) })
        }, isNewer = { _, _ -> false }, project = { value, _ -> value }))

    suspend fun envelopes(binding: LogicalSessionBinding, month: String) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "cash_envelopes", month)),
        DebtReadSpec(FundsWire.envelopes, { envelopes(month) }, validate = {
            require(it.ledgerId == binding.ledgerId && it.month == month && it.rowVersion >= 0)
        }, isNewer = { old, incoming -> incoming.rowVersion > old.rowVersion }, project = { value, _ -> value }))

    suspend fun accountChoices(binding: LogicalSessionBinding) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_account_choices", "all")),
        DebtReadSpec(FundsWire.choices, { fundsAccountChoices() }, validate = { rows ->
            require(rows.map { it.key }.distinct().size == rows.size)
        }, isNewer = { _, _ -> false }, project = { value, _ -> value }))

    suspend fun overview(binding: LogicalSessionBinding) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_overview", "ledger-v2:all")),
        DebtReadSpec(FundsWire.overview, { fundsOverview() }, validate = { require(it.includedAccounts >= 0) },
            isNewer = { _, _ -> false }, project = { value, _ -> value }))

    suspend fun accounts(binding: LogicalSessionBinding) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_accounts", "ledger-v2:all")),
        DebtReadSpec(FundsWire.listing, { fundsAccounts() }, validate = { rows ->
            require(rows.all { it.rowVersion > 0 && it.ledgerId == binding.ledgerId } && rows.map { it.publicId }.distinct().size == rows.size)
        }, isNewer = { old, incoming -> old.associateBy { it.publicId }.let { previous ->
            incoming.any { row -> previous[row.publicId]?.rowVersion?.let { it < row.rowVersion } == true }
        } }, project = { rows, _ -> rows }))
        .map { ReadSnapshot(it.value.map { it.toDomain() }, it.fetchedAt, it.fromCache) }

    suspend fun existingDebts(binding: LogicalSessionBinding) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_existing_debts", "all")),
        DebtReadSpec(FundsWire.existingDebts, { existingFundDebts() }, validate = { rows ->
            require(rows.all { it.rowVersion > 0 } && rows.map { it.publicId }.distinct().size == rows.size)
        }, isNewer = { _, _ -> false }, project = { rows, _ -> rows }))

    suspend fun detail(binding: LogicalSessionBinding, id: String) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "funds_account", "ledger-v2:$id")),
        DebtReadSpec(FundsWire.account, { fundsAccount(id) }, validate = { require(it.publicId == id && it.ledgerId == binding.ledgerId) },
            isNewer = { old, incoming -> incoming.rowVersion > old.rowVersion }, project = { value, _ -> value }))
        .map { ReadSnapshot(it.value.toDomain(), it.fetchedAt, it.fromCache) }

    suspend fun funding(binding: LogicalSessionBinding, id: Long) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "expense_funding", id.toString())),
        DebtReadSpec(FundsWire.funding, { expenseFunding(id) }, validate = { require(it.expenseId == id) },
            isNewer = { old, incoming -> incoming.expenseRowVersion > old.expenseRowVersion }, project = { value, _ -> value }))

    suspend fun installments(binding: LogicalSessionBinding, id: String) = queries.read(binding,
        DebtQueryScope(debtScope(binding, "installments", "ledger-v2:$id")),
        DebtReadSpec(FundsWire.installments, { installments(id) }, validate = { require(it.accountPublicId == id) },
            isNewer = { old, incoming -> incoming.accountRowVersion > old.accountRowVersion }, project = { value, _ -> value }))

}
