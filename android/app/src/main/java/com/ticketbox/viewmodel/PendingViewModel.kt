package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseStateOutcome
import com.ticketbox.data.repository.PendingThumbnailLoader
import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
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
        _uiState.update {
            it.copy(
                readOnly = true,
                uploading = false,
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
            _uiState.update { it.copy(loading = true, message = null) }
            repository.fetchPending()
                .onSuccess { expenses ->
                    if (requestGeneration != generation) return@onSuccess
                    _uiState.update { PendingUiStateReducer.afterRefresh(it, expenses, readOnly = isReadOnly()) }
                    loadThumbnails(expenses, generation)
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
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

    fun confirm(expense: Expense) {
        if (blockReadOnlyWrite()) return
        if (expense.amountCents == null) {
            _uiState.update { it.copy(message = "请先填写金额。") }
            return
        }
        if (expense.id in _uiState.value.actionInProgressIds) return
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.confirmExpenseAllowingOffline(expense)
                .onSuccess { outcome ->
                    if (requestGeneration != generation) return@onSuccess
                    val message = when (outcome) {
                        is ExpenseStateOutcome.Synced -> "已确认入账"
                        is ExpenseStateOutcome.Queued -> "已离线确认，联网后同步"
                    }
                    _uiState.update { state ->
                        PendingUiStateReducer.afterConfirmed(state, outcome.expense, message = message)
                    }
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    _uiState.update {
                        it.copy(
                            actionInProgressIds = it.actionInProgressIds - expense.id,
                            message = error.message ?: "没有确认成功，请稍后再试。",
                        )
                    }
                }
        }
    }

    fun reject(expense: Expense) {
        if (blockReadOnlyWrite()) return
        if (expense.id in _uiState.value.actionInProgressIds) return
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.rejectExpenseAllowingOffline(expense)
                .onSuccess { outcome ->
                    if (requestGeneration != generation) return@onSuccess
                    val message = when (outcome) {
                        is ExpenseStateOutcome.Synced -> "已删除"
                        is ExpenseStateOutcome.Queued -> "已离线删除，联网后同步"
                    }
                    _uiState.update { state ->
                        PendingUiStateReducer.afterRejected(state, outcome.expense, message = message)
                    }
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    _uiState.update {
                        it.copy(
                            actionInProgressIds = it.actionInProgressIds - expense.id,
                            message = error.message ?: "没有删除成功，请稍后再试。",
                        )
                    }
                }
        }
    }

    fun markNotDuplicate(expense: Expense) {
        if (blockReadOnlyWrite()) return
        if (expense.id in _uiState.value.actionInProgressIds) return
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.markNotDuplicate(expense.id, expense.updatedAt)
                .onSuccess { updated ->
                    if (requestGeneration != generation) return@onSuccess
                    _uiState.update { state ->
                        PendingUiStateReducer.afterUpdated(
                            current = state,
                            updated = updated,
                            closeSheet = true,
                            message = "已保留这条账单",
                        )
                    }
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    _uiState.update {
                        it.copy(
                            actionInProgressIds = it.actionInProgressIds - expense.id,
                            message = error.message ?: "暂时没处理成功，请稍后再试。",
                        )
                    }
                }
        }
    }
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
