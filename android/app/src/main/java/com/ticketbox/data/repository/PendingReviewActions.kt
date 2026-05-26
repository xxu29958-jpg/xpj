package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

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
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()
    fun currentActiveLedgerId(): String? = null
    suspend fun fetchPending(): Result<List<Expense>>
    suspend fun fetchThumbnail(id: Long): Result<ProtectedImage>
    suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense? = null,
    ): Result<Expense>
    // ADR-0038 PR-2b: 状态机 POST 必须带 expected_updated_at（client
    // 上次看到的 baseline.updatedAt）。Stale 写入 → 409，由 errorHandler
    // 映射到 RepositoryException 让 UI 提示刷新。
    suspend fun confirmExpense(id: Long, expectedUpdatedAt: String): Result<Expense>
    suspend fun rejectExpense(id: Long, expectedUpdatedAt: String): Result<Expense>
    suspend fun markNotDuplicate(id: Long, expectedUpdatedAt: String): Result<Expense>
    suspend fun categories(): Result<List<String>>
    suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long? = null,
        sourceSizeBytes: Long? = null,
        expectedLedgerId: String? = null,
    ): Result<Long>
}
