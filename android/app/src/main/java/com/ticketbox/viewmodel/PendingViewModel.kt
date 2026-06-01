package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseStateOutcome
import com.ticketbox.data.repository.PendingThumbnailLoader
import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * slice 3 M7：BottomSheet 类型枚举，标记当前打开的 review 快速操作面板。
 */
sealed class PendingSheet {
    object None : PendingSheet()
    data class QuickCategory(val expense: Expense) : PendingSheet()
    data class QuickMerchant(val expense: Expense) : PendingSheet()
    data class MissingAmount(val expense: Expense) : PendingSheet()
    data class Duplicate(val expense: Expense) : PendingSheet()
    object BulkConfirm : PendingSheet()
}

/**
 * 批量确认运行时统计。
 */
data class BulkConfirmRunState(
    val total: Int = 0,
    val succeeded: Int = 0,
    val failed: Int = 0,
    val running: Boolean = false,
)

data class PendingUiState(
    val items: List<Expense> = emptyList(),
    val thumbnails: Map<Long, ProtectedImage> = emptyMap(),
    val actionInProgressIds: Set<Long> = emptySet(),
    val readOnly: Boolean = false,
    val loading: Boolean = false,
    val uploading: Boolean = false,
    val message: String? = null,
    val activeSheet: PendingSheet = PendingSheet.None,
    val categoryOptions: List<String> = emptyList(),
    val bulkConfirm: BulkConfirmRunState = BulkConfirmRunState(),
    /**
     * ADR-0038 undo: just-rejected Synced expense, surfaced for the 撤销
     * snackbar. Non-null = render the snackbar; tapping 撤销 calls
     * [PendingViewModel.undoReject], the VM's 5s display timer firing or
     * the user moving to another action calls
     * [PendingViewModel.dismissUndoable].
     *
     * **Two-clock split (intentional)**:
     *  - **VM 5s** ([PendingViewModel.startUndoTimer]) = UI display window
     *    only — when to hide the banner. Survives Compose lifecycle
     *    (tab/back-stack/scroll).
     *  - **Server 5-min retention** = actual undo authority. The button
     *    stays clickable the whole time the banner shows; the server
     *    decides per-request whether retention is still open. The VM
     *    NEVER pre-judges "within 5s == definitely undoable" — see
     *    [PendingViewModel.undoReject]'s onFailure 404-vs-transient
     *    branching.
     *
     * Only Synced reject outcomes seed this (the server actually holds the
     * rejected row to flip back); a Queued (offline) reject's mutation lives
     * in the outbox, so there's nothing for /undo to find — Queued therefore
     * leaves any pre-existing Synced banner intact rather than wiping it.
     * The banner carries the [Expense] so the UI can render merchant /
     * amount and disambiguate "撤的是 A 不是 B" in the Synced(A) followed
     * by Queued(B) case.
     */
    val undoableExpense: Expense? = null,
)

