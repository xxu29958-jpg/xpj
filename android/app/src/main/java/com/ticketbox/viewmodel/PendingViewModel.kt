package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.data.repository.ExpenseCommandObservation
import com.ticketbox.data.repository.PendingThumbnailLoader
import com.ticketbox.data.repository.PendingEnrichmentTaskReader
import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.UploadBatchRequest
import com.ticketbox.data.repository.UploadIntentActions
import com.ticketbox.data.repository.UploadIntentObservation
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.toPendingUploadReceipt
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.firstOrNull
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
    val upload: PendingUploadUiState = PendingUploadUiState(),
    val uploadBinding: LogicalSessionBinding? = null,
    val uploadActionInProgress: Boolean = false,
    val enrichment: PendingEnrichmentUiState = PendingEnrichmentUiState(),
    val message: UiText? = null,
    val activeSheet: PendingSheet = PendingSheet.None,
    val categoryOptions: List<String> = emptyList(),
    val bulkConfirm: BulkConfirmRunState = BulkConfirmRunState(),
    /** Original accepted rejection receipt; the server decides whether Undo remains valid. */
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

    val uploading: Boolean get() = uploadActionInProgress || upload.inFlight
    val canStartUpload: Boolean get() = !readOnly && !uploading
    val canRetryUpload: Boolean get() = !readOnly && !uploadActionInProgress && upload.retryable
    val canStopUpload: Boolean get() = !uploadActionInProgress && upload.groupId != null
    val uploadMessage: UiText? get() = upload.message
    val uploadFailedCount: Int get() = upload.failedCount

}

