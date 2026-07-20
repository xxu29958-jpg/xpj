package com.ticketbox.data.repository

import com.ticketbox.security.isBusinessReady
import kotlinx.coroutines.CancellationException
import java.util.UUID

internal class ExpenseBindingRepository(
    private val core: ExpenseRepositoryCore,
) : ServerBindingRepository {
    private val enrollment = DeviceEnrollmentCoordinator(
        sessionStore = core.binding.sessionStore,
        apiProvider = core.apiProvider,
        sessionCoordinator = core.sessionCoordinator,
    )

    override fun hasActiveSession(): Boolean = core.apiProvider.currentSession() != null

    override fun isBusinessSessionReady(): Boolean =
        core.apiProvider.currentSession().isBusinessReady()

    override fun hasPendingBinding(): Boolean =
        core.binding.sessionStore.pendingDeviceEnrollment() != null

    override suspend fun bindServer(
        serverUrl: String,
        pairingCode: String,
    ): Result<BindServerResult> = completeEnrollment(serverUrl) {
        enrollment.pairDevice(
            serverUrl = serverUrl,
            pairingCode = pairingCode,
            deviceName = core.deviceNameProvider(),
        )
    }

    override suspend fun resumePendingBinding(): Result<BindServerResult>? {
        val pending = core.binding.sessionStore.pendingDeviceEnrollment() ?: return null
        return completeEnrollment(pending.serverUrl) {
            requireNotNull(enrollment.resumePending())
        }
    }

    override suspend fun abandonPendingBinding(): Boolean =
        enrollment.abandonPending()

    private suspend fun completeEnrollment(
        serverUrl: String,
        enroll: suspend () -> LedgerSessionIdentity,
    ): Result<BindServerResult> = core.errorHandler.safeCall(serverUrlHint = serverUrl) {
        val identity = enroll()
        val restoreFailed = restoreConfirmedAfterBinding(identity.ledgerId)
        BindServerResult(confirmedRestoreFailed = restoreFailed)
    }

    private suspend fun restoreConfirmedAfterBinding(ledgerId: String): Boolean = try {
        val bound = core.ledgerRequestGuard.bind(expectedLedgerId = ledgerId)
        core.syncConfirmedFromService(
            bound = bound,
            request = ConfirmedSyncRequest(replaceCache = true),
        )
        false
    } catch (error: Exception) {
        if (error is CancellationException) throw error
        logNetworkWarning("Confirmed restore failed after successful binding.", error)
        true
    }

    override suspend fun clearBinding() {
        core.clearBinding()
    }

}

internal fun String?.requireSessionProtocolId(label: String): String {
    val value = this?.takeIf { it.isNotBlank() }
        ?: throw RepositoryException("后端版本过旧，缺少${label}，请先升级后端。")
    val canonical = runCatching { UUID.fromString(value).toString() }.getOrNull()
    if (canonical != value) throw RepositoryException("后端返回的${label}无效，已停止操作。")
    return value
}
