package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService

/** Credential rotation keeps this logical binding; a new session cannot adopt an original Debt command. */
internal fun DebtWriteIntent.matchesOriginalBinding(binding: LogicalSessionBinding): Boolean =
    originSessionGeneration == binding.sessionGeneration && originBindingRevision == binding.bindingRevision

/** Verify the original intent and persistent owner against the same request snapshot before delivery. */
internal fun BoundLedgerRequest.serviceForOriginalDebtWrite(row: OutboxRow, intent: DebtWriteIntent): ApiService {
    if (!intent.matchesOriginalBinding(logicalBinding)) throw RepositoryException("连接信息已变化，无法继续这次原提交。")
    return serviceFor(requireNotNull(row.bindingOrNull()))
}
