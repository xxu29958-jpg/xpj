package com.ticketbox.data.repository

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
        val expectedLedgerId = core.settingsStore.activeLedgerId()?.takeIf { it.isNotBlank() }
        val bound = core.ledgerRequestGuard.bind(expectedLedgerId = expectedLedgerId)
        val requestSnapshot = core.sessionCoordinator.currentSnapshot()
        core.persistAuthCheck(
            check = bound.service.checkAuth(),
            expectedSnapshot = requestSnapshot,
        )
    }

    suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val service = bound.service
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

        record(DiagnosticCheckKind.Auth) {
            service.checkAuth()
        }
        record(DiagnosticCheckKind.ServerSettings) {
            service.serverSettings()
        }
        record(DiagnosticCheckKind.PendingExpenses) {
            pending = service.pendingExpenses().map { it.toDomain() }
        }
        record(DiagnosticCheckKind.ConfirmedExpenses) {
            service.confirmedExpenses(page = 1, pageSize = 1, timezone = core.currentTimezoneId())
        }
        record(DiagnosticCheckKind.MonthlyStats) {
            service.monthlyStats(month = null, timezone = core.currentTimezoneId())
        }
        record(DiagnosticCheckKind.CategoriesAndMonths) {
            service.categories()
            service.months(timezone = core.currentTimezoneId())
        }
        record(DiagnosticCheckKind.Duplicates) {
            service.duplicates()
        }

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

    fun lastConfirmedSyncAt(): String? = core.settingsStore.lastConfirmedSyncAt()

    fun lastUploadAt(): String? = core.settingsStore.lastUploadAt()

    fun saveMonthlyBudgetCents(amountCents: Long?) {
        core.settingsStore.saveMonthlyBudgetCents(amountCents)
    }

    suspend fun clearLocalCache() {
        core.clearLocalCache()
    }
}
