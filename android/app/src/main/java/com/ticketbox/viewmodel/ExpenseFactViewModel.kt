package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseFactBundle
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
 *  - [ExpenseFactViewModelOffsets.kt]     退回与冲销：bundle 读 + 登记表单态
 *  - ExpenseFactViewModelOffsetsCommands.kt / OffsetsVoid.kt  登记/撤销命令与发布
 */
data class ExpenseFactUiState(
    val expense: Expense? = null,
    val expenseLoading: Boolean = true,
    val expenseLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Loading,
    /** True when known content is shown because the authoritative refresh failed. */
    val expenseStale: Boolean = false,
    /** This view must adopt every receipt version it has observed, even after another reader acknowledges it. */
    val requiredRootRowVersion: Long = 0L,
    val initialRootVerificationPending: Boolean = false,
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
    val correctionAccess: com.ticketbox.data.repository.LedgerAccessContext? = null,
    val corrections: List<com.ticketbox.data.repository.PendingExpenseCorrection> = emptyList(),
    val correctionRecoveryBusy: Boolean = false,
    // 更正流（correction 扩展拥有全部逻辑）。
    val correction: CorrectionFormState = CorrectionFormState(),
    // 退回与冲销（offsets 扩展拥有逻辑；bundle = 服务端原子事实包，pending 只是
    // 会话内待提交表达，持久队列归 Outbox；command 不依赖 bundle 是否可读）。
    val factBundle: ExpenseFactBundle? = null,
    val factBundleLoadState: ExpenseDetailDataLoadState = ExpenseDetailDataLoadState.Unknown,
    val factBundleMessage: UiText? = null,
    val offsetForm: OffsetFormState = OffsetFormState(),
    val voidOffsetForm: VoidOffsetFormState = VoidOffsetFormState(),
    /** A 409 raised this root's OCC gate; only an adopted authoritative bundle clears it. */
    // 拆账邀请（bill-split 扩展拥有逻辑；字段名与旧编辑 VM 同构，便于组件复用）。
    val billSplitSubmissions: List<com.ticketbox.data.repository.PendingBillSplitCreation> = emptyList(),
    val billSplitRecoveryBusy: Boolean = false,
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
) {
    val authoritativeRootReady: Boolean get() = correctionAccess != null && expense != null &&
        !initialRootVerificationPending && expense.rowVersion >= requiredRootRowVersion &&
        !expenseLoading && !expenseStale &&
        expenseLoadState == ExpenseDetailDataLoadState.Loaded && corrections.none { !it.delivered || it.refreshRequired }

    val canStartCorrection: Boolean get() = !readOnly && authoritativeRootReady
}

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
    preferLocalCache: Boolean = false,
) : ViewModel() {

    internal var correctionOriginalItems: ExpenseItems? = null
    internal var correctionOriginalSplits: ExpenseSplits? = null
    internal var correctionBaseline: Expense? = null
    internal var correctionBinding: com.ticketbox.data.repository.LogicalSessionBinding? = null
    internal var correctionSplitMemberGeneration = 0L
    internal var observedCorrectionCompletions: Set<Long>? = null
    internal var expenseLoadGeneration = 0L
    internal var expenseReadInFlightGeneration: Long? = null
    internal var itemsLoadGeneration = 0L
    internal var splitsLoadGeneration = 0L
    internal var revisionLoadGeneration = 0L
    internal var thumbnailLoadGeneration = 0L
    internal var fullImageLoadGeneration = 0L

    /** bundle 读/命令的 authority 序号：只在调用点同步递增（见 Offsets 扩展）。 */
    internal var factBundleLoadGeneration = 0L

    internal val _uiState = MutableStateFlow(ExpenseFactUiState(readOnly = true))
    val uiState: StateFlow<ExpenseFactUiState> = _uiState.asStateFlow()

    init {
        observeBillSplitSubmissions()
        var verifyInitialCache = preferLocalCache
        observeCorrectionSubmissions {
            if (verifyInitialCache) {
                verifyInitialCache = false
                verifyInitialExpenseFromCache { loadExpense(initialLoad = true) }
            } else {
                loadExpense(initialLoad = true)
            }
            loadCategories()
            loadExpenseItems()
            loadExpenseSplits()
            loadExpenseFactBundle()
            loadExpenseRevisions()
            loadRevisionMemberNames()
        }
    }

    fun retryLoadExpense() {
        loadExpense()
    }

    private fun loadExpense(initialLoad: Boolean = false) {
        val generation = ++expenseLoadGeneration
        expenseReadInFlightGeneration = generation
        _uiState.update {
            it.copy(
                expenseLoading = true,
                initialRootVerificationPending = false,
                expenseLoadState = ExpenseDetailDataLoadState.Loading,
                expenseStale = false,
                expenseLoadMessage = null,
            )
        }
        viewModelScope.launch {
            if (generation != expenseLoadGeneration) return@launch
            repository.fetchExpense(expenseId)
                .onSuccess { expense ->
                    if (generation != expenseLoadGeneration) return@onSuccess
                    _uiState.update {
                        // 单调采用：bundle 读/命令已发布更新的 root 时，较旧的
                        // fetchExpense 响应不倒灌 expense（OCC token 不回退）。
                        val current = it.expense
                        val adopt = current == null || current.id != expense.id ||
                            expense.rowVersion >= current.rowVersion
                        it.copy(
                            expense = if (adopt) expense else current,
                            expenseLoading = false,
                            expenseLoadState = ExpenseDetailDataLoadState.Loaded,
                            expenseStale = false,
                            expenseLoadMessage = null,
                        )
                    }
                    loadThumbnailFor(expense)
                    // confirmed 才能发起拆账邀请（domain 门）；满足才拉取，避免无谓请求。
                    if (_uiState.value.expense?.canInitiateBillSplit(_uiState.value.readOnly) == true) {
                        loadBillSplitSent(onlyIfUnknown = initialLoad)
                    }
                }
                .onFailure { refreshError ->
                    if (generation != expenseLoadGeneration) return@onFailure
                    resolveExpenseRefreshFailure(refreshError, generation)
                }
        }.invokeOnCompletion {
            if (expenseReadInFlightGeneration == generation) expenseReadInFlightGeneration = null
        }
    }

    private suspend fun resolveExpenseRefreshFailure(refreshError: Throwable, generation: Long) {
        if (generation != expenseLoadGeneration) return
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
                if (generation != expenseLoadGeneration) return@onSuccess
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
                if (generation != expenseLoadGeneration) return@onFailure
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
        val binding = _uiState.value.correctionAccess?.binding ?: return
        viewModelScope.launch {
            if (binding != _uiState.value.correctionAccess?.binding) return@launch
            repository.categories()
                .onSuccess { list ->
                    _uiState.update {
                        if (binding == it.correctionAccess?.binding) it.copy(categories = list) else it
                    }
                }
        }
    }

    fun retryLoadThumbnail() {
        _uiState.value.expense?.let { loadThumbnailFor(it, force = true) }
    }

    internal fun loadThumbnailFor(expense: Expense, force: Boolean = false) {
        val binding = _uiState.value.correctionAccess?.binding ?: return
        if (!expense.hasImage) {
            thumbnailLoadGeneration++
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
        val generation = ++thumbnailLoadGeneration
        _uiState.update {
            it.copy(
                thumbnailLoadState = ExpenseDetailDataLoadState.Loading,
                thumbnailMessage = null,
            )
        }
        viewModelScope.launch {
            if (!isCurrentMediaRequest(binding, generation, thumbnailLoadGeneration)) return@launch
            repository.fetchThumbnail(expenseId)
                .onSuccess { image ->
                    if (!isCurrentMediaRequest(binding, generation, thumbnailLoadGeneration)) return@onSuccess
                    _uiState.update {
                        it.copy(
                            thumbnail = image,
                            thumbnailLoadState = ExpenseDetailDataLoadState.Loaded,
                            thumbnailMessage = null,
                        )
                    }
                }
                .onFailure { error ->
                    if (!isCurrentMediaRequest(binding, generation, thumbnailLoadGeneration)) return@onFailure
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
        val binding = _uiState.value.correctionAccess?.binding ?: return
        if (_uiState.value.fullImage != null || _uiState.value.imageLoading) return
        val generation = ++fullImageLoadGeneration
        _uiState.update { it.copy(imageLoading = true) }
        viewModelScope.launch {
            if (!isCurrentMediaRequest(binding, generation, fullImageLoadGeneration)) return@launch
            repository.fetchImage(expenseId)
                .onSuccess { image ->
                    if (!isCurrentMediaRequest(binding, generation, fullImageLoadGeneration)) return@onSuccess
                    _uiState.update { it.copy(fullImage = image, imageLoading = false) }
                }
                .onFailure { error ->
                    if (!isCurrentMediaRequest(binding, generation, fullImageLoadGeneration)) return@onFailure
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
        val generation = ++itemsLoadGeneration
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
                    if (generation != itemsLoadGeneration) return@onSuccess
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
                    if (generation != itemsLoadGeneration) return@onFailure
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
        val generation = ++splitsLoadGeneration
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
                    if (generation != splitsLoadGeneration) return@onSuccess
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
                    if (generation != splitsLoadGeneration) return@onFailure
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

private fun ExpenseFactViewModel.isCurrentMediaRequest(
    binding: LogicalSessionBinding,
    generation: Long,
    currentGeneration: Long,
): Boolean = generation == currentGeneration && binding == _uiState.value.correctionAccess?.binding
