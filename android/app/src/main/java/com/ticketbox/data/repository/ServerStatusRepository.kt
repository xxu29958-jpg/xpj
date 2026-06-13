package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.dto.StatusPrivateDto
import com.ticketbox.domain.model.ServerBackupHealth

/** DTO → 领域模型:`backup_stale` 缺省(老后端无该字段)映射 false,保守不提醒。 */
fun StatusPrivateDto.toBackupHealth(): ServerBackupHealth = ServerBackupHealth(
    latestBackupAt = latestBackupAt,
    ageHours = backupAgeHours,
    stale = backupStale ?: false,
)

/**
 * `GET /api/status/private` 的窄仓库(轴6 备份超龄通知数据源)。
 *
 * 与 [BudgetRepository] 等 ledger 域仓库的差别:status/private 是 **server 级**端点
 * (只要 app token,与 active ledger 无关),故不走 LedgerRequestGuard 的 ledger 绑定,
 * 直接用 [ApiServiceProvider.current](未绑定时其异常由 [NetworkErrorHandler.safeCall]
 * 折叠为 failure;调用方 engine 另有 sessionReady 前置门,这里只是兜底)。
 */
class ServerStatusRepository(
    private val apiProvider: ApiServiceProvider,
    settingsStore: TicketboxSettingsStore,
) {
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "ServerStatus",
    )

    suspend fun backupHealth(): Result<ServerBackupHealth> = errorHandler.safeCall {
        apiProvider.current().privateStatus().toBackupHealth()
    }
}
