package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.security.LocalSessionStore
import kotlinx.coroutines.CancellationException

data class SnapshotAccessDenial(
    val binding: LogicalSessionBinding,
    val failure: RepositoryException,
    val generation: Long,
)

internal fun TicketboxSettingsStore.restoreSnapshotAccessDenial(sessions: LocalSessionStore): SnapshotAccessDenial? {
    val binding = sessions.currentSession()?.toBoundSessionSnapshotOrNull()?.logicalBinding ?: return null
    val status = snapshotReadAccessDenial(logicalBindingAdapter.toJson(binding), monthlyArrangementPersistentBindingKey(binding)) ?: return null
    require(status in setOf(401, 403))
    return SnapshotAccessDenial(binding, RepositoryException("绑定已失效，请重新绑定账本。", httpStatusCode = status), 0L)
}

internal fun TicketboxSettingsStore.persistSnapshotAccessDenial(binding: LogicalSessionBinding, bindingKey: String, status: Int?): Boolean = try {
    saveSnapshotReadAccessDenial(bindingKey, monthlyArrangementPersistentBindingKey(binding), status)
    true
} catch (error: CancellationException) {
    throw error
} catch (_: Exception) {
    false
}
