package com.ticketbox.data.repository

import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.notification.PaymentNotificationResult
import kotlinx.coroutines.CancellationException

/** Accepts the original into the existing Outbox before any network call. */
class NotificationCaptureRepository internal constructor(
    private val provider: ApiServiceProvider,
    private val outbox: OutboxRepository,
) {
    private val guard = LedgerRequestGuard(provider)

    internal suspend fun accept(result: PaymentNotificationResult, binding: LogicalSessionBinding, key: String): Result<Long> = try {
        val bound = guard.bindExact(binding)
        if (!ledgerRoleCanModify(provider.currentLedgerRole())) throw RepositoryException("当前角色为只读，无法采集账单。")
        Result.success(outbox.enqueueOriginalCreation(bound, result.captureIntent(key)))
    } catch (error: CancellationException) {
        throw error
    } catch (error: RepositoryException) {
        Result.failure(error)
    } catch (_: Exception) {
        Result.failure(RepositoryException("未能保存这条采集，请检查本机存储后重试。", "notification_capture_local_save_failed"))
    }
}