class PendingViewModel(
    internal val repository: PendingReviewActions,
    private val uploadIntents: UploadIntentActions,
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
    internal var requestGeneration = 0
    // Only the latest issued refresh may publish into visible UI state.
    private var refreshSequence = 0
    // Bumped when undoReject commits its optimistic restore so any refresh
    // already in flight from before /undo (whose response will lack the
    // restored row) skips its afterRefresh wholesale-replace and doesn't
    // overwrite the row we just put back. requestGeneration is reserved for
    // ledger switches; we can't reuse it without cancelling unrelated flows.
    internal var refreshSkipEpoch = 0
    // issue #64 A3: pending 本地优先读的「首屏种子」一次性闸。仅首屏 / 换账本后的
    // 第一次 refresh 从 Room 缓存铺列表（消空白间隙）；之后的下拉刷新不再回种，避免
    // 在用户已乐观移除（confirm/reject 只改内存不写 Room）后又从陈旧缓存把行复活
    // ——撞 issue 红线「review action 执行器行为不变」。换账本时在
    // 原绑定初始化重置为 false 以便对新账本重新种一次。
    private var pendingCacheSeeded = false
    // VM-owned 5s auto-dismiss timer for the 撤销 banner. Lives here rather
    // than in a Compose LaunchedEffect so it isn't restarted every time the
    // banner is recomposed (LazyColumn dispose / bottom-tab switch /
    // NavHost pop), which would let the banner outlive the server's 5-min
    // retention window.
    private var undoTimerJob: Job? = null
    private var enrichmentObserver: PendingEnrichmentObserver? = null
    private var uploadObservation: UploadIntentObservation? = null
    private val observedUploadReceipts = mutableSetOf<Long>()
    internal var commandObservation: ExpenseCommandObservation? = null
    internal val commandRowsByExpense = mutableMapOf<Long, Set<Long>>()
    internal val seenCommandCompletions = mutableSetOf<Long>()
    internal val ignoredRejectRows = mutableSetOf<Long>()
    internal val bulkCommandRows = mutableSetOf<Long>()

    // 连续审阅（批量过堆积待确认票）本轮已「跳过」的票 id。快补 sheet 的
    // 保存并下一笔 / 跳过都朝列表后方推进，跳过的票留在 pending 列表里、不出队、
    // 不改后端状态，但本轮不再回头载入它——靠这个集合排除（口径见
    // [PendingReviewQueue]）。开新一轮（从列表点开快补）/ 关闭 sheet / 换账本
    // 即清空，所以它是「一次连续审阅」的局部状态，不跨 pass 残留。
    internal val reviewSkippedIds = mutableSetOf<Long>()

    init {
        _uiState.update { it.copy(readOnly = true) }
        viewModelScope.launch {
            combine(uploadIntents.observeUploadIntents(), repository.observeExpenseCommands()) { uploads, commands ->
                uploads to commands
            }.collect { (uploads, commands) ->
                if (uploads.access?.binding != commands.access?.binding) return@collect
                val initialize = commandObservation == null
                val changed = commandObservation?.access?.binding != commands.access?.binding
                commandObservation = commands
                if (changed) {
                    commandRowsByExpense.clear()
                    seenCommandCompletions.clear()
                    ignoredRejectRows.clear()
                    bulkCommandRows.clear()
                }
                if (initialize || changed) seenCommandCompletions.addAll(
                    commands.commands.filter { it.row.status == PendingMutationStatus.Done }.map { it.row.id })
                installUploadObservation(uploads)
                reconcileExpenseCommands()
            }
        }
    }

    private fun installUploadObservation(observation: UploadIntentObservation) {
        if (observation.access != null && observation.access.binding != uploadIntents.currentUploadBinding()) return
        val initialize = uploadObservation == null || uploadObservation?.access != observation.access
        uploadObservation = observation
        val completed = observation.uploads.filter { it.row.status == PendingMutationStatus.Done && it.receipt != null }
        if (initialize) {
            requestGeneration += 1
            observedUploadReceipts.clear()
            observedUploadReceipts.addAll(completed.map { it.row.id })
            enrichmentObserver?.clear()
            enrichmentObserver = null
            cancelUndoTimer()
            reviewSkippedIds.clear()
            pendingCacheSeeded = false
            _uiState.value = PendingUiState(
                readOnly = isReadOnly(), upload = observation.toPendingUploadUiState(),
                uploadBinding = observation.access?.binding,
            )
            if (observation.access != null) {
                refresh()
                loadCategoryOptions()
            }
            return
        }
        _uiState.update { it.copy(readOnly = isReadOnly(), upload = observation.toPendingUploadUiState()) }
        val newlyCompleted = completed.filter { observedUploadReceipts.add(it.row.id) }
        newlyCompleted.forEach {
            onDataChanged()
            enrichmentObserver()?.track(requireNotNull(it.receipt).toPendingUploadReceipt())
        }
        if (newlyCompleted.isNotEmpty()) refresh()
    }

    private fun isReadOnly(): Boolean =
        uploadObservation?.access?.canModify != true || commandObservation?.access?.canModify != true ||
            commandObservation?.access?.binding != uploadIntents.currentUploadBinding() || !repository.canModifyLedger()

    internal fun blockReadOnlyWrite(closeSheet: Boolean = false): Boolean {
        if (!isReadOnly()) {
            _uiState.update { it.copy(readOnly = false) }
            return false
        }
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
                undoableExpense = null,
                activeSheet = if (closeSheet) PendingSheet.None else it.activeSheet,
                message = readOnlyMessage(),
            )
        }
        return true
    }

    private fun loadCategoryOptions() {
        val generation = requestGeneration
        viewModelScope.launch {
            repository.categories()
                .onSuccess { options ->
                    if (generation != requestGeneration) return@onSuccess
                    _uiState.update { it.copy(categoryOptions = options) }
                }
                .onFailure { /* 静默失败：用户仍可手动输入分类 */ }
        }
    }

    fun refresh() {
        // Issued synchronously (not inside the launch) so call order always
        // matches sequence order even if the coroutine body runs later.
        val binding = uploadObservation?.access?.binding ?: return
        val sequence = ++refreshSequence
        val generation = requestGeneration
        viewModelScope.launch {
            if (generation != requestGeneration) return@launch
            val skipEpoch = refreshSkipEpoch
            _uiState.update {
                it.copy(
                    loading = true,
                    listLoadState = PendingListLoadState.Loading,
                    message = null,
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
                    restorePendingEnrichment(expenses)
                    loadThumbnails(expenses, generation)
                }
                .onFailure { error ->
                    val knownConfirmed = repository.observeConfirmed().catch { emit(emptyList()) }.firstOrNull().orEmpty()
                    if (sequence != refreshSequence) return@onFailure
                    if (requestGeneration != generation) return@onFailure
                    if (refreshSkipEpoch != skipEpoch) return@onFailure
                    if (uploadIntents.currentUploadBinding() != binding) return@onFailure
                    _uiState.update {
                        PendingUiStateReducer.afterKnownConfirmed(it, knownConfirmed).copy(
                            hasLoadedOnce = true,
                            loading = false,
                            listLoadState = PendingListLoadState.Failed,
                            message = error.toUiText(R.string.pending_msg_load_failed),
                        )
                    }
                    recomputeReviewRemaining()
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

    internal fun currentUploadBinding(): LogicalSessionBinding? = uploadObservation?.access?.binding
        ?.takeIf { it == uploadIntents.currentUploadBinding() }

    internal suspend fun acceptUploads(request: UploadBatchRequest): Boolean {
        if (_uiState.value.uploadActionInProgress || blockReadOnlyWrite()) return false
        val binding = request.expectedBinding
        if (currentUploadBinding() != binding) {
            _uiState.update { it.copy(message = UiText.res(R.string.pending_msg_upload_ledger_switched)) }
            return false
        }
        val generation = requestGeneration
        _uiState.update { it.copy(uploadActionInProgress = true, message = null) }
        return try {
            val result = uploadIntents.acceptUploadBatch(request)
            if (generation != requestGeneration || uploadIntents.currentUploadBinding() != binding) return false
            result.onFailure { error ->
                _uiState.update { it.copy(message = error.toUiText(R.string.pending_msg_upload_failed)) }
            }.isSuccess
        } finally {
            if (generation == requestGeneration) _uiState.update { it.copy(uploadActionInProgress = false) }
        }
    }

    fun retryCapacityUpload() = recoverUploads(drop = false)

    fun discardCapacityUpload() = recoverUploads(drop = true)

    private fun recoverUploads(drop: Boolean) {
        val state = _uiState.value
        if (if (drop) !state.canStopUpload else !state.canRetryUpload || blockReadOnlyWrite()) return
        val groupId = state.upload.groupId ?: return
        val binding = uploadObservation?.access?.binding ?: return
        if (binding != uploadIntents.currentUploadBinding()) return
        val generation = requestGeneration
        _uiState.update { it.copy(uploadActionInProgress = true) }
        viewModelScope.launch {
            try {
                uploadIntents.recoverUploadGroup(binding, groupId, drop).onFailure { error ->
                    if (generation == requestGeneration) {
                        _uiState.update { it.copy(message = error.toUiText(R.string.pending_msg_upload_failed)) }
                    }
                }.onSuccess {
                    if (drop && generation == requestGeneration) {
                        _uiState.update { it.copy(message = UiText.res(R.string.pending_msg_upload_stopped)) }
                    }
                }
            } finally {
                if (generation == requestGeneration) _uiState.update { it.copy(uploadActionInProgress = false) }
            }
        }
    }

    override fun onCleared() {
        requestGeneration += 1
        enrichmentObserver?.clear()
        super.onCleared()
    }

    fun retryEnrichmentObservation() {
        enrichmentObserver?.retryPaused()
    }

    private fun restorePendingEnrichment(expenses: List<Expense>) {
        val pendingIds = expenses.map { it.id }.toSet()
        val receipts = uploadObservation?.uploads.orEmpty()
            .filter { it.row.status == PendingMutationStatus.Done }
            .mapNotNull { it.receipt?.toPendingUploadReceipt() }
            .filter { it.expenseId in pendingIds }
        if (receipts.isNotEmpty()) enrichmentObserver()?.restore(receipts)
    }

    private fun enrichmentObserver(): PendingEnrichmentObserver? {
        val taskReader = enrichmentTaskReader ?: return null
        val generation = requestGeneration
        val binding = uploadObservation?.access?.binding ?: return null
        return enrichmentObserver ?: PendingEnrichmentObserver(
            scope = viewModelScope,
            fetchTask = { taskReader.fetchPendingEnrichmentTask(it, binding) },
            canObserve = { generation == requestGeneration && uploadIntents.currentUploadBinding() == binding && !isReadOnly() },
            onStateChanged = { enrichment ->
                if (generation == requestGeneration) _uiState.update { it.copy(enrichment = enrichment) }
            },
            onTerminal = { if (generation == requestGeneration) refresh() },
        ).also { enrichmentObserver = it }
    }

    private suspend fun loadThumbnails(expenses: List<Expense>, generation: Int) {
        val loaded = thumbnailLoader.loadMissing(expenses, _uiState.value.thumbnails)
        if (requestGeneration != generation) return
        if (loaded.isNotEmpty()) {
            _uiState.update { state -> PendingUiStateReducer.afterLoadedThumbnails(state, loaded) }
        }
    }

    internal fun commandBinding(): LogicalSessionBinding? {
        val binding = commandObservation?.access?.binding
        if (binding != null && binding == currentUploadBinding() && binding == uploadIntents.currentUploadBinding()) return binding
        _uiState.update { it.copy(message = UiText.res(R.string.expense_fx_binding_changed)) }
        return null
    }

    internal fun submitPendingCommand(
        expense: Expense,
        @StringRes failureFallback: Int,
        offerUndo: Boolean = true,
        call: suspend (LogicalSessionBinding) -> Result<ExpenseCommandAcceptance>,
    ) {
        if (blockReadOnlyWrite() || expense.id in _uiState.value.actionInProgressIds) return
        if (expense.id in commandRowsByExpense) {
            _uiState.update { it.copy(message = UiText.res(R.string.expense_command_accepted)) }
            return
        }
        val binding = commandBinding() ?: return
        _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
        viewModelScope.launch {
            call(binding).onSuccess { accepted ->
                if (commandBinding() != binding) return@onSuccess
                acceptExpenseCommand(accepted, offerUndo)
            }.onFailure { error ->
                if (commandBinding() != binding) return@onFailure
                _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds - expense.id,
                    message = error.toUiText(failureFallback)) }
            }
        }
    }

    fun confirm(expense: Expense) {
        dismissUndoable()
        if (expense.amountCents == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.error_amount_required)) }
            return
        }
        submitPendingCommand(expense, R.string.pending_msg_confirm_failed) { binding ->
            repository.confirmExpenseAllowingOffline(binding, expense)
        }
    }

    fun reject(expense: Expense) = submitPendingCommand(expense, R.string.pending_msg_reject_failed) { binding ->
        repository.rejectExpenseAllowingOffline(binding, expense)
    }

    fun undoReject() {
        if (blockReadOnlyWrite()) return
        val target = _uiState.value.undoableExpense ?: return
        if (target.id in _uiState.value.actionInProgressIds) return
        val binding = commandBinding() ?: return
        dismissUndoable()
        _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + target.id, message = null) }
        viewModelScope.launch {
            repository.undoRejectExpense(binding, target).onSuccess { accepted ->
                if (commandBinding() != binding) return@onSuccess
                acceptExpenseCommand(accepted)
            }.onFailure { error ->
                if (commandBinding() != binding) return@onFailure
                _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds - target.id,
                    undoableExpense = it.undoableExpense ?: target,
                    message = error.toUiText(R.string.pending_msg_undo_failed)) }
                if (_uiState.value.undoableExpense?.id == target.id) startUndoTimer(target.id)
            }
        }
    }

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

    fun ignoreDuplicate(expense: Expense) {
        dismissUndoable()
        submitPendingCommand(expense, R.string.pending_msg_ignore_duplicate_failed, offerUndo = false) { binding ->
            repository.rejectExpenseAllowingOffline(binding, expense)
        }
    }

    fun markNotDuplicate(expense: Expense) {
        dismissUndoable()
        submitPendingCommand(expense, R.string.pending_msg_keep_failed) { binding ->
            repository.markNotDuplicateAllowingOffline(binding, expense)
        }
    }

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
