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
    /**
     * Direct PATCH only — no outbox fallback. Use this for chained
     * flows that hand ``saved.updatedAt`` to a follow-up POST (e.g.
     * ``confirmExpense`` / ``saveAmountAndConfirm``); a stale
     * baseline returned from an offline queue would break the
     * chain.
     *
     * For "save and forget" call sites that don't chain (e.g. the
     * edit screen's standalone 保存 button), use
     * [saveExpenseAllowingOffline] instead.
     */
    suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense? = null,
    ): Result<Expense>

    /**
     * ADR-0038 PR-2g.3 round-8 P2: offline-aware save returning a
     * sealed [SaveOutcome] so the caller can tell synced from
     * queued state. Used by [com.ticketbox.viewmodel.ExpenseEditViewModel.save]
     * which doesn't chain on the returned token and can therefore
     * tolerate "queued offline" outcomes by showing a different UI
     * message (``"已离线保存，联网后同步"`` vs ``"已保存"``).
     *
     * Behaviour:
     *  - direct 2xx → [SaveOutcome.Synced] with the server-returned
     *    [Expense] (canonical ``updatedAt`` token).
     *  - IOException (and only IOException) → [SaveOutcome.Queued]
     *    with an *optimistic* [Expense] built by applying [draft]
     *    over [baseline]; the row is persisted in the outbox and
     *    the worker (PR-2g.2) replays it on connectivity-up.
     *  - HttpException (409 / 4xx / 5xx etc.) → ``Result.failure``
     *    so the user sees the actual server problem.
     *
     * Pre-condition: [baseline] MUST be non-null AND carry a valid
     * ``updatedAt`` token — otherwise the outbox row would lack
     * the optimistic-concurrency token the server expects and the
     * call falls back to a hard failure.
     */
    suspend fun saveExpenseAllowingOffline(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense,
    ): Result<SaveOutcome>
    // ADR-0038 PR-2b: 状态机 POST 必须带 expected_row_version（client
    // 上次看到的 baseline.updatedAt）。Stale 写入 → 409，由 errorHandler
    // 映射到 RepositoryException 让 UI 提示刷新。
    //
    // These DIRECT variants surface IOException as Result.failure with
    // NO outbox fallback — kept for chained flows (save→confirm /
    // saveAmount→confirm) where the follow-up POST consumes the
    // returned token; a silently queued row would let the chain
    // dispatch against a stale baseline. Standalone single-tap
    // confirm/reject (PendingViewModel.confirm/reject,
    // ExpenseEditViewModel.reject) use the *AllowingOffline variants
    // below instead.
    suspend fun confirmExpense(id: Long, expectedRowVersion: Long): Result<Expense>
    suspend fun rejectExpense(id: Long, expectedRowVersion: Long): Result<Expense>
    suspend fun markNotDuplicate(id: Long, expectedRowVersion: Long): Result<Expense>

    /**
     * ADR-0038 PR-2g.7: offline-aware confirm / reject. Mirrors
     * [saveExpenseAllowingOffline] for the state-machine POSTs.
     *
     *  - direct 2xx → [ExpenseStateOutcome.Synced] with the server
     *    expense (canonical post-transition ``updatedAt``).
     *  - IOException (and only IOException) → [ExpenseStateOutcome.Queued]
     *    with an optimistic projection ([Expense.status] flipped to
     *    ``confirmed`` / ``rejected``); the row is enqueued
     *    (``ConfirmExpense`` / ``RejectExpense``) and the worker
     *    replays it on connectivity-up.
     *  - HttpException (409 / 4xx / 5xx) → ``Result.failure`` so the
     *    user sees the real server problem.
     *
     * Takes the whole [expense] (not just id + token) because the
     * Queued branch needs the baseline fields to build the optimistic
     * projection — the same reason [saveExpenseAllowingOffline] takes
     * a baseline. ``expense.updatedAt`` is the optimistic-concurrency
     * token persisted on the outbox row.
     */
    suspend fun confirmExpenseAllowingOffline(expense: Expense): Result<ExpenseStateOutcome>
    suspend fun rejectExpenseAllowingOffline(expense: Expense): Result<ExpenseStateOutcome>

    /**
     * ADR-0038 undo: restore a recently-rejected expense within the 5-min
     * server-side retention window. Online-only — call this only after an
     * [ExpenseStateOutcome.Synced] reject (the server actually holds a
     * rejected row to flip back). A Queued reject's row is sitting in the
     * outbox, not on the server, so there's nothing for /undo to find.
     *
     *  - 200 → ``Result.success(Expense)`` with status=pending, rejected_at=null.
     *  - 404 ``expense_not_found`` (past window / wrong status / cross-tenant /
     *    missing-row collapse) → ``Result.failure``. UI flashes "无法撤销..."
     *    and stops showing the undo affordance.
     *  - IOException / 5xx → ``Result.failure``; no outbox fallback (undo is a
     *    short-window UI nudge, not a durable mutation worth queueing).
     */
    suspend fun undoRejectExpense(id: Long, expectedRowVersion: Long): Result<Expense>

    /**
     * ADR-0038 PR-2g.8: offline-aware mark-not-duplicate. Same
     * contract as [confirmExpenseAllowingOffline] but the optimistic
     * projection flips [Expense.duplicateStatus] to ``none`` and the
     * row STAYS in the pending list (mark-not-duplicate keeps the
     * expense; it just clears the suspected-duplicate badge).
     */
    suspend fun markNotDuplicateAllowingOffline(expense: Expense): Result<ExpenseStateOutcome>
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

