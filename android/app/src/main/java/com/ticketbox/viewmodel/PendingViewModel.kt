package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseStateOutcome
import com.ticketbox.data.repository.PendingThumbnailLoader
import com.ticketbox.data.repository.PendingEnrichmentTaskReader
import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.ScreenshotUploadRequest
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.PendingUploadReceipt
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val ENRICHMENT_CAPACITY_FULL_CODE = "enrichment_capacity_full"

private data class CapacityRetryIntent(
    val image: PreparedUploadImage,
    val ledgerId: String?,
    val generation: Int,
    val priorSharedFailureCount: Int,
)

internal data class PendingUploadAttempt(
    val id: Long,
    val ledgerId: String?,
    val generation: Int,
)

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

enum class PendingListLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

data class PendingUiState(
    val items: List<Expense> = emptyList(),
    val thumbnails: Map<Long, ProtectedImage> = emptyMap(),
    val actionInProgressIds: Set<Long> = emptySet(),
    val readOnly: Boolean = false,
    val showingCachedSnapshot: Boolean = false,
    val listLoadState: PendingListLoadState = PendingListLoadState.Unknown,
    val hasLoadedOnce: Boolean = false,
    val loading: Boolean = false,
    val uploading: Boolean = false,
    val enrichment: PendingEnrichmentUiState = PendingEnrichmentUiState(),
    val message: UiText? = null,
    /** Whether an in-memory image rejected before commit can be retried. */
    val canRetryUpload: Boolean = false,
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
    /**
     * 连续审阅「还剩 N 条」计数：当前打开的快补 sheet 对应字段、本轮未跳过、仍
     * 待补的票数（含当前票）。仅在快补 sheet（金额/商家/分类）打开时有意义，
     * sheet 关闭后归 0。口径见 [PendingReviewQueue.remaining]；VM 在每次设置快补
     * sheet / 推进 / 跳过 / 刷新后重算，Screen 只读不算。
     */
    val reviewRemaining: Int = 0,
) {
    val showPageRefresh: Boolean
        get() = loading && items.isEmpty() && !showingCachedSnapshot

    internal val preserveUploadMessageDuringRefresh: Boolean
        get() = canRetryUpload ||
            (message as? UiText.Res)?.id == R.string.pending_msg_share_partial_failure
}

private data class PendingStateTransitionOperation(
    val repoCall: suspend (Expense) -> Result<ExpenseStateOutcome>,
    val dismissBanner: Boolean = true,
    val preCheck: () -> UiText? = { null },
    /** True only for transitions that LAND in confirmed expenses (the budget
     *  advisor's expense input) — pending-side lifecycle (reject, duplicate
     *  handling) leaves it false so no advice invalidation fires. */
    val landsInConfirmed: Boolean = false,
)

private data class PendingStateTransitionMessages(
    val synced: UiText,
    val queued: UiText,
    @param:StringRes val failureFallback: Int,
)

private data class PendingStateTransitionResultHandler(
    val reduceOutcome: (
        state: PendingUiState,
        outcome: ExpenseStateOutcome,
        message: UiText,
    ) -> PendingUiState,
    val afterSyncedSuccess: ((Expense) -> Unit)? = null,
)