class PendingViewModel(
    internal val repository: PendingReviewActions,
    private val thumbnailLoader: PendingThumbnailLoader = PendingThumbnailLoader(repository),
) : ViewModel() {
    internal val _uiState = MutableStateFlow(PendingUiState())
    val uiState: StateFlow<PendingUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0
    private var uploadLedgerIdAtStart: String? = null
    private var uploadGenerationAtStart = 0
    // Bumped when undoReject commits its optimistic restore so any refresh
    // already in flight from before /undo (whose response will lack the
    // restored row) skips its afterRefresh wholesale-replace and doesn't
    // overwrite the row we just put back. requestGeneration is reserved for
    // ledger switches; we can't reuse it without cancelling unrelated flows.
    private var refreshSkipEpoch = 0
    // VM-owned 5s auto-dismiss timer for the 撤销 banner. Lives here rather
    // than in a Compose LaunchedEffect so it isn't restarted every time the
    // banner is recomposed (LazyColumn dispose / bottom-tab switch /
    // NavHost pop), which would let the banner outlive the server's 5-min
    // retention window.
    private var undoTimerJob: Job? = null

    init {
        val readOnly = !repository.canModifyLedger()
        _uiState.update { it.copy(readOnly = readOnly, message = if (readOnly) READ_ONLY_LEDGER_MESSAGE else it.message) }
        observeLedgerChanges()
        refresh()
        loadCategoryOptions()
    }

    private fun observeLedgerChanges() {
        viewModelScope.launch {
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .drop(1)
                .collect {
                    requestGeneration += 1
                    uploadLedgerIdAtStart = null
                    val readOnly = isReadOnly()
                    _uiState.value = PendingUiState(
                        readOnly = readOnly,
                        loading = true,
                        message = if (readOnly) READ_ONLY_LEDGER_MESSAGE else null,
                    )
                    refresh()
                    loadCategoryOptions()
                }
        }
    }

    private fun isReadOnly(): Boolean = !repository.canModifyLedger()

    internal fun blockReadOnlyWrite(closeSheet: Boolean = false): Boolean {
        if (!isReadOnly()) {
            _uiState.update { it.copy(readOnly = false) }
            return false
        }
        uploadLedgerIdAtStart = null
        // Demoted to viewer mid-banner: the snackbar is now a dead affordance
        // (the user can't 撤销 anything regardless of server retention), and
        // leaving it visible loops the read-only toast on every tap. Tear it
        // down explicitly here since this is the single gate every write path
        // routes through.
        cancelUndoTimer()
        _uiState.update {
            it.copy(
                readOnly = true,
                uploading = false,
                undoableExpense = null,
                activeSheet = if (closeSheet) PendingSheet.None else it.activeSheet,
                message = READ_ONLY_LEDGER_MESSAGE,
            )
        }
        return true
    }

    private fun loadCategoryOptions() {
        viewModelScope.launch {
            repository.categories()
                .onSuccess { options ->
                    _uiState.update { it.copy(categoryOptions = options) }
                }
                .onFailure { /* 静默失败：用户仍可手动输入分类 */ }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            val generation = requestGeneration
            val skipEpoch = refreshSkipEpoch
            _uiState.update { it.copy(loading = true, message = null) }
            repository.fetchPending()
                .onSuccess { expenses ->
                    if (requestGeneration != generation) return@onSuccess
                    // undoReject bumped refreshSkipEpoch between our fetch
                    // dispatch and its arrival — applying afterRefresh now
                    // would replace items wholesale with a list that's
                    // missing the row /undo just restored. Drop the stale
                    // response; user-initiated refresh re-trips this branch
                    // afresh.
                    if (refreshSkipEpoch != skipEpoch) return@onSuccess
                    _uiState.update { PendingUiStateReducer.afterRefresh(it, expenses, readOnly = isReadOnly()) }
                    loadThumbnails(expenses, generation)
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    if (refreshSkipEpoch != skipEpoch) return@onFailure
                    _uiState.update { it.copy(loading = false, message = error.message ?: "暂时加载不了，请稍后再试。") }
                }
        }
    }

    fun markUploadPreparing(): Boolean {
        if (blockReadOnlyWrite()) return false
        if (_uiState.value.uploading) return false
        uploadLedgerIdAtStart = repository.currentActiveLedgerId()
        uploadGenerationAtStart = requestGeneration
        _uiState.update { it.copy(uploading = true, message = null) }
        return true
    }

    fun uploadPreparationFailed(message: String = "这张图片暂时无法读取，请换一张试试。") {
        uploadLedgerIdAtStart = null
        _uiState.update { it.copy(uploading = false, message = message) }
    }

    fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long? = null,
        sourceSizeBytes: Long? = null,
        uploadAlreadyStarted: Boolean = false,
    ) {
        if (blockReadOnlyWrite()) return
        if (!uploadAlreadyStarted && _uiState.value.uploading) return
        viewModelScope.launch {
            if (!uploadAlreadyStarted) {
                uploadLedgerIdAtStart = repository.currentActiveLedgerId()
                uploadGenerationAtStart = requestGeneration
                _uiState.update { it.copy(uploading = true, message = null) }
            }
            val expectedLedgerId = uploadLedgerIdAtStart
            if (uploadGenerationAtStart != requestGeneration || expectedLedgerId != repository.currentActiveLedgerId()) {
                uploadLedgerIdAtStart = null
                _uiState.update {
                    it.copy(
                        uploading = false,
                        message = "账本已切换，请重新选择截图上传。",
                    )
                }
                return@launch
            }
            repository.uploadScreenshot(
                fileName = fileName,
                contentType = contentType,
                bytes = bytes,
                preparationDurationMs = preparationDurationMs,
                sourceSizeBytes = sourceSizeBytes,
                expectedLedgerId = expectedLedgerId,
            )
                .onSuccess {
                    if (uploadGenerationAtStart != requestGeneration) return@onSuccess
                    uploadLedgerIdAtStart = null
                    _uiState.update { state ->
                        state.copy(uploading = false, message = "截图已上传，等你确认。")
                    }
                    refresh()
                }
                .onFailure { error ->
                    if (uploadGenerationAtStart != requestGeneration) return@onFailure
                    uploadLedgerIdAtStart = null
                    _uiState.update {
                        it.copy(
                            uploading = false,
                            message = error.message ?: "没有上传成功，请稍后再试。",
                        )
                    }
                }
        }
    }

    private suspend fun loadThumbnails(expenses: List<Expense>, generation: Int) {
        val loaded = thumbnailLoader.loadMissing(expenses, _uiState.value.thumbnails)
        if (requestGeneration != generation) return
        if (loaded.isNotEmpty()) {
            _uiState.update { state -> PendingUiStateReducer.afterLoadedThumbnails(state, loaded) }
        }
    }

    /**
     * Shared scaffolding for every state-machine POST on the pending list
     * (confirm / reject / markNotDuplicate / ignoreDuplicate). Captures the
     * pattern that every variant ran open-coded:
     *
     *  1. (optional) dismiss the prior 撤销 banner — user moved on to
     *     another action. [dismissBanner] = false for [reject], which
     *     re-seeds the banner itself on Synced.
     *  2. read-only gate. [blockReadOnlyWrite] tears down the banner +
     *     toast as a side effect (V11 fix).
     *  3. optional per-call precondition (e.g. confirm needs an amount);
     *     return [String] to set as the user-facing message.
     *  4. in-progress guard against double-tap.
     *  5. mark in-progress.
     *  6. launch + generation snapshot for ledger-switch cancellation.
     *  7. call repo; on success let the caller compose the new
     *     [PendingUiState] via [onOutcome] (typically a reducer call);
     *     on Synced run [afterSyncedSuccess] for side effects like
     *     seeding [undoableExpense] + [startUndoTimer].
     *  8. on failure clear in-progress + show fallback message.
     *
     * Keeps the four call sites at ~7 lines each instead of ~40, and
     * makes future race / cancellation fixes a single-edit affair.
     */
    private fun launchStateTransition(
        expense: Expense,
        dismissBanner: Boolean = true,
        preCheck: () -> String? = { null },
        repoCall: suspend (Expense) -> Result<ExpenseStateOutcome>,
        syncedMessage: String,
        queuedMessage: String,
        failureFallback: String,
        onOutcome: (state: PendingUiState, outcome: ExpenseStateOutcome, message: String) -> PendingUiState,
        afterSyncedSuccess: ((Expense) -> Unit)? = null,
    ) {
        if (dismissBanner) dismissUndoable()
        if (blockReadOnlyWrite()) return
        preCheck()?.let { msg ->
            _uiState.update { it.copy(message = msg) }
            return
        }
        if (expense.id in _uiState.value.actionInProgressIds) return
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repoCall(expense)
                .onSuccess { outcome ->
                    if (requestGeneration != generation) return@onSuccess
                    val message = when (outcome) {
                        is ExpenseStateOutcome.Synced -> syncedMessage
                        is ExpenseStateOutcome.Queued -> queuedMessage
                    }
                    _uiState.update { state -> onOutcome(state, outcome, message) }
                    if (outcome is ExpenseStateOutcome.Synced) {
                        afterSyncedSuccess?.invoke(outcome.expense)
                    }
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    _uiState.update {
                        it.copy(
                            actionInProgressIds = it.actionInProgressIds - expense.id,
                            message = error.message ?: failureFallback,
                        )
                    }
                }
        }
    }

    fun confirm(expense: Expense) = launchStateTransition(
        expense = expense,
        preCheck = { if (expense.amountCents == null) "请先填写金额。" else null },
        repoCall = { repository.confirmExpenseAllowingOffline(it) },
        syncedMessage = "已确认入账",
        queuedMessage = "已离线确认，联网后同步",
        failureFallback = "没有确认成功，请稍后再试。",
        onOutcome = { state, outcome, message ->
            PendingUiStateReducer.afterConfirmed(state, outcome.expense, message = message)
        },
    )

    fun reject(expense: Expense) = launchStateTransition(
        expense = expense,
        // Reject doesn't pre-dismiss — Synced reject re-seeds the banner
        // with the new row inside onOutcome; Queued reject preserves any
        // prior Synced banner (V1 fix — the earlier Synced row is still
        // server-side undoable within its 5-min retention).
        dismissBanner = false,
        repoCall = { repository.rejectExpenseAllowingOffline(it) },
        syncedMessage = "已删除",
        queuedMessage = "已离线删除，联网后同步",
        failureFallback = "没有删除成功，请稍后再试。",
        onOutcome = { state, outcome, message ->
            val updated = PendingUiStateReducer.afterRejected(state, outcome.expense, message = message)
            when (outcome) {
                is ExpenseStateOutcome.Synced -> updated.copy(undoableExpense = outcome.expense)
                is ExpenseStateOutcome.Queued -> updated
            }
        },
        afterSyncedSuccess = { synced -> startUndoTimer(synced.id) },
    )

    /**
     * ADR-0038 undo: restore the most-recently-Synced-rejected expense back to
     * the pending list. Only call from the 5s 撤销 snackbar; on 404
     * (`expense_not_found`) the server's 5-min retention window already
     * closed (or another surface restored it first), so we flash a failure
     * message and stop showing the affordance. On transient errors
     * (IOException / 5xx) the server window may still be open — we restore
     * the banner so the user can retry.
     */
    fun undoReject() {
        val initial = _uiState.value
        val target = initial.undoableExpense ?: return
        if (blockReadOnlyWrite()) return
        if (target.id in initial.actionInProgressIds) return
        // Atomic CAS claim (V9 double-tap / Sweep#3 concurrent-reject race).
        // The synchronous prelude on the UI thread reads state.undoableExpense
        // once; a concurrent reject's onSuccess between this prelude and the
        // launch body below could replace undoableExpense with a different
        // row (B) — clearing it later would silently wipe B's banner while
        // we still hit /undo on A. Doing the claim inside `_uiState.update`
        // (which is atomic on MutableStateFlow) and gating on
        // `current.undoableExpense?.id == target.id` keeps the clear scoped
        // to the same row the caller intended to undo.
        var claimed = false
        _uiState.update { current ->
            if (current.undoableExpense?.id != target.id) return@update current
            if (target.id in current.actionInProgressIds) return@update current
            claimed = true
            current.copy(
                actionInProgressIds = current.actionInProgressIds + target.id,
                undoableExpense = null,
                message = null,
            )
        }
        if (!claimed) return
        cancelUndoTimer()
        val generation = requestGeneration
        // Bump epoch BEFORE the network call: any fetchPending already in
        // flight (and still on the dispatcher / network) will see the bump
        // when it returns and skip its wholesale afterRefresh replace,
        // which would otherwise overwrite the row we're about to restore.
        refreshSkipEpoch += 1
        viewModelScope.launch {
            // ADR-0038 PR-A: undo carries the rejected row's updated_at as
            // the OCC token. ``target`` is the Synced reject's expense (set
            // at seed time in reject()'s onSuccess), so its updated_at is
            // exactly what the banner showed. If the row's been re-rejected
            // since, the server-side atomic UPDATE WHERE fails → 404 → the
            // standard "无法撤销" flash.
            repository.undoRejectExpense(target.id, target.updatedAt)
                .onSuccess { restored ->
                    if (requestGeneration != generation) return@onSuccess
                    _uiState.update { state ->
                        // Restore at the TOP — backend lists pending by
                        // `created_at DESC`, so the just-rejected row was
                        // originally near the top, not the bottom. Tail-
                        // append would visually demote it across the
                        // restore. distinctBy keeps the canonical server
                        // copy if a refresh already re-added it.
                        val merged = (listOf(restored) + state.items).distinctBy { it.id }
                        state.copy(
                            items = merged,
                            actionInProgressIds = state.actionInProgressIds - target.id,
                            message = "已撤销，账单已恢复待确认。",
                        )
                    }
                    // V3 — afterRejected dropped the thumbnail; rehydrate
                    // so the restored row renders with its image immediately.
                    loadThumbnails(listOf(restored), generation)
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    val errorCode = (error as? RepositoryException)?.errorCode
                    when (errorCode) {
                        "expense_not_found" -> {
                            // 404: server window closed, row reaped, or
                            // another surface already restored it. Banner
                            // dead — leave undoableExpense null. Wording
                            // matches the surface's own semantics rather
                            // than the generic backend "账单不存在。".
                            _uiState.update {
                                it.copy(
                                    actionInProgressIds = it.actionInProgressIds - target.id,
                                    message = "无法撤销：账单已超过 5 分钟保留窗口，或已被清理。",
                                )
                            }
                        }
                        else -> {
                            // Transient (IOException / 5xx / unknown). The
                            // server window may still be open — restore the
                            // banner so the user can retry. Only restore if
                            // no NEWER reject seeded a different row in the
                            // meantime; never clobber a fresher Synced
                            // banner. Restart the timer only if we actually
                            // wrote the target back.
                            var restoredTarget = false
                            _uiState.update { state ->
                                if (state.undoableExpense == null) {
                                    restoredTarget = true
                                    state.copy(
                                        actionInProgressIds = state.actionInProgressIds - target.id,
                                        undoableExpense = target,
                                        message = error.message ?: "撤销失败，请稍后再试。",
                                    )
                                } else {
                                    state.copy(
                                        actionInProgressIds = state.actionInProgressIds - target.id,
                                        message = error.message ?: "撤销失败，请稍后再试。",
                                    )
                                }
                            }
                            if (restoredTarget) startUndoTimer(target.id)
                        }
                    }
                }
        }
    }

    /**
     * ADR-0038 undo: dismiss the 撤销 snackbar without acting on it. Called
     * by the VM's own 5s auto-dismiss timer or by user-initiated signals
     * (confirm / markNotDuplicate / openSheet / ignoreDuplicate).
     */
    fun dismissUndoable() {
        if (_uiState.value.undoableExpense == null) return
        cancelUndoTimer()
        _uiState.update { it.copy(undoableExpense = null) }
    }

    /**
     * Start (or restart) the 撤销 banner's display timer.
     *
     * This is the **VM 5s display window** half of the two-clock split (see
     * [PendingUiState.undoableExpense] KDoc) — it decides **when to hide
     * the banner**, not whether the row is actually undoable. The button
     * is clickable for the whole window; the server's 5-min retention
     * decides per request. Owning the timer here (not in Compose
     * LaunchedEffect) means tab switches / NavHost pops / LazyColumn
     * dispose-on-scroll don't restart it and can't let the banner outlive
     * its window into the server retention edge.
     */
    internal fun startUndoTimer(id: Long) {
        cancelUndoTimer()
        undoTimerJob = viewModelScope.launch {
            delay(5_000)
            // Only auto-dismiss if the banner still points at the SAME row
            // — a newer reject may have re-seeded (and re-started the
            // timer for) a different row between schedule and fire.
            if (_uiState.value.undoableExpense?.id == id) {
                _uiState.update { it.copy(undoableExpense = null) }
            }
            undoTimerJob = null
        }
    }

    private fun cancelUndoTimer() {
        undoTimerJob?.cancel()
        undoTimerJob = null
    }

    /**
     * ADR-0038 onIgnoreDuplicate split (V14): same backend transition as
     * [reject] (the row leaves pending), but UX-wise the user "忽略重复" — no
     * 撤销 affordance, message wording matches intent. Routing the
     * duplicate-sheet "忽略" button through [reject] inherited its banner
     * + "已删除" message, confusing users on the duplicate sheet.
     */
    fun ignoreDuplicate(expense: Expense) = launchStateTransition(
        expense = expense,
        repoCall = { repository.rejectExpenseAllowingOffline(it) },
        syncedMessage = "已忽略重复",
        queuedMessage = "已离线忽略，联网后同步",
        failureFallback = "没有处理成功，请稍后再试。",
        onOutcome = { state, outcome, message ->
            PendingUiStateReducer.afterRejected(state, outcome.expense, message = message)
        },
    )

    fun markNotDuplicate(expense: Expense) = launchStateTransition(
        expense = expense,
        repoCall = { repository.markNotDuplicateAllowingOffline(it) },
        syncedMessage = "已保留这条账单",
        queuedMessage = "已离线保留，联网后同步",
        failureFallback = "暂时没处理成功，请稍后再试。",
        onOutcome = { state, outcome, message ->
            PendingUiStateReducer.afterUpdated(
                current = state,
                updated = outcome.expense,
                closeSheet = true,
                message = message,
            )
        },
    )
}

internal fun reconcileActiveSheet(sheet: PendingSheet, items: List<Expense>): PendingSheet {
    if (sheet is PendingSheet.None || sheet is PendingSheet.BulkConfirm) return sheet
    val latestById = items.associateBy { it.id }
    return when (sheet) {
        is PendingSheet.QuickCategory -> latestById[sheet.expense.id]?.let(PendingSheet::QuickCategory) ?: PendingSheet.None
        is PendingSheet.QuickMerchant -> latestById[sheet.expense.id]?.let(PendingSheet::QuickMerchant) ?: PendingSheet.None
        is PendingSheet.MissingAmount -> latestById[sheet.expense.id]?.let(PendingSheet::MissingAmount) ?: PendingSheet.None
        is PendingSheet.Duplicate -> latestById[sheet.expense.id]?.let(PendingSheet::Duplicate) ?: PendingSheet.None
        is PendingSheet.None,
        is PendingSheet.BulkConfirm,
        -> sheet
    }
}
