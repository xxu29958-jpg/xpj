package com.ticketbox.ui.screens.recurring

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.data.repository.RecurringDateEdit
import com.ticketbox.data.repository.RecurringItemPatch
import com.ticketbox.data.repository.RecurringPendingKind
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.screens.RecurringListSectionModel
import com.ticketbox.ui.screens.recurringListBodyState
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringUiState
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * 固定支出屏的纯 UI 模型层：金额合计、行 meta、tab 派生、表单 patch/提交判定全部
 * 在这里算好，Composable 只做渲染。约束（A3 纵向片合同）：
 * - hero 总额只计 active 已发布项的 baseline（计划金额）；待同步 intent 一律不进总额。
 * - source=manual 且 occurrence_count=0 的项，baseline 语义是「每月计划金额」，
 *   不得露出「0 次 / 最近发生」这类观察语义；只有 occurrenceCount>0 才给观察 meta。
 */

internal enum class RecurringTab(@param:StringRes val labelRes: Int) {
    Upcoming(R.string.recurring_tab_upcoming),
    Active(R.string.recurring_tab_active),
    Paused(R.string.recurring_tab_paused),
    Archived(R.string.recurring_tab_archived),
}

/**
 * 默认 tab 是 Active（全集）：新建项允许无提醒日期，若默认落在 Upcoming，
 * 保存后条目会从默认列表消失——对手工 registry 是真实便利性反例。
 * Upcoming 保留为「带了下次日期」的快捷筛选。
 */
internal val recurringDefaultTab: RecurringTab = RecurringTab.Active

internal data class RecurringHeroModel(
    /** false = 列表尚未给出可读事实（读取中 / 待刷新），总额不可信，不渲染数字。 */
    val factual: Boolean,
    val totalCents: Long,
    val activeCount: Int,
    val nearestNextDate: String?,
)

internal fun recurringHeroModel(
    items: List<RecurringItem>,
    loadState: RecurringListLoadState,
): RecurringHeroModel {
    val active = items.filter { it.status == "active" }
    return RecurringHeroModel(
        factual = items.isNotEmpty() || loadState == RecurringListLoadState.Loaded,
        totalCents = active.sumOf { it.baselineAmountCents },
        activeCount = active.size,
        nearestNextDate = active.mapNotNull { it.nextExpectedDate }.minOrNull(),
    )
}

/** durable pending 也是可读内容：纯离线待同步时不得当作空页（影响刷新指示与空态判断）。 */
internal fun recurringHasReadableData(state: RecurringUiState): Boolean =
    state.items.isNotEmpty() || state.candidates.isNotEmpty() || state.pendingIntents.isNotEmpty()

internal data class RecurringItemMeta(
    val nextExpectedDate: String?,
    /** occurrenceCount>0 才非空：观察来源（候选确认）项的记录次数。 */
    val observedCount: Int?,
    /** 最近一次观测日期（yyyy-MM-dd），仅观察项有。 */
    val lastObservedDate: String?,
    val anomalyDeltaPercent: Int?,
)

internal fun recurringItemMeta(item: RecurringItem): RecurringItemMeta {
    val observed = item.occurrenceCount > 0
    return RecurringItemMeta(
        nextExpectedDate = item.nextExpectedDate,
        observedCount = if (observed) item.occurrenceCount else null,
        lastObservedDate = if (observed) item.lastSeenAt?.take(10) else null,
        anomalyDeltaPercent = item.amountDeltaPercent
            .takeIf { item.anomalyStatus == "higher_than_average" },
    )
}

internal data class RecurringTabCounts(
    /** active 且 nextExpectedDate 非空（即「即将」的真实集合），不与活跃计数混用。 */
    val upcoming: Int,
    val active: Int,
    val paused: Int,
    val archived: Int,
    val factual: Boolean,
)

internal data class RecurringDerivedModel(
    val hero: RecurringHeroModel,
    val selectedTab: RecurringTab,
    val counts: RecurringTabCounts,
    val itemSection: RecurringListSectionModel<RecurringItem>,
    val candidateSection: RecurringListSectionModel<RecurringCandidate>,
    val canModify: Boolean,
)

