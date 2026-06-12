package com.ticketbox.notification.recurring

import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.domain.model.RecurringItem

/**
 * ADR-0046 Slice 4 / Contract 4：提醒候选的**只读**来源。
 *
 * 当前唯一实现读后端 API（经 [RecurringActions.items]）。禁止任何写：不创建 pending、不确认账单、
 * 不推进 next_expected_date、不改 recurring 状态、不写服务端「已提醒」状态——next_expected_date
 * 的自动推进是另一项准确性问题，必须单独 PR/ADR（Contract 4），不混进本检测源。
 *
 * 接口稳定性即扩展性（Contract 12）：未来 local cache source / push-triggered source 换实现即可，
 * engine / policy / store / dispatcher 不动。
 */
fun interface RecurringReminderSource {
    suspend fun activeItems(): Result<List<RecurringItem>>
}

/**
 * 生产实现：拉当前 active ledger 的 active 固定支出（`status="active"`, `includeArchived=false`）。
 *
 * 失败（网络 / API / 账本切换）原样透传 [Result.failure]——由 [RecurringReminderEngine] 决定降级
 * （映射成 transient failure → worker retry，不 mark sent，见 Contract 8）。本类不吞错、不补偿。
 */
class RepositoryRecurringReminderSource(
    private val recurring: RecurringActions,
) : RecurringReminderSource {
    override suspend fun activeItems(): Result<List<RecurringItem>> =
        recurring.items(status = STATUS_ACTIVE, includeArchived = false)

    private companion object {
        const val STATUS_ACTIVE = "active"
    }
}
