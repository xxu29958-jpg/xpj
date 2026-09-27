package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.StatsProjectionCacheEntity
import java.time.Instant
import java.util.UUID

/** Existing Debt read owner protects dispatch and retirement; no receipt is a canonical query. */
internal data class DebtDispatchReadProtection(val binding: LogicalSessionBinding, val token: String,
    val hadUnresolved: Boolean, val bound: BoundLedgerRequest)

private fun DebtQueryReader.originalDebtBinding(row: OutboxRow): LogicalSessionBinding {
    val binding = requireNotNull(guard.captureLogicalBinding())
    require(row.ownerKey == binding.ownerKey && row.ledgerId == binding.ledgerId &&
        canonicalServerOriginOrNull(row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl)) {
        "原往来提交不属于当前连接。"
    }
    return binding
}

internal suspend fun DebtQueryReader.prepareDebtDispatch(row: OutboxRow) {
    val binding = originalDebtBinding(row)
    val key = logicalBindingAdapter.toJson(binding)
    val token = "${row.idempotencyKey ?: row.id}:${UUID.randomUUID()}"
    activeDirect.add("$key|$token")
    try {
        val protection = DebtDispatchReadProtection(binding, token, dao.debtOutboxReadBarrier(key) != null, guard.bindExact(binding))
        dao.saveStatsProjection(StatsProjectionCacheEntity(key, binding.ledgerId, "debt_outbox_read_barrier",
            "", "", "", "UTC", token, Instant.now().toString()))
        dispatchProtections[row.id] = protection
    } catch (error: Exception) {
        activeDirect.remove("$key|$token")
        throw error // Without durable protection the original command remains unsent.
    }
}

internal suspend fun DebtQueryReader.finishDebtDispatch(row: OutboxRow, result: DispatchResult?) {
    val protection = dispatchProtections.remove(row.id) ?: return
    val key = logicalBindingAdapter.toJson(protection.binding)
    val rejected = result is DispatchResult.Conflict || result is DispatchResult.Discarded ||
        (result is DispatchResult.Failure && result.definitelyRejected)
    try {
        if (result is DispatchResult.Failure && result.credentialRejected) {
            coordinator.rejectSnapshotAccess(protection.bound, key, RepositoryException(result.message, httpStatusCode = 401))
        }
        if (rejected && !protection.hadUnresolved) dao.settleDebtOutboxReadBarrier(key, protection.binding.ledgerId,
            protection.token, retire = false)
    } catch (_: SQLiteException) { /* Preserve protection until an actual current query reconciles it. */ }
    finally { activeDirect.remove("$key|${protection.token}") }
}

internal suspend fun DebtQueryReader.invalidateDebtAccepted(row: OutboxRow) {
    val binding = originalDebtBinding(row)
    val key = logicalBindingAdapter.toJson(binding)
    generation.incrementAndGet()
    retired.add(key)
    dao.settleDebtOutboxReadBarrier(key, binding.ledgerId, requireNotNull(dispatchProtections[row.id]).token, retire = true)
    retired.remove(key)
}

