package com.ticketbox.notification.recurring

import com.ticketbox.domain.model.RecurringItem
import java.time.LocalDate
import java.time.format.DateTimeParseException

/**
 * ADR-0046 Slice 2: 固定支出提醒的纯 JVM 业务判定层。零 Android 依赖、零 IO，
 * 可直测（本模块无 Robolectric，业务真值必须落在纯 Kotlin 层——见 ADR Contract 1/2）。
 *
 * 提醒种类。区分「即将到期」与「已逾期」是为了：
 * - 去重 key 的最后一段（同一 expectedDate 允许到期前提醒一次、逾期后再提醒一次）；
 * - 未来（Slice 8）给两类配不同文案；当前 MVP 两类共用同一 content spec（ADR Contract 7）。
 */
enum class RecurringReminderKind { DUE_SOON, OVERDUE }

/**
 * 一条提醒决策。由 [RecurringReminderPolicy.evaluate] 产出，承载去重 key + 通知上下文。
 *
 * @property key 去重 sent-key，格式见 [recurringReminderSentKey]。
 * @property kind 即将到期 / 已逾期。
 * @property ledgerId 账本隔离段（防多账本串台）。
 * @property itemPublicId 固定支出项 public_id。
 * @property merchant 固定支出名 / 商家，进通知标题占位符（dispatcher 负责 blank fallback）。
 * @property expectedDate 后端返回的 next_expected_date，已解析为 [LocalDate]。
 */
data class RecurringReminderDecision(
    val key: String,
    val kind: RecurringReminderKind,
    val ledgerId: String,
    val itemPublicId: String,
    val merchant: String,
    val expectedDate: LocalDate,
)

/**
 * 去重 sent-key 构造（ADR Contract 5，单一真源）：
 *
 *     v1:{ledgerId}:{itemPublicId}:{expectedDate}:{kind}
 *
 * - `v1:` 前缀给 key 格式留版本位（未来加 snooze / history 升级时可识别旧 key）；
 * - `ledgerId` 防多账本串台；
 * - `itemPublicId` 锁定固定支出项；
 * - `expectedDate` 允许下一周期换了预期日期后重新提醒（ISO `yyyy-MM-dd`）；
 * - `kind` 区分 DUE_SOON / OVERDUE / 未来 AMOUNT_ANOMALY，使到期前后各提醒一次。
 *
 * 纯函数：同一输入恒定产出同一 key（StoreTest / PolicyTest 都钉这个稳定性）。
 */
fun recurringReminderSentKey(
    ledgerId: String,
    itemPublicId: String,
    expectedDate: LocalDate,
    kind: RecurringReminderKind,
): String = "v1:$ledgerId:$itemPublicId:$expectedDate:${kind.name}"

/**
 * MVP 提醒策略（ADR Contract 3）。**只消费 [RecurringItem.nextExpectedDate]，绝不读 frequency**
 * （当前后端 frequency 只有 monthly，但提醒层不得写死 monthly——多频率 recurring 落地时此层不需改）。
 *
 * 判定（OVERDUE 优先于 DUE_SOON）：
 *
 *     status != "active"                            -> NONE
 *     nextExpectedDate 缺失 / 不可解析              -> NONE（item-level skip，不让单条坏日期炸全局）
 *     nextExpectedDate < today                      -> OVERDUE
 *     today <= nextExpectedDate <= today + 7 天      -> DUE_SOON
 *     否则（窗口外的未来日期）                       -> NONE
 *
 * [today] 由可注入 clock / date provider 提供（[RecurringReminderEngine] 传入），便于测试钉边界。
 */
class RecurringReminderPolicy(
    private val dueSoonWindowDays: Long = DUE_SOON_WINDOW_DAYS,
) {
    /**
     * 对单条 item 求值。返回 null = 不提醒（NONE）。日期不可解析按 NONE 处理（item-level skip），
     * 解析失败本身不抛出——编排层据此「跳过该 item、轻量日志、不让整个 worker 失败」（Contract 8）。
     */
    fun evaluate(today: LocalDate, item: RecurringItem): RecurringReminderDecision? {
        if (item.status != STATUS_ACTIVE) return null
        val expectedDate = parseExpectedDate(item.nextExpectedDate) ?: return null
        val kind = when {
            expectedDate.isBefore(today) -> RecurringReminderKind.OVERDUE
            !expectedDate.isAfter(today.plusDays(dueSoonWindowDays)) -> RecurringReminderKind.DUE_SOON
            else -> return null
        }
        return RecurringReminderDecision(
            key = recurringReminderSentKey(item.ledgerId, item.publicId, expectedDate, kind),
            kind = kind,
            ledgerId = item.ledgerId,
            itemPublicId = item.publicId,
            merchant = item.merchant,
            expectedDate = expectedDate,
        )
    }

    /** 解析 ISO `yyyy-MM-dd`；null / 空白 / 非法格式一律返回 null（上游按 NONE 处理）。 */
    private fun parseExpectedDate(raw: String?): LocalDate? {
        val trimmed = raw?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        return try {
            LocalDate.parse(trimmed)
        } catch (_: DateTimeParseException) {
            null
        }
    }

    companion object {
        /** ADR Contract 3 / Contract 9：到期前提醒窗口（天）。 */
        const val DUE_SOON_WINDOW_DAYS: Long = 7

        /** 只对 active 固定支出提醒；paused / archived / 未知状态一律 NONE。 */
        const val STATUS_ACTIVE = "active"
    }
}
