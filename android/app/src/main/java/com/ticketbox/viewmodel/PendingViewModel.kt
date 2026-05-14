package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit

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
) : ViewModel() {
    private companion object {
        const val THUMBNAIL_CONCURRENCY = 4
    }

    internal val _uiState = MutableStateFlow(PendingUiState())
    val uiState: StateFlow<PendingUiState> = _uiState.asStateFlow()

    init {
        val readOnly = !repository.canModifyLedger()
        _uiState.update { it.copy(readOnly = readOnly, message = if (readOnly) READ_ONLY_LEDGER_MESSAGE else it.message) }
        refresh()
        loadCategoryOptions()
    }

    private fun isReadOnly(): Boolean = !repository.canModifyLedger()

    internal fun blockReadOnlyWrite(closeSheet: Boolean = false): Boolean {
        if (!isReadOnly()) {
            _uiState.update { it.copy(readOnly = false) }
            return false
        }
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
            _uiState.update { it.copy(loading = true, message = null) }
            repository.fetchPending()
                .onSuccess { expenses ->
                    val ids = expenses.map { expense -> expense.id }.toSet()
                    _uiState.update {
                        it.copy(
                            items = expenses,
                            thumbnails = it.thumbnails.filterKeys { id -> id in ids },
                            activeSheet = reconcileActiveSheet(it.activeSheet, expenses),
                            readOnly = isReadOnly(),
                            loading = false,
                        )
                    }
                    loadThumbnails(expenses)
                }
                .onFailure { error -> _uiState.update { it.copy(loading = false, message = error.message ?: "暂时加载不了，请稍后再试。") } }
        }
    }

    fun markUploadPreparing(): Boolean {
        if (blockReadOnlyWrite()) return false
        if (_uiState.value.uploading) return false
        _uiState.update { it.copy(uploading = true, message = null) }
        return true
    }

    fun uploadPreparationFailed(message: String = "这张图片暂时无法读取，请换一张试试。") {
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
                _uiState.update { it.copy(uploading = true, message = null) }
            }
            repository.uploadScreenshot(
                fileName = fileName,
                contentType = contentType,
                bytes = bytes,
                preparationDurationMs = preparationDurationMs,
                sourceSizeBytes = sourceSizeBytes,
            )
                .onSuccess {
                    _uiState.update { state ->
                        state.copy(uploading = false, message = "截图已上传，等你确认。")
                    }
                    refresh()
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            uploading = false,
                            message = error.message ?: "没有上传成功，请稍后再试。",
                        )
                    }
                }
        }
    }

    private suspend fun loadThumbnails(expenses: List<Expense>) = coroutineScope {
        val pendingIds = expenses.map { expense -> expense.id }.toSet()
        val missing = expenses.filter { expense ->
            expense.imagePath != null && !_uiState.value.thumbnails.containsKey(expense.id)
        }
        if (missing.isEmpty()) return@coroutineScope

        val limiter = Semaphore(THUMBNAIL_CONCURRENCY)
        val loaded = missing
            .map { expense ->
                async {
                    limiter.withPermit {
                        repository.fetchThumbnail(expense.id)
                            .getOrNull()
                            ?.let { image -> expense.id to image }
                    }
                }
            }
            .awaitAll()
            .filterNotNull()
            .filter { (id, _) -> id in pendingIds }
            .toMap()

        if (loaded.isNotEmpty()) {
            _uiState.update { state ->
                val activeIds = state.items.map { expense -> expense.id }.toSet()
                state.copy(thumbnails = state.thumbnails + loaded.filterKeys { id -> id in activeIds })
            }
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
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.confirmExpense(expense.id)
                .onSuccess { confirmed ->
                    _uiState.update { state ->
                        state.copy(
                            items = state.items.filterNot { it.id == confirmed.id },
                            thumbnails = state.thumbnails - confirmed.id,
                            actionInProgressIds = state.actionInProgressIds - confirmed.id,
                            message = "已确认入账",
                        )
                    }
                }
                .onFailure { error ->
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
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.rejectExpense(expense.id)
                .onSuccess { rejected ->
                    _uiState.update { state ->
                        state.copy(
                            items = state.items.filterNot { it.id == rejected.id },
                            thumbnails = state.thumbnails - rejected.id,
                            actionInProgressIds = state.actionInProgressIds - rejected.id,
                            activeSheet = PendingSheet.None,
                            message = "已删除",
                        )
                    }
                }
                .onFailure { error ->
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
            _uiState.update { it.copy(actionInProgressIds = it.actionInProgressIds + expense.id, message = null) }
            repository.markNotDuplicate(expense.id)
                .onSuccess { updated ->
                    _uiState.update { state ->
                        state.copy(
                            items = state.items.map { if (it.id == updated.id) updated else it },
                            actionInProgressIds = state.actionInProgressIds - updated.id,
                            activeSheet = PendingSheet.None,
                            message = "已保留这条账单",
                        )
                    }
                }
                .onFailure { error ->
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
