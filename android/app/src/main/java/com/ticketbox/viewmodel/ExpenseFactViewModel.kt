package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.canInitiateBillSplit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * A1: confirmed 账单的 read-first 事实详情 Owner（独立于 pending 编辑的
 * [ExpenseEditViewModel] —— 两种 Owner 责任，互不渲染对方状态）。
 *
 * 责任域拆分（同包扩展，ItemsEditor/SplitsEditor 先例模式）：
 *  - [ExpenseFactViewModelRevisions.kt]   变更记录时间线（真实 GET revisions）
 *  - [ExpenseFactViewModelCorrection.kt]  显式更正流（reason + composite draft + 四态）
 *  - [ExpenseFactViewModelBillSplit.kt]   拆账邀请（迁移自旧编辑 VM，能力不丢）
 */
data class ExpenseFactUiState(
    val expense: Expense? = null,
    val expenseLoading: Boolean = true,
    val expenseLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Loading,
    /** True when known content is shown because the authoritative refresh failed. */
    val expenseStale: Boolean = false,
    val expenseLoadMessage: UiText? = null,
    val readOnly: Boolean = false,
    val thumbnail: ProtectedImage? = null,
    val thumbnailLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Unknown,
    val thumbnailMessage: UiText? = null,
    val fullImage: ProtectedImage? = null,
    val imageLoading: Boolean = false,
    val categories: List<String> = DEFAULT_EXPENSE_CATEGORIES,
    val expenseItems: ExpenseItems? = null,
    val expenseSplits: ExpenseSplits? = null,
    val itemsLoading: Boolean = false,
    val splitsLoading: Boolean = false,
    val itemsLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Unknown,
    val splitsLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Unknown,
    val itemsMessage: UiText? = null,
    val splitsMessage: UiText? = null,
    // 变更记录（revisions 扩展拥有加载逻辑；展示模型在 UI 层由其 mapper 生成）。
    val revisions: List<com.ticketbox.domain.model.ExpenseRevision> = emptyList(),
    val revisionsTotal: Int = 0,
    val revisionsLoading: Boolean = false,
    val revisionsLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Unknown,
    val revisionsNextPage: Int? = null,
    /** 当前已加载历史所属的服务端快照锚；null = 尚未加载或最近一次首读失败。 */
    val revisionsSnapshotRevision: Long? = null,
    val revisionsOlderLoading: Boolean = false,
    val revisionsOlderLoadFailed: Boolean = false,
    val revisionsRefreshFailed: Boolean = false,
    /** null means the current member directory could not be read. */
    val revisionMemberNames: Map<Long, String>? = null,
    val timelineExpanded: Boolean = false,
    // 更正流（correction 扩展拥有全部逻辑）。
    val correction: CorrectionFormState = CorrectionFormState(),
    // 拆账邀请（bill-split 扩展拥有逻辑；字段名与旧编辑 VM 同构，便于组件复用）。
    val billSplitSent: List<com.ticketbox.domain.model.BillSplitSent> = emptyList(),
    val billSplitSentLoadState: BillSplitSentLoadState = BillSplitSentLoadState.Unknown,
    val billSplitLoading: Boolean = false,
    val billSplitMessage: UiText? = null,
    val billSplitMessageTone: MessageTone = MessageTone.Neutral,
    val billSplitInviteSheetOpen: Boolean = false,
    val billSplitInviteMembers: List<com.ticketbox.domain.model.FamilyMember> = emptyList(),
    val billSplitInviteMembersLoading: Boolean = false,
    val billSplitInviteSelectedMemberId: Long? = null,
    val billSplitInviteAmountText: String = "",
    val billSplitInviteSending: Boolean = false,
    val billSplitInviteMessage: UiText? = null,
    val billSplitInviteMessageTone: MessageTone = MessageTone.Neutral,
    // 还款捕获草稿（迁移能力）。
    val repaymentDraftCreating: Boolean = false,
    val openRepaymentDraftPublicId: String? = null,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val done: Boolean = false,

    /** 与编辑页同义：本次离开时需要失效建议缓存（金额/币种/分类/时间发生了变化）。 */
    val doneAdviceInputsChanged: Boolean = false,
)

