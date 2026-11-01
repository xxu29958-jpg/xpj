package com.ticketbox.data.repository

import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.notification.PaymentNotificationResult
import kotlinx.coroutines.CancellationException

/** Accepts the original into the existing Outbox before any network call. */
class NotificationCaptureRepository internal constructor(
    private val provider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val snapshots: com.ticketbox.data.local.NotificationSnapshotDao,
) {
    private val guard = LedgerRequestGuard(provider)

    internal suspend fun accept(result: PaymentNotificationResult, binding: LogicalSessionBinding, key: String): Result<Long> = try {
        acceptIntent(result.captureIntent(key), binding)
    } catch (error: IllegalArgumentException) {
        Result.failure(RepositoryException("未能保存这条采集，请检查原通知。", "notification_capture_invalid"))
    }

    internal suspend fun acceptBatch(results: List<PaymentNotificationResult>, binding: LogicalSessionBinding, key: String): Result<Long> =
        if (results.size == 1) accept(results.single(), binding, key)
        else acceptIntent(results.captureBatchIntent(key), binding)

    internal suspend fun acceptSnapshot(cards: List<com.ticketbox.notification.ParsedNotificationCard>, binding: LogicalSessionBinding,
        delivery: NotificationSnapshotDelivery): Result<Long> = captureLocally {
        val bound = guard.bindExact(binding)
        require(ledgerRoleCanModify(provider.currentLedgerRole())) { "当前角色为只读，无法采集账单。" }
        outbox.enqueueNotificationSnapshot(bound, snapshots, delivery) { previous, original ->
            planNotificationSnapshot(cards, delivery, previous, original)
        }
    }

    internal suspend fun closeSnapshot(slotKey: String, deliveryKey: String): Result<Unit> = captureLocally {
        snapshots.closeNotificationSnapshot(slotKey, deliveryKey)
    }

    private suspend fun <T> captureLocally(action: suspend () -> T): Result<T> = try {
        Result.success(action())
    } catch (error: CancellationException) {
        throw error
    } catch (error: RepositoryException) {
        Result.failure(error)
    } catch (_: Exception) {
        Result.failure(RepositoryException("未能保存这条采集，请检查本机存储后重试。", "notification_capture_local_save_failed"))
    }

    private suspend fun acceptIntent(intent: PendingMutationIntent, binding: LogicalSessionBinding): Result<Long> = try {
        val bound = guard.bindExact(binding)
        if (!ledgerRoleCanModify(provider.currentLedgerRole())) throw RepositoryException("当前角色为只读，无法采集账单。")
        Result.success(outbox.enqueueOriginalCreation(bound, intent))
    } catch (error: CancellationException) {
        throw error
    } catch (error: RepositoryException) {
        Result.failure(error)
    } catch (_: Exception) {
        Result.failure(RepositoryException("未能保存这条采集，请检查本机存储后重试。", "notification_capture_local_save_failed"))
    }
}
