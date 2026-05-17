package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage

/**
 * v0.4-alpha4 M1：PendingViewModel 依赖反转用接口。
 *
 * 抽出 PendingViewModel + Review Action 扩展所用到的 8 个 Repository 方法，
 * 便于在单元测试里以 Fake 实现替换 [ExpenseRepository]，
 * 而不必拖动 Retrofit / Room / DataStore 等真实依赖。
 *
 * 注意：仅声明 Review 流程必需的方法；其它 Repository 能力仍直接挂在
 * [ExpenseRepository] 上，本接口不负责。
 */
interface PendingReviewActions {
    fun canModifyLedger(): Boolean = true
    suspend fun fetchPending(): Result<List<Expense>>
    suspend fun fetchThumbnail(id: Long): Result<ProtectedImage>
    suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense? = null,
    ): Result<Expense>
    suspend fun confirmExpense(id: Long): Result<Expense>
    suspend fun rejectExpense(id: Long): Result<Expense>
    suspend fun markNotDuplicate(id: Long): Result<Expense>
    suspend fun categories(): Result<List<String>>
    suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long? = null,
        sourceSizeBytes: Long? = null,
    ): Result<Long>
}
