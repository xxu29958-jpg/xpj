package com.ticketbox.data.repository

import com.ticketbox.data.remote.ConfirmedExpensesApiQuery
import com.ticketbox.data.remote.PageQuery
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ServerSettings
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
                sessionGeneration = session.sessionGeneration,
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

    suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { service ->
            val checks = mutableListOf<DiagnosticCheck>()

            suspend fun record(
                kind: DiagnosticCheckKind,
                block: suspend () -> Unit,
            ) {
                var failure: Throwable? = null
                val elapsedMs = measureTimeMillis {
                    try {
                        block()
                    } catch (error: Throwable) {
                        failure = error
                    }
                }
                val error = failure
                checks += if (error == null) {
                    DiagnosticCheck(
                        kind = kind,
                        status = DiagnosticStatus.Pass,
                        elapsedMs = elapsedMs,
                    )
                } else {
                    DiagnosticCheck(
                        kind = kind,
                        status = DiagnosticStatus.Fail,
                        detail = core.diagnosticErrorMessage(error),
                        elapsedMs = elapsedMs,
                    )
                }
            }

            var pending = emptyList<Expense>()

            record(DiagnosticCheckKind.Auth) { service.checkAuth() }
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

    fun monthlyBudgetCents(): Long? = core.settingsStore.monthlyBudgetCents()

    fun lastConfirmedSyncAt(): String? =
        core.apiProvider.currentLedgerId()
            ?.let(core.settingsStore::lastConfirmedSyncAtForLedger)

    fun lastUploadAt(): String? =
        core.apiProvider.currentLedgerId()
            ?.let(core.settingsStore::lastUploadAtForLedger)

    fun saveMonthlyBudgetCents(amountCents: Long?) {
        core.settingsStore.saveMonthlyBudgetCents(amountCents)
    }

    suspend fun clearLocalCache() {
        core.clearLocalCache()
    }
}
