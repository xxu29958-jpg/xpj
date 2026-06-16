package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.ui.components.AppFilterChip

/**
 * ADR-0049 §7.0 / 设计稿 8e-6a：**纯外部债**还债计划的「先清小的」(snowball) 排序。
 *
 * §7.0 红线：成员债 = Communal（共同的事，各自那份），**不是** Market 心智的还债引擎——成员/混装计划
 * **不做**清偿排序器/三态/还清日期投影。清偿排序只属于 **纯外部债**计划（composition == External，
 * 由调用方 gate；**用 `== External` 不是 `!= Member`**，否则会误纳 Mixed）。
 *
 * 本切片只有**升序一档「先清小的」**，刻意收窄到最小诚实赢：
 *  - **avalanche（按利率降序）永久砍掉**：后端零 `interest_rate/apr/minimum_payment` 字段，按利率排序是
 *    伪能力，会暗示一个并不存在的省息收益（红线 R3，零利率冻结本金模型）。
 *  - **「先清大的」降序也砍掉**：零利率下大额优先没有任何诚实的财务依据，是 avalanche 的动机壳（对抗审 Major）。
 *
 * 排序是纯展示派生态（transient，无持久化/无 DataStore/无后端列），对**冻结快照**做纯客户端算术
 * （[DebtGoalLink] 上的字段）；**永远返回新列表、不改源 list**，以保 `items(key=)` 的稳定（对抗审 C2）。
 */
enum class DebtPlanSortMode {
    /** 原始关联顺序（后端返回序）。 */
    Default,

    /** 「先清小的」：仍待清的欠款按剩余金额升序在前（小额先清=快速赢）；已两清/已作废沉到末尾。 */
    SmallestRemainingFirst,
}

/**
 * 对关联欠款应用 [mode]，返回**新列表**（[DebtPlanSortMode.Default] 原样返回，不复制也不改序）。
 *
 * [DebtPlanSortMode.SmallestRemainingFirst]：仍进行中的（open）排前、按剩余金额升序（先清小的）；
 * 已两清 / 已作废沉到「待清」之后并保持各自原有相对顺序——「先清小的」指「你还要清的里头最小的」，
 * 把已完成 / 已放弃的放在待清之后才诚实（cleared 的剩余为 0，直接全列排序会把它误浮到「最该先清」的顶部）。
 */
internal fun List<DebtGoalLink>.sortedForPlan(mode: DebtPlanSortMode): List<DebtGoalLink> =
    when (mode) {
        DebtPlanSortMode.Default -> this
        DebtPlanSortMode.SmallestRemainingFirst ->
            // sortedWith 是稳定排序：同桶内（cleared / voided 次键恒 0）保持源顺序。
            sortedWith(
                compareBy<DebtGoalLink> { it.payoffSortRank }
                    .thenBy { if (it.isOpen) it.remainingAmountCents else 0L },
            )
    }

/** 排序桶：进行中(0) → 已两清(1) → 已作废(2)，保证「待清」始终排在已完成/已放弃之前。 */
private val DebtGoalLink.payoffSortRank: Int
    get() = when {
        isVoided -> 2
        isCleared -> 1
        else -> 0
    }

/**
 * 「先清小的」单 toggle（[AppFilterChip]）。**只在纯外部债计划渲染**（调用方 gate composition == External）；
 * 选中 → snowball 升序，取消 → 原顺序。状态由调用方持有的 composable-local 态驱动（无持久化）。
 */
@Composable
internal fun DebtPlanSortToggle(
    mode: DebtPlanSortMode,
    onModeChange: (DebtPlanSortMode) -> Unit,
    modifier: Modifier = Modifier,
) {
    val selected = mode == DebtPlanSortMode.SmallestRemainingFirst
    AppFilterChip(
        label = stringResource(R.string.debt_plan_sort_smallest_first),
        selected = selected,
        onClick = {
            onModeChange(
                if (selected) DebtPlanSortMode.Default else DebtPlanSortMode.SmallestRemainingFirst,
            )
        },
        modifier = modifier,
    )
}
