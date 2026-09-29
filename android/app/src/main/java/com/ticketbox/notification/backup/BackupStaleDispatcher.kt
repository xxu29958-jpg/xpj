package com.ticketbox.notification.backup

/**
 * 一条备份超龄提醒的判定结果(engine 产出,dispatcher 消费)。
 *
 * @property key 日级 sent-key([backupStaleSentKey]),同时用作通知栏覆盖 tag。
 * @property ageHours 备份年龄(小时,服务端算好);null=服务器上没有任何备份。
 */
data class BackupStaleDecision(
    val key: String,
    val ageHours: Int?,
)

/**
 * 一次备份超龄提醒投递的结果。**只有 [SENT] 允许 markSent**(镜像 recurring Contract 6:
 * 权限/开关拒绝写假「已提醒」会让当天再也不响)。
 */
enum class BackupStaleDispatchOutcome {
    SENT,
    SKIPPED_DISABLED,
    SKIPPED_PERMISSION_DENIED,
}

/**
 * 把一条 [BackupStaleDecision] 交给 Android 通知出口的接缝——engine 依赖本接口而非
 * 具体 notifier,EngineTest 用 fake 钉「SENT 才 markSent」。实现不得拉 API、判 stale、
 * 维护 sent-key。
 */
fun interface BackupStaleDispatcher {
    fun dispatch(decision: BackupStaleDecision, binding: com.ticketbox.data.repository.LogicalSessionBinding): BackupStaleDispatchOutcome
}
