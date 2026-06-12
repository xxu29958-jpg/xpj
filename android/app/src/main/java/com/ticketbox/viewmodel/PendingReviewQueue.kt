package com.ticketbox.viewmodel

import com.ticketbox.domain.model.Expense

/**
 * 连续审阅（批量过堆积的待确认票）的纯队列口径。
 *
 * 快补 sheet 保存成功后自动载入「下一条仍缺同一字段」的待确认票（/web 批 10
 * 「保存并下一笔」的 Android 镜像）。这里只做纯计算——给定当前 pending 列表、
 * 缺字段类型、当前票 id、本轮已跳过 id 集合，算出下一条目标与「还剩 N 条」。
 * 没有任何 Compose / Repository 依赖，全部可单测；VM 与 Screen 都不重写这套口径。
 *
 * **序列口径**：沿用 [PendingUiState.items] 的现有顺序（后端 `created_at DESC`，
 * 与列表渲染、筛选条一致），不自创排序。
 *
 * **跳过语义**：跳过的票留在 pending 列表里（不出队、不改后端状态），只是在
 * **本轮连续审阅**里被排除——靠 `skippedIds` 集合实现，下一条永远朝列表后方走，
 * 不会绕回已跳过的票。换账本 / 关闭 sheet / 从列表重新发起一轮即清空该集合。
 */
internal enum class ReviewField {
    AMOUNT,
    MERCHANT,
    CATEGORY,
    ;

    /** 该票是否仍缺本字段（与列表 / 滑动动作的「缺字段」判定同源）。 */
    fun isMissing(expense: Expense): Boolean = when (this) {
        AMOUNT -> expense.amountCents == null
        MERCHANT -> expense.merchant.isNullOrBlank()
        CATEGORY -> expense.category.isBlank()
    }
}

internal object PendingReviewQueue {

    /**
     * 本轮连续审阅里仍待补本字段的票（含当前票，若它还缺）：列表顺序、排除
     * `skippedIds`。「还剩 N 条」计数即取本结果的 size。
     */
    fun remaining(
        items: List<Expense>,
        field: ReviewField,
        skippedIds: Set<Long>,
    ): List<Expense> = items.filter { field.isMissing(it) && it.id !in skippedIds }

    /**
     * 当前票处理（保存 / 跳过）后应载入的下一条：列表里**当前票之后**第一条仍缺
     * 本字段且未被跳过的票；当前票之后没有时，回到列表开头继续找（环绕一圈，
     * 不重复扫当前票），都没有则返回 null（队列耗尽 → 调用方关闭 sheet）。
     *
     * 永远排除 [currentId] 本身：保存成功后该票已不缺字段会自然落选，但跳过时
     * 它仍缺字段，必须靠 id 显式排除才不会原地打转。
     */
    fun nextTarget(
        items: List<Expense>,
        field: ReviewField,
        currentId: Long,
        skippedIds: Set<Long>,
    ): Expense? {
        val candidates = items.filter {
            it.id != currentId && field.isMissing(it) && it.id !in skippedIds
        }
        if (candidates.isEmpty()) return null
        val currentIndex = items.indexOfFirst { it.id == currentId }
        if (currentIndex < 0) return candidates.first()
        // 当前票之后的第一条候选；没有则环绕取列表里靠前的第一条候选。
        return candidates.firstOrNull { items.indexOf(it) > currentIndex } ?: candidates.first()
    }
}