/** 一屏的派生态：tab 过滤排序、分段 bodyState、hero、计数，一次算完。 */
internal fun recurringScreenDerived(state: RecurringUiState, tab: RecurringTab): RecurringDerivedModel {
    val active = state.items.filter { it.status == "active" }
    val paused = state.items.filter { it.status == "paused" }
    val archived = state.items.filter { it.status == "archived" }
    // 即将 ≠ 活跃换序：严格定义为 active 且下次日期非空；无日期项只留在活跃。
    val upcoming = active.filter { it.nextExpectedDate != null }
    val visible = when (tab) {
        RecurringTab.Upcoming -> upcoming.sortedWith(
            compareBy<RecurringItem> { it.nextExpectedDate }.thenBy { it.merchant },
        )
        RecurringTab.Active -> active.sortedBy { it.merchant }
        RecurringTab.Paused -> paused.sortedBy { it.merchant }
        RecurringTab.Archived -> archived.sortedBy { it.merchant }
    }
    return RecurringDerivedModel(
        hero = recurringHeroModel(state.items, state.itemsLoadState),
        selectedTab = tab,
        counts = RecurringTabCounts(
            upcoming = upcoming.size,
            active = active.size,
            paused = paused.size,
            archived = archived.size,
            factual = state.items.isNotEmpty() || state.itemsLoadState == RecurringListLoadState.Loaded,
        ),
        itemSection = RecurringListSectionModel(
            rows = visible,
            bodyState = recurringListBodyState(visible.isNotEmpty(), state.itemsLoadState),
        ),
        candidateSection = RecurringListSectionModel(
            rows = state.candidates,
            bodyState = recurringListBodyState(state.candidates.isNotEmpty(), state.candidatesLoadState),
        ),
        canModify = state.canModify,
    )
}

/** 新建表单默认建议的下次日期：下月同日（LocalDate 自动处理月末回退）。 */
internal fun recurringDefaultNextDate(today: LocalDate = LocalDate.now()): String =
    today.plusMonths(1).toString()

/** DatePicker 的 millis（UTC 当日零点）→ 后端 date 语义 yyyy-MM-dd。 */
internal fun recurringPickerMillisToDateIso(millis: Long): String =
    Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate().toString()

private val recurringDisplayDateFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy年M月d日")

/** yyyy-MM-dd（或 ISO 日期时间取日期段）→ 2026年9月15日；解析失败原样透出，不猜。 */
internal fun recurringDisplayDate(value: String?): String {
    if (value.isNullOrBlank()) return ""
    return runCatching { LocalDate.parse(value.take(10)).format(recurringDisplayDateFormatter) }
        .getOrElse { value }
}

/**
 * 由表单输入构造编辑 patch：与基线一致的字段不落 patch（patch 里 null/unchanged = 不改）。
 * 什么都没改时返回 null，调用方直接关表单，不发空 patch（后端 require_edit 会拒）。
 */
internal fun buildRecurringItemPatch(
    baseline: RecurringItem,
    merchant: String,
    baselineAmountCents: Long,
    dateTouched: Boolean,
    nextExpectedDate: String?,
): RecurringItemPatch? {
    val merchantEdit = merchant.trim().takeIf { it != baseline.merchant }
    val amountEdit = baselineAmountCents.takeIf { it != baseline.baselineAmountCents }
    val dateEdit = if (dateTouched && nextExpectedDate != baseline.nextExpectedDate) {
        RecurringDateEdit.changed(nextExpectedDate)
    } else {
        RecurringDateEdit.unchanged()
    }
    if (merchantEdit == null && amountEdit == null && !dateEdit.changed) return null
    return RecurringItemPatch(
        merchant = merchantEdit,
        baselineAmountCents = amountEdit,
        nextExpectedDate = dateEdit,
    )
}

@StringRes
internal fun recurringPendingKindLabelRes(kind: RecurringPendingKind): Int = when (kind) {
    RecurringPendingKind.CREATE -> R.string.recurring_pending_kind_create
    RecurringPendingKind.UPDATE -> R.string.recurring_pending_kind_update
}