/** 更正表单态（reason 必填但降层级；draft 相对 baseline 的 diff 决定提交内容）。 */
data class CorrectionFormState(
    val open: Boolean = false,
    val reason: String = "",
    val merchant: String = "",
    val category: String = "",
    val tags: String = "",
    val note: String = "",
    val amountText: String = "",
    val currency: CurrencyCode = FxContract.HomeCurrency,
    val currencyTouched: Boolean = false,
    /** Non-null means the current raw code is outside this client support set. */
    val unsupportedCurrencyCode: String? = null,
    val foreignCurrency: Boolean = false,
    val expenseTimeText: String = "",
    val valueScore: Int? = null,
    val regretScore: Int? = null,
    val amountError: UiText? = null,
    val timeError: UiText? = null,
    val conflictMessage: UiText? = null,
    val submitError: UiText? = null,
    val itemsEditorOpen: Boolean = false,
    val itemDrafts: List<EditableItem> = emptyList(),
    val itemsTouched: Boolean = false,
    val splitEditorOpen: Boolean = false,
    val splitDrafts: List<EditableSplit> = emptyList(),
    val splitMembersLoading: Boolean = false,
    val splitsTouched: Boolean = false,
    val saving: Boolean = false,
)

class ExpenseFactViewModel(
    internal val expenseId: Long,
    internal val repository: ExpenseFactActions,
    initialExpense: Expense? = null,
) : ViewModel() {

    internal var revisionLoadGeneration = 0L

    internal val _uiState = MutableStateFlow(
        ExpenseFactUiState(
            expense = initialExpense,
            expenseLoading = initialExpense == null,
            expenseLoadState = if (initialExpense == null) {
                ExpenseDetailDataLoadState.Loading
            } else {
                ExpenseDetailDataLoadState.Loaded
            },
            readOnly = !repository.canModifyLedger(),
        ),
    )
    val uiState: StateFlow<ExpenseFactUiState> = _uiState.asStateFlow()

    init {
        if (initialExpense == null) {
            loadExpense()
        } else if (initialExpense.canInitiateBillSplit(_uiState.value.readOnly)) {
            loadBillSplitSent()
        }
        loadCategories()
        initialExpense?.let { loadThumbnailFor(it) }
        loadExpenseItems()
        loadExpenseSplits()
        loadExpenseRevisions()
        loadRevisionMemberNames()
    }

    fun retryLoadExpense() {
        loadExpense()
    }

    private fun loadExpense() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    expenseLoading = true,
                    expenseLoadState = ExpenseDetailDataLoadState.Loading,
                    expenseStale = false,
                    expenseLoadMessage = null,
                )
            }
            repository.fetchExpense(expenseId)
                .onSuccess { expense ->
                    _uiState.update {
                        it.copy(
                            expense = expense,
                            expenseLoading = false,
                            expenseLoadState = ExpenseDetailDataLoadState.Loaded,
                            expenseStale = false,
                            expenseLoadMessage = null,
                        )
                    }
                    loadThumbnailFor(expense)
                    // confirmed 才能发起拆账邀请（domain 门）；满足才拉取，避免无谓请求。
                    if (expense.canInitiateBillSplit(_uiState.value.readOnly)) {
                        loadBillSplitSent()
                    }
                }
                .onFailure { refreshError ->
                    resolveExpenseRefreshFailure(refreshError)
                }
        }
    }

    private suspend fun resolveExpenseRefreshFailure(refreshError: Throwable) {
        if (_uiState.value.expense != null) {
            _uiState.update {
                it.copy(
                    expenseLoading = false,
                    expenseLoadState = ExpenseDetailDataLoadState.Failed,
                    expenseStale = true,
                    expenseLoadMessage = refreshError.toUiText(
                        R.string.expense_fact_refresh_failed_showing_known,
                    ),
                )
            }
            return
        }
        // 离线兜底：本地缓存有就展示缓存事实（徽标/时间线可能缺席，
        // 但读取面不空）；没有才进入可重试的错误态。
        repository.fetchExpenseFromLocalCache(expenseId)
            .onSuccess { cached ->
                _uiState.update {
                    it.copy(
                        expense = cached,
                        expenseLoading = false,
                        expenseLoadState = ExpenseDetailDataLoadState.Failed,
                        expenseStale = true,
                        expenseLoadMessage = UiText.res(R.string.expense_fact_cached_showing),
                    )
                }
                loadThumbnailFor(cached)
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        expenseLoading = false,
                        expenseLoadState = ExpenseDetailDataLoadState.Failed,
                        expenseStale = false,
                        expenseLoadMessage = error.toUiText(
                            R.string.expense_edit_loading_empty_fallback,
                        ),
                    )
                }
            }
    }

    private fun loadCategories() {
        viewModelScope.launch {
            repository.categories()
                .onSuccess { list ->
                    _uiState.update { it.copy(categories = list) }
                }
        }
    }

    fun retryLoadThumbnail() {
        _uiState.value.expense?.let { loadThumbnailFor(it, force = true) }
    }

    private fun loadThumbnailFor(expense: Expense, force: Boolean = false) {
        if (!expense.hasImage) {
            _uiState.update {
                it.copy(
                    thumbnail = null,
                    thumbnailLoadState = ExpenseDetailDataLoadState.Loaded,
                    thumbnailMessage = null,
                )
            }
            return
        }
        if (!force && (
                _uiState.value.thumbnail != null ||
                    _uiState.value.thumbnailLoadState == ExpenseDetailDataLoadState.Loading
                )
        ) {
            return
        }
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    thumbnailLoadState = ExpenseDetailDataLoadState.Loading,
                    thumbnailMessage = null,
                )
            }
            repository.fetchThumbnail(expenseId)
                .onSuccess { image ->
                    _uiState.update {
                        it.copy(
                            thumbnail = image,
                            thumbnailLoadState = ExpenseDetailDataLoadState.Loaded,
                            thumbnailMessage = null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            thumbnail = null,
                            thumbnailLoadState = ExpenseDetailDataLoadState.Failed,
                            thumbnailMessage = error.toUiText(R.string.expense_fact_thumbnail_failed),
                        )
                    }
                }
        }
    }

    fun loadFullImage() {
        if (_uiState.value.fullImage != null || _uiState.value.imageLoading) return
        viewModelScope.launch {
            _uiState.update { it.copy(imageLoading = true) }
            repository.fetchImage(expenseId)
                .onSuccess { image ->
                    _uiState.update { it.copy(fullImage = image, imageLoading = false) }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            imageLoading = false,
                            message = error.toUiText(R.string.expense_edit_image_open_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun loadExpenseItems() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    itemsLoading = true,
                    itemsLoadState = ExpenseDetailDataLoadState.Loading,
                    itemsMessage = null,
                )
            }
            repository.fetchExpenseItems(expenseId)
                .onSuccess { items ->
                    _uiState.update {
                        it.copy(
                            expenseItems = items,
                            itemsLoading = false,
                            itemsLoadState = ExpenseDetailDataLoadState.Loaded,
                            itemsMessage = null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            itemsLoading = false,
                            itemsLoadState = ExpenseDetailDataLoadState.Failed,
                            itemsMessage = error.toUiText(R.string.expense_fact_items_failed),
                        )
                    }
                }
        }
    }

    fun loadExpenseSplits() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    splitsLoading = true,
                    splitsLoadState = ExpenseDetailDataLoadState.Loading,
                    splitsMessage = null,
                )
            }
            repository.fetchExpenseSplits(expenseId)
                .onSuccess { splits ->
                    _uiState.update {
                        it.copy(
                            expenseSplits = splits,
                            splitsLoading = false,
                            splitsLoadState = ExpenseDetailDataLoadState.Loaded,
                            splitsMessage = null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            splitsLoading = false,
                            splitsLoadState = ExpenseDetailDataLoadState.Failed,
                            splitsMessage = error.toUiText(R.string.expense_fact_splits_failed),
                        )
                    }
                }
        }
    }

    fun consumeDoneAdviceInputsChanged(): Boolean {
        val changed = _uiState.value.doneAdviceInputsChanged
        if (changed) {
            _uiState.update { it.copy(doneAdviceInputsChanged = false) }
        }
        return changed
    }

    /** 只读账本写入门：所有更正/拆账/还款动作先过此门。 */
    internal fun blockReadOnlyWrite(): Boolean {
        if (!_uiState.value.readOnly) return false
        _uiState.update {
            it.copy(
                readOnly = true,
                message = UiText.res(R.string.expense_correction_readonly_blocked),
                messageTone = MessageTone.Danger,
            )
        }
        return true
    }
}