class PendingViewModel(
    internal val repository: PendingReviewActions,
    private val thumbnailLoader: PendingThumbnailLoader = PendingThumbnailLoader(repository),
    private val enrichmentTaskReader: PendingEnrichmentTaskReader? = null,
    internal val onDataChanged: () -> Unit = {},
) : ViewModel() {
    /** Fired ONLY when a pending action lands in confirmed expenses (the
     *  budget advisor's input set): confirm paths. Upload / reject /
     *  pending-side edits never fire it. var per the repository seam idiom —
     *  wired in PendingRoute (the factory is at the parameter cap). */
    internal var onAdviceInputsChanged: () -> Unit = {}
    internal val _uiState = MutableStateFlow(PendingUiState())
    val uiState: StateFlow<PendingUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0
    private var uploadAttemptSequence = 0L
    private var activeUploadAttempt: PendingUploadAttempt? = null
    // Only the latest issued refresh may publish into visible UI state.
    private var refreshSequence = 0
    // Memory-only; never persisted or routed through the offline outbox.
    private var capacityRetryIntent: CapacityRetryIntent? = null
    // Bumped when undoReject commits its optimistic restore so any refresh
    // already in flight from before /undo (whose response will lack the
    // restored row) skips its afterRefresh wholesale-replace and doesn't
    // overwrite the row we just put back. requestGeneration is reserved for
    // ledger switches; we can't reuse it without cancelling unrelated flows.
    private var refreshSkipEpoch = 0
    // issue #64 A3: pending 本地优先读的「首屏种子」一次性闸。仅首屏 / 换账本后的
    // 第一次 refresh 从 Room 缓存铺列表（消空白间隙）；之后的下拉刷新不再回种，避免
    // 在用户已乐观移除（confirm/reject 只改内存不写 Room）后又从陈旧缓存把行复活
    // ——撞 issue 红线「review action 执行器行为不变」。换账本时在
    // observeLedgerChanges 重置为 false 以便对新账本重新种一次。
    private var pendingCacheSeeded = false
    // VM-owned 5s auto-dismiss timer for the 撤销 banner. Lives here rather
    // than in a Compose LaunchedEffect so it isn't restarted every time the
    // banner is recomposed (LazyColumn dispose / bottom-tab switch /
    // NavHost pop), which would let the banner outlive the server's 5-min
    // retention window.
    private var undoTimerJob: Job? = null
    private var enrichmentObserver: PendingEnrichmentObserver? = null

    // 连续审阅（批量过堆积待确认票）本轮已「跳过」的票 id。快补 sheet 的
    // 保存并下一笔 / 跳过都朝列表后方推进，跳过的票留在 pending 列表里、不出队、
    // 不改后端状态，但本轮不再回头载入它——靠这个集合排除（口径见
    // [PendingReviewQueue]）。开新一轮（从列表点开快补）/ 关闭 sheet / 换账本
    // 即清空，所以它是「一次连续审阅」的局部状态，不跨 pass 残留。
    internal val reviewSkippedIds = mutableSetOf<Long>()

    init {
        val readOnly = !repository.canModifyLedger()
        _uiState.update { it.copy(readOnly = readOnly, message = if (readOnly) readOnlyMessage() else it.message) }
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
                    activeUploadAttempt = null
                    capacityRetryIntent = null
                    enrichmentObserver?.clear()
                    reviewSkippedIds.clear()
                    // A3: 新账本要重新种一次首屏缓存。
                    pendingCacheSeeded = false
                    val readOnly = isReadOnly()
                    _uiState.value = PendingUiState(
                        readOnly = readOnly,
                        loading = true,
                        listLoadState = PendingListLoadState.Loading,
                        message = if (readOnly) readOnlyMessage() else null,
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
        activeUploadAttempt = null
        capacityRetryIntent = null
        enrichmentObserver?.clear()
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
                canRetryUpload = false,
                undoableExpense = null,
                activeSheet = if (closeSheet) PendingSheet.None else it.activeSheet,
                message = readOnlyMessage(),
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
        // Issued synchronously (not inside the launch) so call order always
        // matches sequence order even if the coroutine body runs later.
        val sequence = ++refreshSequence
        viewModelScope.launch {
            val generation = requestGeneration
            val skipEpoch = refreshSkipEpoch
            _uiState.update {
                it.copy(
                    loading = true,
                    listLoadState = PendingListLoadState.Loading,
                    message = if (it.preserveUploadMessageDuringRefresh) it.message else null,
                )
            }
            // A3: 先用本地缓存铺首屏（仅首次 / 换账本后那次），再走网络 write-through。
            // 顺序在同一协程里：种子完成后才发网络 → 飞行模式下网络失败时缓存仍留在
            // 列表里（onFailure 不动 items），无竞态。
            seedFromCacheIfFirstLoad(generation)
            repository.syncPending()
                .onSuccess { expenses ->
                    if (sequence != refreshSequence) return@onSuccess
                    if (requestGeneration != generation) return@onSuccess
                    // undoReject bumped refreshSkipEpoch between our fetch
                    // dispatch and its arrival — applying afterRefresh now
                    // would replace items wholesale with a list that's
                    // missing the row /undo just restored. Drop the stale
                    // response; user-initiated refresh re-trips this branch
                    // afresh.
                    if (refreshSkipEpoch != skipEpoch) return@onSuccess
                    _uiState.update { PendingUiStateReducer.afterRefresh(it, expenses, readOnly = isReadOnly()) }
                    // 后台刷新可能改变 items / 经 reconcile 关闭已离开的快补 sheet，
                    // 「还剩 N 条」随之重算（sheet 没开则归 0）。
                    recomputeReviewRemaining()
                    loadThumbnails(expenses, generation)
                }
                .onFailure { error ->
                    if (sequence != refreshSequence) return@onFailure
                    if (requestGeneration != generation) return@onFailure
                    if (refreshSkipEpoch != skipEpoch) return@onFailure
                    _uiState.update {
                        it.copy(
                            hasLoadedOnce = true,
                            loading = false,
                            listLoadState = PendingListLoadState.Failed,
                            message = if (it.preserveUploadMessageDuringRefresh) {
                                it.message
                            } else {
                                error.toUiText(R.string.pending_msg_load_failed)
                            },
                        )
                    }
                }
        }
    }

    /**
     * A3 首屏种子：仅当本轮是首屏 / 换账本后的第一次刷新、且列表还空时，从 Room
     * 缓存铺一次 pending（[pendingCacheSeeded] 一次性闸）。闸先同步置位再 await，
     * 并发刷新不会重复种；[requestGeneration] 守换账本；铺前再查一次 items 仍空，
     * 不覆盖刚落地的 fetch / 乐观状态。空缓存也算「已种」——避免下拉刷新回种复活。
     */
    private suspend fun seedFromCacheIfFirstLoad(generation: Int) {
        if (pendingCacheSeeded || _uiState.value.items.isNotEmpty()) return
        pendingCacheSeeded = true
        repository.getCachedPending().onSuccess { cached ->
            if (requestGeneration != generation) return@onSuccess
            if (_uiState.value.items.isEmpty() && cached.isNotEmpty()) {
                _uiState.update {
                    it.copy(
                        items = cached,
                        showingCachedSnapshot = true,
                        hasLoadedOnce = true,
                    )
                }
            }
        }
    }

    internal fun beginUploadPreparation(): PendingUploadAttempt? {
        if (blockReadOnlyWrite()) return null
        if (_uiState.value.uploading) return null
        // A new image intent supersedes any retained retry.
        clearCapacityRetry()
        val attempt = newUploadAttempt(
            ledgerId = repository.currentActiveLedgerId(),
            generation = requestGeneration,
        )
        _uiState.update { it.copy(uploading = true, message = null) }
        return attempt
    }

    internal fun uploadPreparationFailed(
        attempt: PendingUploadAttempt,
        message: UiText = UiText.res(R.string.pending_msg_upload_unreadable),
    ) {
        if (activeUploadAttempt != attempt) return
        activeUploadAttempt = null
        _uiState.update { it.copy(uploading = false, message = message) }
    }

    internal fun uploadCancelled(attempt: PendingUploadAttempt) {
        if (activeUploadAttempt != attempt) return
        activeUploadAttempt = null
        _uiState.update { state ->
            if (state.uploading) state.copy(uploading = false) else state
        }
    }

    internal fun isUploadAttemptBoundToCurrentLedger(attempt: PendingUploadAttempt): Boolean =
        attempt.generation == requestGeneration && attempt.ledgerId == repository.currentActiveLedgerId()

    internal fun reportSharedUploadFailures(failedCount: Int) {
        if (failedCount <= 0 || _uiState.value.canRetryUpload) return
        _uiState.update {
            it.copy(message = UiText.res(R.string.pending_msg_share_partial_failure, failedCount))
        }
    }

    internal fun uploadScreenshot(image: PreparedUploadImage, attempt: PendingUploadAttempt) {
        if (blockReadOnlyWrite()) return
        viewModelScope.launch {
            performUpload(image = image, attempt = attempt)
        }
    }

    /**
     * 等待完成的单张上传，供「系统分享多图」按顺序逐张上传（W1）。调用方负责先
     * [beginUploadPreparation]（拿 in-progress 锁 + 快照 ledger/generation），再于此 await
     * 一张完成后再处理下一张——因为上传链是**在线-only**（直连 POST，非 outbox 队列），
     * 顺序串行是最朴素的「多图循环」。
     *
     * @return 该张是否上传成功（用于决定是否继续后续张 / 汇总提示）。
     */
    internal suspend fun uploadPreparedImage(
        image: PreparedUploadImage,
        attempt: PendingUploadAttempt,
        priorSharedFailureCount: Int = 0,
    ): Boolean = performUpload(
        image = image,
        attempt = attempt,
        priorSharedFailureCount = priorSharedFailureCount,
    )

    /** Retry a capacity-rejected image without asking the user to pick it again. */
    fun retryCapacityUpload() {
        val intent = capacityRetryIntent ?: return
        if (blockReadOnlyWrite()) return
        if (_uiState.value.uploading) return
        capacityRetryIntent = null
        if (intent.generation != requestGeneration || intent.ledgerId != repository.currentActiveLedgerId()) {
            _uiState.update {
                it.copy(
                    uploading = false,
                    canRetryUpload = false,
                    message = UiText.res(R.string.pending_msg_upload_ledger_switched),
                )
            }
            return
        }
        val attempt = newUploadAttempt(
            ledgerId = intent.ledgerId,
            generation = intent.generation,
        )
        _uiState.update { it.copy(uploading = true, canRetryUpload = false, message = null) }
        viewModelScope.launch {
            val succeeded = performUpload(
                image = intent.image,
                attempt = attempt,
                priorSharedFailureCount = intent.priorSharedFailureCount,
            )
            if (succeeded) reportSharedUploadFailures(intent.priorSharedFailureCount)
        }
    }

    private fun newUploadAttempt(ledgerId: String?, generation: Int): PendingUploadAttempt {
        val attempt = PendingUploadAttempt(
            id = ++uploadAttemptSequence,
            ledgerId = ledgerId,
            generation = generation,
        )
        activeUploadAttempt = attempt
        return attempt
    }

    private fun clearCapacityRetry() {
        capacityRetryIntent = null
        if (_uiState.value.canRetryUpload) {
            _uiState.update { it.copy(canRetryUpload = false) }
        }
    }

    private suspend fun performUpload(
        image: PreparedUploadImage,
        attempt: PendingUploadAttempt,
        priorSharedFailureCount: Int = 0,
    ): Boolean {
        if (activeUploadAttempt != attempt) {
            // A ledger switch may retire this token before image preparation
            // completes. Report that case only while no newer attempt owns the
            // slot; a stale callback must never overwrite newer upload UI.
            if (
                activeUploadAttempt == null &&
                (attempt.generation != requestGeneration || attempt.ledgerId != repository.currentActiveLedgerId())
            ) {
                _uiState.update {
                    it.copy(
                        uploading = false,
                        canRetryUpload = false,
                        message = UiText.res(R.string.pending_msg_upload_ledger_switched),
                    )
                }
            }
            return false
        }
        if (attempt.generation != requestGeneration || attempt.ledgerId != repository.currentActiveLedgerId()) {
            activeUploadAttempt = null
            _uiState.update {
                it.copy(
                    uploading = false,
                    message = UiText.res(R.string.pending_msg_upload_ledger_switched),
                )
            }
            return false
        }
        var succeeded = false
        repository.uploadScreenshot(
            ScreenshotUploadRequest(
                fileName = image.fileName,
                contentType = image.contentType,
                bytes = image.bytes,
                preparationDurationMs = image.preparationDurationMs,
                sourceSizeBytes = image.sourceSizeBytes,
                expectedLedgerId = attempt.ledgerId,
            ),
        )
            .onSuccess { receipt -> succeeded = onUploadSuccess(attempt, receipt) }
            .onFailure { error ->
                onUploadFailure(
                    attempt = attempt,
                    error = error,
                    image = image,
                    priorSharedFailureCount = priorSharedFailureCount,
                )
            }
        return succeeded
    }

    private fun onUploadSuccess(attempt: PendingUploadAttempt, receipt: PendingUploadReceipt): Boolean {
        if (activeUploadAttempt != attempt) return false
        if (attempt.generation != requestGeneration || attempt.ledgerId != repository.currentActiveLedgerId()) {
            activeUploadAttempt = null
            _uiState.update {
                it.copy(
                    uploading = false,
                    canRetryUpload = false,
                    message = UiText.res(R.string.pending_msg_upload_ledger_switched),
                )
            }
            return false
        }
        activeUploadAttempt = null
        _uiState.update { state ->
            state.copy(uploading = false, message = null)
        }
        onDataChanged()
        refresh()
        enrichmentObserver()?.track(receipt)
        return true
    }

    private fun onUploadFailure(
        attempt: PendingUploadAttempt,
        error: Throwable,
        image: PreparedUploadImage,
        priorSharedFailureCount: Int,
    ) {
        if (activeUploadAttempt != attempt) return
        if (attempt.generation != requestGeneration || attempt.ledgerId != repository.currentActiveLedgerId()) {
            activeUploadAttempt = null
            _uiState.update {
                it.copy(
                    uploading = false,
                    canRetryUpload = false,
                    message = UiText.res(R.string.pending_msg_upload_ledger_switched),
                )
            }
            return
        }
        activeUploadAttempt = null
        if ((error as? RepositoryException)?.errorCode == ENRICHMENT_CAPACITY_FULL_CODE) {
            // Match the machine code, not a generic 503. The server guarantees
            // this rejection occurs before commit, so retaining bytes is safe.
            capacityRetryIntent = CapacityRetryIntent(
                image = image,
                ledgerId = attempt.ledgerId,
                generation = attempt.generation,
                priorSharedFailureCount = priorSharedFailureCount,
            )
            _uiState.update {
                it.copy(
                    uploading = false,
                    canRetryUpload = true,
                    message = UiText.res(R.string.pending_msg_upload_capacity_full),
                )
            }
        } else {
            _uiState.update {
                it.copy(
                    uploading = false,
                    message = error.toUiText(R.string.pending_msg_upload_failed),
                )
            }
        }
    }

    fun retryEnrichmentObservation() {
        enrichmentObserver?.retryPaused()
    }

    private fun enrichmentObserver(): PendingEnrichmentObserver? {
        val taskReader = enrichmentTaskReader ?: return null
        return enrichmentObserver ?: PendingEnrichmentObserver(
            scope = viewModelScope,
            fetchTask = taskReader::fetchPendingEnrichmentTask,
            canObserve = { !isReadOnly() },
            onStateChanged = { enrichment ->
                _uiState.update { it.copy(enrichment = enrichment) }
            },
            onTerminal = ::refresh,
        ).also { enrichmentObserver = it }
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
     *     another action.
     *     [PendingStateTransitionOperation.dismissBanner] = false for
     *     [reject], which re-seeds the banner itself on Synced.
     *  2. read-only gate. [blockReadOnlyWrite] tears down the banner +
     *     toast as a side effect (V11 fix).
     *  3. optional per-call precondition (e.g. confirm needs an amount);
     *     return [String] to set as the user-facing message.
     *  4. in-progress guard against double-tap.
     *  5. mark in-progress.
     *  6. launch + generation snapshot for ledger-switch cancellation.
     *  7. call repo; on success let the caller compose the new
     *     [PendingUiState] via
     *     [PendingStateTransitionResultHandler.reduceOutcome]
     *     (typically a reducer call); on Synced run
     *     [PendingStateTransitionResultHandler.afterSyncedSuccess]
     *     for side effects like
     *     seeding [undoableExpense] + [startUndoTimer].
     *  8. on failure clear in-progress + show fallback message.
     *
     * Keeps the four call sites at ~7 lines each instead of ~40, and
     * makes future race / cancellation fixes a single-edit affair.
     */
    private fun launchStateTransition(
        expense: Expense,
        operation: PendingStateTransitionOperation,
        messages: PendingStateTransitionMessages,
        resultHandler: PendingStateTransitionResultHandler,
    ) {
        if (operation.dismissBanner) dismissUndoable()
        if (blockReadOnlyWrite()) return
        operation.preCheck()?.let { msg ->
            _uiState.update { it.copy(message = msg) }
            return
        }
        if (expense.id in _uiState.value.actionInProgressIds) return
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            operation.repoCall(expense)
                .onSuccess { outcome ->
                    if (requestGeneration != generation) return@onSuccess
                    val message = when (outcome) {
                        is ExpenseStateOutcome.Synced -> messages.synced
                        is ExpenseStateOutcome.Queued -> messages.queued
                    }
                    _uiState.update { state -> resultHandler.reduceOutcome(state, outcome, message) }
                    onDataChanged()
                    if (operation.landsInConfirmed) {
                        onAdviceInputsChanged()
                    }
                    if (outcome is ExpenseStateOutcome.Synced) {
                        resultHandler.afterSyncedSuccess?.invoke(outcome.expense)
                    }
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    _uiState.update {
                        it.copy(
                            actionInProgressIds = it.actionInProgressIds - expense.id,
                            message = error.toUiText(messages.failureFallback),
                        )
                    }
                }
        }
    }

    fun confirm(expense: Expense) = launchStateTransition(
        expense = expense,
        operation = PendingStateTransitionOperation(
            repoCall = { repository.confirmExpenseAllowingOffline(it) },
            preCheck = { if (expense.amountCents == null) UiText.res(R.string.error_amount_required) else null },
            landsInConfirmed = true,
        ),
        messages = PendingStateTransitionMessages(
            synced = UiText.res(R.string.pending_msg_confirmed),
            queued = UiText.res(R.string.pending_msg_confirmed_offline),
            failureFallback = R.string.pending_msg_confirm_failed,
        ),
        resultHandler = PendingStateTransitionResultHandler(
            reduceOutcome = { state, outcome, message ->
                PendingUiStateReducer.afterConfirmed(state, outcome.expense, message = message)
            },
        ),
    )

    fun reject(expense: Expense) = launchStateTransition(
        expense = expense,
        operation = PendingStateTransitionOperation(
            // Reject does not pre-dismiss: Synced reject re-seeds the banner
            // with the new row inside reduceOutcome; Queued reject preserves any
            // prior Synced banner because it may still be server-side undoable.
            dismissBanner = false,
            repoCall = { repository.rejectExpenseAllowingOffline(it) },
        ),
        messages = PendingStateTransitionMessages(
            synced = UiText.res(R.string.pending_msg_rejected),
            queued = UiText.res(R.string.pending_msg_rejected_offline),
            failureFallback = R.string.pending_msg_reject_failed,
        ),
        resultHandler = PendingStateTransitionResultHandler(
            reduceOutcome = { state, outcome, message ->
                val updated = PendingUiStateReducer.afterRejected(state, outcome.expense, message = message)
                when (outcome) {
                    is ExpenseStateOutcome.Synced -> updated.copy(undoableExpense = outcome.expense)
                    is ExpenseStateOutcome.Queued -> updated
                }
            },
            afterSyncedSuccess = { synced -> startUndoTimer(synced.id) },
        ),
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
            // ADR-0041: undo carries the rejected row's row_version as
            // the OCC token. ``target`` is the Synced reject's expense (set
            // at seed time in reject()'s onSuccess), so its row_version is
            // exactly what the banner showed. If the row's been re-rejected
            // since, the server-side atomic UPDATE WHERE fails → 404 → the
            // standard "无法撤销" flash.
            repository.undoRejectExpense(target.id, target.rowVersion)
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
                            message = UiText.res(R.string.pending_msg_undo_restored),
                        )
                    }
                    onDataChanged()
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
                                    message = UiText.res(R.string.pending_msg_undo_window_closed),
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
                                        message = error.toUiText(R.string.pending_msg_undo_failed),
                                    )
                                } else {
                                    state.copy(
                                        actionInProgressIds = state.actionInProgressIds - target.id,
                                        message = error.toUiText(R.string.pending_msg_undo_failed),
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
        operation = PendingStateTransitionOperation(
            repoCall = { repository.rejectExpenseAllowingOffline(it) },
        ),
        messages = PendingStateTransitionMessages(
            synced = UiText.res(R.string.pending_msg_ignored_duplicate),
            queued = UiText.res(R.string.pending_msg_ignored_duplicate_offline),
            failureFallback = R.string.pending_msg_ignore_duplicate_failed,
        ),
        resultHandler = PendingStateTransitionResultHandler(
            reduceOutcome = { state, outcome, message ->
                PendingUiStateReducer.afterRejected(state, outcome.expense, message = message)
            },
        ),
    )

    fun markNotDuplicate(expense: Expense) = launchStateTransition(
        expense = expense,
        operation = PendingStateTransitionOperation(
            repoCall = { repository.markNotDuplicateAllowingOffline(it) },
        ),
        messages = PendingStateTransitionMessages(
            synced = UiText.res(R.string.pending_msg_kept),
            queued = UiText.res(R.string.pending_msg_kept_offline),
            failureFallback = R.string.pending_msg_keep_failed,
        ),
        resultHandler = PendingStateTransitionResultHandler(
            reduceOutcome = { state, outcome, message ->
                PendingUiStateReducer.afterUpdated(
                    current = state,
                    updated = outcome.expense,
                    closeSheet = true,
                    message = message,
                )
            },
        ),
    )
}

// ADR-0044 wave 2: read-only ledger copy, resource-backed like every other
// message — every VM resolves this copy from common_readonly_ledger (the old
// hardcoded String const was removed in the wave-2 cleanup).
internal fun readOnlyMessage(): UiText = UiText.res(R.string.common_readonly_ledger)

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
