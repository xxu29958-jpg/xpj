package com.ticketbox.ui.screens

import com.ticketbox.viewmodel.RecurringListLoadState

internal data class RecurringListSectionModel<T>(
    val rows: List<T>,
    val bodyState: ReadableListBodyState,
)

internal fun recurringListBodyState(
    hasRows: Boolean,
    loadState: RecurringListLoadState,
): ReadableListBodyState = when {
    hasRows -> ReadableListBodyState.Content
    loadState == RecurringListLoadState.Loaded -> ReadableListBodyState.Empty
    loadState == RecurringListLoadState.Failed -> ReadableListBodyState.LoadFailed
    else -> ReadableListBodyState.Loading
}

/**
 * generic mutation / manual save 任一在途时，屏上 generic 命令入口
 * （行内编辑与生命周期键、采用建议、添加）统一禁用。真正的并发防线是
 * ViewModel 的 hard guard；这里只保证仍被渲染的入口不产生死点击。
 */
internal fun recurringCommandsEnabled(
    manualSaveInFlight: Boolean,
    mutationInFlight: Boolean,
): Boolean = !manualSaveInFlight && !mutationInFlight

/**
 * 屏级活动信号：刷新语义不变；generic mutation 在途时即使有可读数据也必须亮
 * 全局「正在工作」信号——in-flight 是架构状态，不是 UI 收尾。
 */
internal fun recurringScreenActivityActive(
    loading: Boolean,
    hasReadableData: Boolean,
    mutationInFlight: Boolean,
): Boolean = ReadableRefreshIndicator.isActive(loading, hasReadableData) || mutationInFlight
