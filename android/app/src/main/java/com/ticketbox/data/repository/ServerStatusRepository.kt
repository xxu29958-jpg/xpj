package com.ticketbox.data.repository

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
 * status/private 是 server 级端点，但请求仍必须固定到一次已验证的会话快照，
 * 避免重绑或切换期间从动态 provider 读取另一套凭据。
 */
class ServerStatusRepository(
    private val apiProvider: ApiServiceProvider,
) {
    private val requestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "ServerStatus",
    )

    suspend fun backupHealth(): Result<ServerBackupHealth> = errorHandler.safeCall {
        requestGuard.guardedCall { api -> api.privateStatus().toBackupHealth() }
    }
}
