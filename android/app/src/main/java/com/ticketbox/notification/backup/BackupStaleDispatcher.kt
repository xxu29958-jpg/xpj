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
    fun dispatch(decision: BackupStaleDecision): BackupStaleDispatchOutcome
}

/**
 * 生产实现:把备份年龄折算成「天」字符串(stale 阈值=48h,故 stale 时恒 ≥2 天;
 * [BackupStaleDecision.ageHours]=null 表示从未有备份,传 null 让 notifier 选
 * 「还没有任何备份」文案变体),委托
 * [TicketboxNotifier.onBackupStale][com.ticketbox.notification.TicketboxNotifier.onBackupStale]。
 *
 * 窄函数接缝 `(daysText, dedupeTag) -> outcome`(镜像 budget / recurring 适配器):
 * AppContainer 用 `notifier::onBackupStale` 接线,测试注 lambda 直测折算与透传。
 */
class NotifierBackupStaleDispatcher(
    private val onBackupStale: (daysText: String?, dedupeTag: String) -> BackupStaleDispatchOutcome,
) : BackupStaleDispatcher {
    override fun dispatch(decision: BackupStaleDecision): BackupStaleDispatchOutcome =
        onBackupStale(decision.ageHours?.let { (it / HOURS_PER_DAY).toString() }, decision.key)

    private companion object {
        const val HOURS_PER_DAY = 24
    }
}
