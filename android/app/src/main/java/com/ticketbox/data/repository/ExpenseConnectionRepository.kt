package com.ticketbox.data.repository

import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticCheck
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
            name: String,
            successDetail: String,
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
                    name = name,
                    status = DiagnosticStatus.Pass,
                    detail = successDetail,
                    elapsedMs = elapsedMs,
                )
            } else {
                DiagnosticCheck(
                    name = name,
                    status = DiagnosticStatus.Fail,
                    detail = core.diagnosticErrorMessage(error),
                    elapsedMs = elapsedMs,
                )
            }
        }

        var pending = emptyList<Expense>()

        record("身份验证", "访问凭证有效") {
            service.checkAuth()
        }
        record("账本状态", "小票夹服务正常") {
            service.serverSettings()
        }
        record("待确认账单", "可以读取待确认账单") {
            pending = service.pendingExpenses().map { it.toDomain() }
        }
        record("已确认账单", "可以更新账本") {
            service.confirmedExpenses(page = 1, pageSize = 1, timezone = core.currentTimezoneId())
        }
        record("月度统计", "可以读取月度统计") {
            service.monthlyStats(month = null, timezone = core.currentTimezoneId())
        }
        record("分类与月份", "可以读取分类和月份") {
            service.categories()
            service.months(timezone = core.currentTimezoneId())
        }
        record("疑似重复", "可以读取疑似重复账单") {
            service.duplicates()
        }

        val imageCandidate = pending.firstOrNull { it.imagePath != null || it.thumbnailPath != null }
        if (imageCandidate == null) {
            checks += DiagnosticCheck(
                name = "受保护图片",
                status = DiagnosticStatus.Warn,
                detail = "还没有待确认截图，跳过图片检查。",
                elapsedMs = 0,
            )
        } else {
            record("受保护图片", "截图预览可以打开") {
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