/**
 * ADR-0038 PR-2g.3 round-8 P2 sealed result for
 * [PendingReviewActions.saveExpenseAllowingOffline]. The two
 * branches carry the same [expense] field so unconditional UI
 * updates (`_uiState.expense = outcome.expense`) work, while the
 * branch itself drives the user-facing message (`"已保存"` vs
 * `"已离线保存，联网后同步"`).
 */
sealed interface SaveOutcome {
    val expense: Expense

    /** Server confirmed the PATCH; [expense] carries the canonical post-mutation token. */
    data class Synced(override val expense: Expense) : SaveOutcome

    /**
     * Network failed; the mutation was persisted to the outbox and
     * [expense] is the optimistic projection (baseline merged with
     * the user's draft fields). The token on [expense] is the
     * pre-mutation ``updatedAt`` and MUST NOT be handed to a
     * follow-up POST — that's why this is a separate method from
     * [PendingReviewActions.updateExpense].
     */
    data class Queued(override val expense: Expense) : SaveOutcome
}

/**
 * ADR-0038 PR-2g.7 sealed result for the offline-aware state-machine
 * POSTs ([PendingReviewActions.confirmExpenseAllowingOffline] /
 * [PendingReviewActions.rejectExpenseAllowingOffline]; PR-2g.8 adds
 * mark-not-duplicate). Parallel to [SaveOutcome] — same two-branch
 * shape, separate type so the confirm/reject surface can't silently
 * widen into the PATCH-save one (see the [CategoryRuleSaveOutcome]
 * KDoc for the convention).
 */
sealed interface ExpenseStateOutcome {
    val expense: Expense

    /** Server confirmed the transition; [expense] is the canonical server snapshot. */
    data class Synced(override val expense: Expense) : ExpenseStateOutcome

    /**
     * Network failed; the transition was persisted to the outbox and
     * [expense] is the optimistic projection (baseline with
     * [Expense.status] flipped to ``confirmed`` / ``rejected``). The
     * token on [expense] is the pre-transition ``updatedAt``; the
     * outbox row owns the authoritative one. The UI moves the row out
     * of the pending list either way (it's gone from the user's
     * perspective); the worker reconciles on replay.
     */
    data class Queued(override val expense: Expense) : ExpenseStateOutcome
}
