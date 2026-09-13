package com.ticketbox.data.repository

import com.ticketbox.data.remote.ConfirmedExpensesApiQuery
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import com.ticketbox.data.remote.PageQuery
import com.ticketbox.data.remote.UPLOAD_ORIGINAL_RECEIPT_VERSION
import com.ticketbox.data.remote.dto.RuntimeWriteCompatibility
import com.ticketbox.data.remote.dto.toWriteCompatibility
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ServerSettings
import kotlinx.coroutines.CancellationException
import kotlin.system.measureTimeMillis

internal class ExpenseConnectionRepository(
    private val core: ExpenseRepositoryCore,
) {
    suspend fun testConnection(): Result<Unit> = core.errorHandler.safeCall {
        val session = core.apiProvider.currentSession()
            ?: throw RepositoryException("登录状态已失效，请重新绑定。")
        val requestSnapshot = core.sessionCoordinator.currentSnapshot()
        val establishedOwner = OutboxOwnerIdentity.fromOrNull(
            serverId = session.serverId,
            dataGeneration = session.dataGeneration,
            accountPublicId = session.identity.accountPublicId,
            devicePublicId = session.identity.devicePublicId,
        )
        val check = if (establishedOwner == null) {
            core.apiProvider.bound(
                serverUrl = session.serverUrl,
                expectedVersion = session.version,
                ledgerId = session.identity.ledgerId,
            ).checkAuth()
        } else {
            val bound = core.ledgerRequestGuard.bind(expectedLedgerId = session.identity.ledgerId)
            bound.call { it.checkAuth() }
        }
        core.persistAuthCheck(
            check = check,
            expectedSnapshot = requestSnapshot,
        )
    }

    suspend fun reconcileActiveSession(): Result<Unit>? {
        val session = core.apiProvider.currentSession() ?: return null
        val owner = OutboxOwnerIdentity.fromOrNull(
            serverId = session.serverId,
            dataGeneration = session.dataGeneration,
            accountPublicId = session.identity.accountPublicId,
            devicePublicId = session.identity.devicePublicId,
        )
        return if (owner == null) testConnection() else null
    }

    suspend fun runConnectionDiagnostics(binding: LogicalSessionBinding): Result<ConnectionDiagnostics> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(binding)
        bound.call { service ->
            val checks = mutableListOf<DiagnosticCheck>()

            suspend fun record(
                kind: DiagnosticCheckKind,
                block: suspend () -> Unit,
            ): Boolean {
                bound.requireStillActive()
                val check = diagnosticCheck(kind, block)
                checks += check
                return check.status != DiagnosticStatus.Fail
            }

            var pending = emptyList<Expense>()

            if (!record(DiagnosticCheckKind.Auth) {
                val snapshot = core.sessionCoordinator.currentSnapshot()
                core.persistAuthCheck(service.checkAuth(), snapshot)
            }) return@call ConnectionDiagnostics(checks)
            record(DiagnosticCheckKind.WriteCompatibility) {
                service.runtimeCompatibility().toWriteCompatibility().requireSubmissionCompatibility()
            }
            record(DiagnosticCheckKind.ServerSettings) { service.serverSettings() }
            record(DiagnosticCheckKind.PendingExpenses) {
                pending = service.pendingExpenses().map { it.toDomain() }
            }
            record(DiagnosticCheckKind.ConfirmedExpenses) {
                service.confirmedExpenses(
                    query = ConfirmedExpensesApiQuery(
                        page = PageQuery(page = 1, pageSize = 1),
                        timezone = core.currentTimezoneId(),
                    ).toQueryMap(),
                )
            }
            record(DiagnosticCheckKind.MonthlyStats) {
                service.monthlyStats(month = null, timezone = core.currentTimezoneId())
            }
            record(DiagnosticCheckKind.CategoriesAndMonths) {
                service.categories()
                service.months(timezone = core.currentTimezoneId())
            }
            record(DiagnosticCheckKind.Duplicates) { service.duplicates() }

            val imageCandidate = pending.firstOrNull { it.imagePath != null || it.thumbnailPath != null }
            if (imageCandidate == null) {
                checks += DiagnosticCheck(
                    kind = DiagnosticCheckKind.ProtectedImage,
                    status = DiagnosticStatus.Warn,
                    elapsedMs = 0,
                )
            } else {
                record(DiagnosticCheckKind.ProtectedImage) {
                    core.readProtectedImage(service.expenseThumbnail(imageCandidate.id))
                }
            }

            ConnectionDiagnostics(checks)
        }
    }

    private suspend fun diagnosticCheck(kind: DiagnosticCheckKind, block: suspend () -> Unit): DiagnosticCheck {
        var failure: Exception? = null
        val elapsedMs = measureTimeMillis {
            try {
                block()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                failure = error
            }
        }
        return DiagnosticCheck(
            kind = kind,
            status = if (failure == null) DiagnosticStatus.Pass else DiagnosticStatus.Fail,
            detail = failure?.let(core::diagnosticErrorMessage),
            elapsedMs = elapsedMs,
        )
    }


    suspend fun serverSettings(): Result<ServerSettings> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            val requestSnapshot = core.sessionCoordinator.currentSnapshot()
            val settings = api.serverSettings()
            core.persistServerSettings(
                settings = settings,
                expectedSnapshot = requestSnapshot,
                expectedLedgerId = ledgerId,
            )
            settings.toDomain()
        }
    }

    fun currentLedgerRole(): String? = core.currentLedgerRole()

    fun lastConfirmedSyncAt(): String? =
        core.apiProvider.currentLedgerId()
            ?.let(core.settingsStore::lastConfirmedSyncAtForLedger)

    fun lastUploadAt(): String? =
        core.apiProvider.currentLedgerId()
            ?.let(core.settingsStore::lastUploadAtForLedger)

    suspend fun clearLocalCache() {
        core.clearLocalCache()
    }
}

private fun RuntimeWriteCompatibility.requireSubmissionCompatibility() {
    val matchingReceipt = uploadOriginalReceiptVersion == UPLOAD_ORIGINAL_RECEIPT_VERSION
    if (canWrite && matchingReceipt) return
    val message = when {
        apiVersion != CURRENT_TICKETBOX_API_VERSION ->
            "请将手机应用与服务端更新到配套版本，再重新检测。"
        conclusion == "owner_action_required" ->
            "请让安装拥有者在电脑端确认本位币，再重新检测。未发送的操作仍保留在本机。"
        conclusion == "configuration_required" ->
            "请让管理员在电脑端检查小票夹的本位币配置，再重新检测。"
        conclusion == "server_upgrade_required" ->
            "请让管理员更新电脑上的小票夹服务，再重新检测。"
        conclusion == "client_upgrade_required" || !matchingReceipt ->
            "请将手机应用与服务端更新到配套版本，再重新检测。"
        else -> "尚未确认保存条件，请重新检测；如果仍未恢复，请联系管理员检查服务端。"
    }
    throw RepositoryException(message)
}
