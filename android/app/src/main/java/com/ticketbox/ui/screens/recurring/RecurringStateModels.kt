package com.ticketbox.ui.screens.recurring

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringPendingKind
import com.ticketbox.data.repository.RecurringPendingState
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.viewmodel.RecurringDuplicateConflict

/**
 * 待同步 intent / 重复冲突 / 行能力的纯解析层。全部由 [com.ticketbox.viewmodel.RecurringUiState]
 * 派生，不另造 UI 状态 Owner；conflict/failed 一律不冒充已发布事实。
 */

internal data class RecurringRowCapabilities(
    /** active/paused 可编辑；archived 只能恢复，不给编辑。 */
    val editable: Boolean,
    /** 暂停 / 恢复 / 归档 生命周期动作（仅 active/paused）。 */
    val lifecycleActions: Boolean,
    /** archived 独立可访问并提供恢复。 */
    val restorable: Boolean,
)

internal fun recurringRowCapabilities(status: String): RecurringRowCapabilities = when (status) {
    "active", "paused" -> RecurringRowCapabilities(
        editable = true,
        lifecycleActions = true,
        restorable = false,
    )
    "archived" -> RecurringRowCapabilities(
        editable = false,
        lifecycleActions = false,
        restorable = true,
    )
    else -> RecurringRowCapabilities(
        editable = false,
        lifecycleActions = false,
        restorable = false,
    )
}

internal enum class RecurringConflictAction {
    /** active/paused 冲突：查看 / 编辑现有记录。 */
    EditExisting,

    /** archived 冲突：用 items 中同 publicId 的真实 rowVersion 恢复这条记录。 */
    RestoreArchived,

    /** 列表里解析不到真实记录：不给按钮，只给诚实说明。 */
    Unavailable,
}

internal data class RecurringConflictModel(
    val publicId: String,
    val status: String,
    val merchant: String?,
    val rowVersion: Long?,
    val action: RecurringConflictAction,
)

internal fun resolveRecurringDuplicateConflict(
    conflict: RecurringDuplicateConflict?,
    items: List<RecurringItem>,
    ownerLoaded: Boolean,
): RecurringConflictModel? {
    if (conflict == null) return null
    val existing = items.firstOrNull { it.publicId == conflict.publicId }
    if (!ownerLoaded) {
        return RecurringConflictModel(
            publicId = conflict.publicId,
            status = conflict.status,
            merchant = null,
            rowVersion = null,
            action = RecurringConflictAction.Unavailable,
        )
    }
    val resolvedStatus = existing?.status ?: conflict.status
    val action = when {
        existing == null -> RecurringConflictAction.Unavailable
        resolvedStatus == "active" || resolvedStatus == "paused" -> RecurringConflictAction.EditExisting
        resolvedStatus == "archived" -> RecurringConflictAction.RestoreArchived
        else -> RecurringConflictAction.Unavailable
    }
    return RecurringConflictModel(
        publicId = conflict.publicId,
        status = resolvedStatus,
        merchant = existing?.merchant,
        rowVersion = existing?.rowVersion,
        action = action,
    )
}

/** UPDATE intent 只存 changed fields；这里把改动逐项翻成用户可读片段。 */
internal sealed interface RecurringPendingChange {
    data class MerchantTo(val value: String) : RecurringPendingChange
    data class AmountTo(val cents: Long) : RecurringPendingChange
    data class DateTo(val iso: String) : RecurringPendingChange
    data object DateCleared : RecurringPendingChange
}

internal data class RecurringPendingRowModel(
    /** 已解析名称；null 时用 [titleFallbackRes]，绝不伪称「未填写商家」。 */
    val title: String?,
    @param:StringRes val titleFallbackRes: Int,
    /** 展示用金额：intent 新值优先，UPDATE 无新值时回落已发布基线（上下文，不计 hero）。 */
    val amountCents: Long?,
    @param:StringRes val kindLabelRes: Int,
    @param:StringRes val stateLabelRes: Int,
    /** CONFLICT/FAILED 指引去既有全局同步入口；本片不造局部 resolve 按钮。 */
    @param:StringRes val stateGuidanceRes: Int?,
    val changes: List<RecurringPendingChange>,
)

internal fun resolveRecurringPendingRow(
    intent: RecurringPendingIntent,
    items: List<RecurringItem>,
): RecurringPendingRowModel {
    val baseline = intent.publicId?.let { pid -> items.firstOrNull { it.publicId == pid } }
    // 「改为 …」清单只属于 UPDATE；CREATE 行本身就在展示新草稿（名称/金额/日期），不重复。
    val changes = if (intent.kind == RecurringPendingKind.CREATE) {
        emptyList()
    } else {
        buildList {
            intent.merchant?.takeIf { it.isNotBlank() }?.let { add(RecurringPendingChange.MerchantTo(it)) }
            intent.baselineAmountCents?.let { add(RecurringPendingChange.AmountTo(it)) }
            if (intent.nextExpectedDateChanged) {
                add(
                    intent.nextExpectedDate
                        ?.let { RecurringPendingChange.DateTo(it) }
                        ?: RecurringPendingChange.DateCleared,
                )
            }
        }
    }
    val title = intent.merchant?.takeIf { it.isNotBlank() } ?: baseline?.merchant
    return RecurringPendingRowModel(
        title = title,
        titleFallbackRes = if (intent.kind == RecurringPendingKind.UPDATE) {
            R.string.recurring_pending_update_unknown
        } else {
            R.string.recurring_item_merchant_fallback
        },
        amountCents = intent.baselineAmountCents ?: baseline?.baselineAmountCents,
        kindLabelRes = recurringPendingKindLabelRes(intent.kind),
        stateLabelRes = recurringPendingStateLabelRes(intent.state),
        stateGuidanceRes = recurringPendingStateGuidanceRes(intent.state),
        changes = changes,
    )
}

@StringRes
private fun recurringPendingStateLabelRes(state: RecurringPendingState): Int = when (state) {
    RecurringPendingState.WAITING -> R.string.recurring_pending_state_waiting
    RecurringPendingState.CONFLICT -> R.string.recurring_pending_state_conflict
    RecurringPendingState.FAILED -> R.string.recurring_pending_state_failed
}

@StringRes
private fun recurringPendingStateGuidanceRes(state: RecurringPendingState): Int? = when (state) {
    RecurringPendingState.WAITING -> null
    RecurringPendingState.CONFLICT,
    RecurringPendingState.FAILED -> R.string.recurring_pending_state_guidance
}
