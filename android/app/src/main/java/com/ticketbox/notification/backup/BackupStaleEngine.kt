package com.ticketbox.notification.backup

import com.ticketbox.domain.model.ServerBackupHealth
import java.time.LocalDate

/**
 * 备份链健康的**只读**来源。生产接线是 `serverStatusRepository::backupHealth` 的直接透传
 * (fun interface,无适配类);测试注 lambda。实现禁止任何写。
 */
fun interface BackupStaleSource {
    suspend fun backupHealth(): Result<ServerBackupHealth>
}

/**
 * 一次备份超龄检测的结果(worker 据此映射 WorkManager Result,镜像 recurring outcome 形态)。
 *
 * - [Success]:检测完成(含开关关 / 未登录 / 备份新鲜 / 今天已提醒等 safe-success),
 *   worker 映射 Result.success();[Success.detail] 给测试与日志定性。
 * - [TransientFailure]:source 网络 / API 故障,worker 映射 Result.retry()。
 *
 * 任何失败都不写服务端状态、不 markSent(0046 边界契约:失败安全降级)。
 */
sealed interface BackupStaleRunOutcome {
    enum class Detail {
        SENT,
        SKIPPED_DISABLED,
        SKIPPED_NO_SESSION,
        SKIPPED_FRESH,
        SKIPPED_ALREADY_SENT,
        SKIPPED_DISPATCH,
    }

    data class Success(val detail: Detail) : BackupStaleRunOutcome

    data class TransientFailure(val reason: String) : BackupStaleRunOutcome
}

/**
 * 检测器运行时上下文(镜像 [RecurringReminderRuntime][com.ticketbox.notification.recurring.RecurringReminderRuntime],
 * 打包使 engine 构造 ≤6 参)。
 *
 * @property backupStaleAlertsEnabled 「备份超龄提醒」开关现读(关 → 不拉、不发、不 markSent)。
 * @property sessionReady 已绑定 token + server 地址(status/private 是 server 级,
 *   **不要求 active ledger**——这点与 recurring 的 sessionReady 不同)。
 * @property today 设备本地当天(日级 sent-key 锚点,可注入钉边界)。
 * @property logWarning 轻量日志注入:source 失败记 error class,不记 token / 时间明细。
 */
class BackupStaleRuntime(
    val backupStaleAlertsEnabled: () -> Boolean,
    val sessionReady: () -> Boolean,
    val today: () -> LocalDate,
    val logWarning: (String, Throwable?) -> Unit = { _, _ -> },
)

/**
 * 备份超龄提醒检测引擎(轴6 主动性 · 五类事件之五,收官)。由 24h 周期
 * [BackupStaleWorker] 唤醒(0046 边界契约:Worker 只做调度,业务判断在本纯层)。
 *
 * 判定超薄:`stale` 布尔由服务端 `backup_service.backup_health()` 算好
 * (48h 阈值服务端单源),本层只做开关/session 前置、日级去重与投递编排——
 * 不在客户端重算年龄、不写服务端任何状态。
 *
 * 与 budget 检测器(事件驱动)的差别:备份超龄与用户记账动作无关,是纯运维
 * 状态,所以走周期 worker 而非确认回调;与 recurring 的差别:无 per-item 扫描,
 * 单次单判定。
 */
class BackupStaleEngine(
    private val source: BackupStaleSource,
    private val store: BackupStaleStore,
    private val dispatcher: BackupStaleDispatcher,
    private val runtime: BackupStaleRuntime,
) {
    /** 一次完整检测:前置门 → 拉健康 → stale? → 日级去重 → dispatch → SENT 才 markSent。 */
    suspend fun checkAndNotify(): BackupStaleRunOutcome {
        if (!runtime.backupStaleAlertsEnabled()) {
            return BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_DISABLED)
        }
        if (!runtime.sessionReady()) {
            return BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_NO_SESSION)
        }
        val health = source.backupHealth().getOrElse { error ->
            runtime.logWarning("backup health fetch failed: ${error::class.java.simpleName}", error)
            return BackupStaleRunOutcome.TransientFailure(error::class.java.simpleName)
        }
        if (!health.stale) return BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_FRESH)
        val key = backupStaleSentKey(runtime.today())
        if (store.wasSent(key)) {
            return BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_ALREADY_SENT)
        }
        val decision = BackupStaleDecision(key = key, ageHours = health.ageHours)
        return when (dispatcher.dispatch(decision)) {
            BackupStaleDispatchOutcome.SENT -> {
                store.markSent(key)
                BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SENT)
            }
            else -> BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_DISPATCH)
        }
    }
}
