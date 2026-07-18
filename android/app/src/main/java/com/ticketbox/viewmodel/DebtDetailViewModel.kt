package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtDetailActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtRepaymentHistory
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0049 §3 (slice 8c) 欠款详情 + 记账管理 —— 进入欠款详情后记还款（§3.1）/ 调整本金（§3.3）/
 * 撤销误记还款（§3.4）/ 作废欠款（§3.5）。四类写都是直接提交事实（external/manual 欠款；成员/拆账欠款走 slice8d 的对方
 * 确认流程，后端 [guard_direct_fact_writable] 对其返回 409），均带 §2.1 OCC 载体
 * （[DebtDetailUiState.debt] 的 `rowVersion`）。提交成功后用服务端折叠后的 [Debt] 原子替换本地态，
 * 故下一次写自动用新的 `rowVersion`。
 *
 * 一个统一的动作面板（[activeAction]）承载四类写：还款只填金额，调整填金额+原因，撤销还款/作废填原因，
 * 让详情屏保持纯渲染。详情自身的数据由进入时的 [refresh] 拉取（账本隔离 + 始终最新），写返回的
 * 折叠态直接覆盖本地 [debt]，无需再次拉取。
 */
data class DebtDetailUiState(
    val isLoading: Boolean = false,
    val debt: Debt? = null,
    val canModify: Boolean = true,
    val error: UiText? = null,
    val activeAction: DebtAction? = null,
    val amountInput: String = "",
    val reasonInput: String = "",
    // Adjustment is a signed delta, but the decimal keyboard exposes no minus key, so the amount
    // field is a positive magnitude and this toggle carries the sign (true = raise `remaining`).
    val adjustmentIncrease: Boolean = true,
    val validationError: UiText? = null,
    val isSubmitting: Boolean = false,
    val flashMessage: UiText? = null,
    // Canonical first page loaded from Repayment + RepaymentVoid facts. This is deliberately
    // independent from the current process/session so reopening the detail restores audit history.
    val repaymentHistory: DebtRepaymentHistory? = null,
    val isRepaymentHistoryLoading: Boolean = false,
    val repaymentHistoryError: UiText? = null,
    val isRepaymentHistoryLoadingMore: Boolean = false,
    val repaymentHistoryLoadMoreError: UiText? = null,
    // Stable id selected from an ACTIVE canonical fact; never reconstructed from amount or Debt.
    val repaymentToVoidPublicId: String? = null,
)

/** Direct fact writes submitted from the detail action surface (ADR-0049 §3.1 / §3.3–§3.5). */
enum class DebtAction { Repayment, Adjustment, RepaymentVoid, Void }

/**
 * A one-shot member-debt 两清 celebration signal (ADR-0049 §5.2 / slice 8e-4): the viewer witnessed a
 * member Debt cross open→cleared (non-forgiven) in this VM lifetime. [counterpartyLabel] picks the
 * named vs anonymous body copy. Presentation metadata only — never a financial truth.
 */
data class DebtSettleCelebration(val counterpartyLabel: String?)

class DebtDetailViewModel(
    private val repository: DebtDetailActions,
) : ViewModel() {

    private val _state = MutableStateFlow(DebtDetailUiState(canModify = repository.canModifyLedger()))
    val state: StateFlow<DebtDetailUiState> = _state.asStateFlow()

    // ADR-0049 §5.2 (slice 8e-4) 两清庆祝边沿检测。三条 →cleared 路径（债权人 confirm / 债务人目击 /
    // forgive）都终结于「详情屏持有的 Debt 跨过 →cleared 边沿」，故只在换入服务端 DTO 的一处做检测。
    // [previousStatusByPublicId] 记录本 VM 生命周期内每笔 Debt 上一次见到的 status：crossedEdge 要求有
    // 明确的非-cleared 先值，所以首次打开一笔「几周前就已 cleared」的债不撒花（P1#4 修复）。
    // [celebratedDebtIds] 去重，refresh / 重进详情都不重放。只读服务端权威 DTO，无乐观本地 status 改写。
    private val previousStatusByPublicId = mutableMapOf<String, String>()
    private val celebratedDebtIds = mutableSetOf<String>()
    private val _celebration = MutableStateFlow<DebtSettleCelebration?>(null)
    val celebration: StateFlow<DebtSettleCelebration?> = _celebration.asStateFlow()

    // The reusable detail VM (one instance, keyed by a constant in DebtRoute) is told which Debt to
    // show by [loadDebt] on each (re)entry, so reopening always re-fetches rather than showing a
    // retained stale fold; [refresh] (pull-to-refresh) re-reads the same id.
    private var loadedPublicId: String? = null

    // Monotonic load token (mirrors DebtGoalViewModel): a refresh applies its result only if it is
    // still the latest. Reopening the reusable detail VM with another Debt ([loadDebt]), pull-to-
    // refresh, and a committed write ([submit]) each supersede an in-flight load, so a slow earlier
    // getDebt can't clobber a just-reopened Debt or revert a just-committed fold to a stale
    // row_version (→ a 409 on the next write).
    private var loadGeneration = 0L

    // The latest refresh's token. The loading flag is owned by the latest refresh; a refresh
    // superseded by a NON-refresh (a committed [submit] bumps loadGeneration but is not a refresh)
    // must clear its own loading flag when no newer refresh has taken over — else the screen sticks
    // "loading".
    private var latestRefreshGeneration = 0L

    fun loadDebt(publicId: String) {
        val previousPublicId = loadedPublicId
        loadedPublicId = publicId
        if (previousPublicId != publicId) {
            _state.update {
                it.copy(
                    debt = null,
                    error = null,
                    activeAction = null,
                    amountInput = "",
                    reasonInput = "",
                    adjustmentIncrease = true,
                    validationError = null,
                    isSubmitting = false,
                    flashMessage = null,
                    repaymentHistory = null,
                    isRepaymentHistoryLoading = false,
                    repaymentHistoryError = null,
                    isRepaymentHistoryLoadingMore = false,
                    repaymentHistoryLoadMoreError = null,
                    repaymentToVoidPublicId = null,
                )
            }
        }
        refresh()
    }

    fun refresh() {
        val publicId = loadedPublicId ?: return
        val gen = ++loadGeneration
        latestRefreshGeneration = gen
        _state.update {
            it.copy(
                isLoading = true,
                error = null,
                isRepaymentHistoryLoading = true,
                repaymentHistoryError = null,
                isRepaymentHistoryLoadingMore = false,
                repaymentHistoryLoadMoreError = null,
            )
        }
        viewModelScope.launch {
            val result = repository.getDebt(publicId)
            val historyResult = if (result.isSuccess) {
                repository.listRepaymentFacts(publicId, REPAYMENT_HISTORY_FIRST_PAGE)
            } else {
                null
            }
            // Drop a load superseded by a newer load or a committed write — before celebration
            // detection (a discarded snapshot must not record a status edge). Clear our loading flag
            // only when no newer refresh now owns it (a non-refresh superseder — submit — would
            // otherwise leave the screen stuck loading).
            if (gen != loadGeneration) {
                if (gen == latestRefreshGeneration) {
                    _state.update { it.copy(isLoading = false, isRepaymentHistoryLoading = false) }
                }
                return@launch
            }
            result.fold(
                onSuccess = { debt ->
                    detectSettleCelebration(debt, previousStatusByPublicId, celebratedDebtIds)
                        ?.let { _celebration.value = it }
                    _state.update {
                        it.withRepaymentHistory(checkNotNull(historyResult)).copy(
                            isLoading = false,
                            debt = debt,
                            canModify = repository.canModifyLedger(),
                            error = null,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            isRepaymentHistoryLoading = false,
                            error = err.toUiText(R.string.debt_detail_load_failed),
                        )
                    }
                },
            )
        }
    }

    fun loadMoreRepaymentHistory() {
        val current = _state.value
        val publicId = loadedPublicId ?: return
        val history = current.repaymentHistory ?: return
        if (current.isRepaymentHistoryLoading ||
            current.isRepaymentHistoryLoadingMore ||
            current.repaymentHistoryError != null ||
            !history.hasMore
        ) {
            return
        }
        val requestedPage = history.page + 1
        val generation = loadGeneration
        _state.update {
            it.copy(
                isRepaymentHistoryLoadingMore = true,
                repaymentHistoryLoadMoreError = null,
            )
        }
        viewModelScope.launch {
            val result = repository.listRepaymentFacts(publicId, requestedPage)
            if (generation != loadGeneration || loadedPublicId != publicId) return@launch
            _state.update {
                it.withNextRepaymentHistoryPage(
                    result = result,
                    expectedDebtPublicId = publicId,
                    expectedPage = requestedPage,
                )
            }
        }
    }

    fun openAction(action: DebtAction, repaymentPublicId: String? = null) {
        val current = _state.value
        if (!current.canModify) return
        val selectedRepaymentPublicId = current.repaymentHistory
            ?.items
            ?.firstOrNull { fact -> fact.publicId == repaymentPublicId && fact.isActive }
            ?.publicId
        if (action == DebtAction.RepaymentVoid &&
            (selectedRepaymentPublicId == null ||
                current.isRepaymentHistoryLoading ||
                current.repaymentHistoryError != null)
        ) {
            return
        }
        _state.update {
            it.copy(
                activeAction = action,
                amountInput = "",
                reasonInput = "",
                adjustmentIncrease = true,
                validationError = null,
                repaymentToVoidPublicId = selectedRepaymentPublicId,
            )
        }
    }

    fun updateActionInput(
        amount: String? = null,
        reason: String? = null,
        adjustmentIncrease: Boolean? = null,
    ) {
        _state.update {
            it.copy(
                amountInput = amount ?: it.amountInput,
                reasonInput = reason ?: it.reasonInput,
                adjustmentIncrease = adjustmentIncrease ?: it.adjustmentIncrease,
                validationError = null,
            )
        }
    }

    fun dismissAction() {
        _state.update {
            it.copy(
                activeAction = null,
                amountInput = "",
                reasonInput = "",
                validationError = null,
                isSubmitting = false,
                repaymentToVoidPublicId = null,
            )
        }
    }

    fun submit() {
        val current = _state.value
        if (!current.canModify) return
        val debt = current.debt ?: return
        val action = current.activeAction ?: return
        val repaymentToVoidPublicId = current.repaymentToVoidPublicId
        if (action == DebtAction.RepaymentVoid && repaymentToVoidPublicId == null) return
        // Exact minor-unit parsing uses the debt's frozen home currency. The input is
        // a positive magnitude; adjustment direction is carried by the explicit toggle.
        val amountCents = parseAmountCents(
            current.amountInput,
            CurrencyCode.requireSupported(debt.homeCurrencyCode),
        )
        val reason = current.reasonInput.trim()
        validateDebtAction(action, amountCents, reason)?.let { errorRes ->
            _state.update { it.copy(validationError = UiText.res(errorRes)) }
            return
        }
        _state.update { it.copy(isSubmitting = true) }
        val magnitude = amountCents ?: 0L
        val command = DebtMutationCommand(
            action = action,
            amountCents = magnitude,
            reason = reason,
            adjustmentIncrease = current.adjustmentIncrease,
            repaymentToVoidPublicId = repaymentToVoidPublicId,
        )
        viewModelScope.launch {
            val result = executeDebtMutation(repository, debt, command)
            result.fold(
                onSuccess = { mutation ->
                    // Supersede any in-flight refresh so its stale fold can't revert this committed
                    // write (which would make the next write's OCC carrier stale → a 409).
                    val mutationGeneration = ++loadGeneration
                    val updated = mutation.debt
                    val changesRepaymentHistory = action.changesRepaymentHistory()
                    detectSettleCelebration(updated, previousStatusByPublicId, celebratedDebtIds)
                        ?.let { _celebration.value = it }
                    _state.update {
                        it.afterSuccessfulMutation(
                            updatedDebt = updated,
                            action = action,
                            reloadRepaymentHistory = changesRepaymentHistory,
                        )
                    }
                    if (changesRepaymentHistory) {
                        val historyResult = repository.listRepaymentFacts(
                            updated.publicId,
                            REPAYMENT_HISTORY_FIRST_PAGE,
                        )
                        if (mutationGeneration == loadGeneration && loadedPublicId == updated.publicId) {
                            _state.update { it.withRepaymentHistory(historyResult) }
                        }
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isSubmitting = false, validationError = err.toUiText(R.string.debt_action_failed))
                    }
                },
            )
        }
    }

    /**
     * 8e-6e：把当前外部债重分类为 [kind]（POST /api/debts/{id}/kind，带 §2.1 OCC 载体 + ADR-0042 幂等键）。
     * 选中当前类型是 no-op（不发请求，避免无谓 row_version bump）。成功后用服务端折叠后的 [Debt]（新
     * row_version + debt_kind）原子换入并 bump loadGeneration——压制在途 refresh 的旧快照回退（否则下一次
     * 写的 OCC 载体会变陈 → 409），与 [submit] 同构。失败走既有 [DebtDetailUiState.error] 横幅。选择器抽屉
     * 的开合是详情屏的本地 UI 态（镜像新建抽屉），故本 VM 只负责提交这一步。
     */
    fun selectKind(kind: String) {
        val debt = _state.value.debt ?: return
        if (kind == debt.debtKind) return
        viewModelScope.launch {
            repository.setDebtKind(debt.publicId, debt.rowVersion, kind).fold(
                onSuccess = { updated ->
                    loadGeneration++
                    _state.update {
                        it.copy(debt = updated, error = null, flashMessage = UiText.res(R.string.debt_kind_updated))
                    }
                },
                onFailure = { err ->
                    _state.update { it.copy(error = err.toUiText(R.string.debt_action_failed)) }
                },
            )
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    /** Ack the 两清 celebration once the overlay has played (ADR-0049 §5.3). */
    fun consumeCelebration() {
        _celebration.value = null
    }
}

// §5.2 边沿检测（提到顶层让 DebtDetailViewModel 守住 detekt TooManyFunctions 阈值，逻辑不变）：crossedEdge
// （本 VM 内先见非-cleared、后变 cleared）= 在场目击两清，返回庆祝信号；否则 null。首次见已 cleared 的债
// prev=null → 不撒（P1#4）；!isForgiven → forgive 走 §5.6 暖语分叉不撒；viewerIsDebtor != null → 非当事方
// （fact 路径无 viewer 上下文 / 第三方成员）不撒；isMember → 外部债走会计框架不撒。每笔一次性（celebratedDebtIds）。
// 永远记录最新 status。两个传入的集合是 VM 的实例态，由调用方持有。
private fun detectSettleCelebration(
    newDebt: Debt,
    previousStatusByPublicId: MutableMap<String, String>,
    celebratedDebtIds: MutableSet<String>,
): DebtSettleCelebration? {
    val prev = previousStatusByPublicId[newDebt.publicId]
    val crossedEdge = prev != null && prev != DebtLinkStatuses.CLEARED && newDebt.isCleared
    val celebration = if (newDebt.isMember &&
        newDebt.viewerIsDebtor != null &&
        crossedEdge &&
        !newDebt.isForgiven &&
        !celebratedDebtIds.contains(newDebt.publicId)
    ) {
        celebratedDebtIds += newDebt.publicId
        DebtSettleCelebration(counterpartyLabel = newDebt.counterpartyLabel)
    } else {
        null
    }
    previousStatusByPublicId[newDebt.publicId] = newDebt.status
    return celebration
}

/** The validation copy for an invalid action input, or null when the inputs are acceptable. */
@StringRes
private fun validateDebtAction(action: DebtAction, amountCents: Long?, reason: String): Int? = when (action) {
    DebtAction.Repayment ->
        if (amountCents == null || amountCents <= 0L) R.string.debt_action_repayment_validation else null
    // The amount field is a positive magnitude (the sign comes from adjustmentIncrease), so an
    // empty/zero/negative magnitude or a blank reason is invalid.
    DebtAction.Adjustment ->
        if (amountCents == null || amountCents <= 0L || reason.isEmpty()) {
            R.string.debt_action_adjustment_validation
        } else {
            null
        }
    DebtAction.RepaymentVoid ->
        if (reason.isEmpty()) R.string.debt_action_repayment_void_validation else null
    DebtAction.Void -> if (reason.isEmpty()) R.string.debt_action_void_validation else null
}

@StringRes
private fun debtActionDoneRes(action: DebtAction): Int = when (action) {
    DebtAction.Repayment -> R.string.debt_action_repayment_done
    DebtAction.Adjustment -> R.string.debt_action_adjustment_done
    DebtAction.RepaymentVoid -> R.string.debt_action_repayment_void_done
    DebtAction.Void -> R.string.debt_action_void_done
}

private data class DebtMutationResult(val debt: Debt)

private data class DebtMutationCommand(
    val action: DebtAction,
    val amountCents: Long,
    val reason: String,
    val adjustmentIncrease: Boolean,
    val repaymentToVoidPublicId: String?,
)

private suspend fun executeDebtMutation(
    repository: DebtDetailActions,
    debt: Debt,
    command: DebtMutationCommand,
): Result<DebtMutationResult> = when (command.action) {
    DebtAction.Repayment ->
        repository.recordRepayment(debt.publicId, debt.rowVersion, command.amountCents)
            .map { DebtMutationResult(debt = it.debt) }
    DebtAction.Adjustment ->
        repository.recordAdjustment(
            debt.publicId,
            debt.rowVersion,
            if (command.adjustmentIncrease) command.amountCents else -command.amountCents,
            command.reason,
        ).map { DebtMutationResult(debt = it) }
    DebtAction.RepaymentVoid ->
        repository.voidRepayment(
            publicId = debt.publicId,
            repaymentPublicId = checkNotNull(command.repaymentToVoidPublicId),
            expectedRowVersion = debt.rowVersion,
            reason = command.reason,
        ).map { DebtMutationResult(debt = it) }
    DebtAction.Void ->
        repository.voidDebt(debt.publicId, debt.rowVersion, command.reason)
            .map { DebtMutationResult(debt = it) }
}

private fun DebtAction.changesRepaymentHistory(): Boolean =
    this == DebtAction.Repayment || this == DebtAction.RepaymentVoid

private fun DebtDetailUiState.afterSuccessfulMutation(
    updatedDebt: Debt,
    action: DebtAction,
    reloadRepaymentHistory: Boolean,
): DebtDetailUiState = copy(
    debt = updatedDebt,
    activeAction = null,
    amountInput = "",
    reasonInput = "",
    isSubmitting = false,
    validationError = null,
    flashMessage = UiText.res(debtActionDoneRes(action)),
    repaymentHistory = if (reloadRepaymentHistory) null else repaymentHistory,
    isRepaymentHistoryLoading = reloadRepaymentHistory,
    repaymentHistoryError = null,
    isRepaymentHistoryLoadingMore = false,
    repaymentHistoryLoadMoreError = null,
    repaymentToVoidPublicId = null,
)

private fun DebtDetailUiState.withRepaymentHistory(
    result: Result<DebtRepaymentHistory>,
): DebtDetailUiState = result.fold(
    onSuccess = { history ->
        copy(
            repaymentHistory = history,
            isRepaymentHistoryLoading = false,
            repaymentHistoryError = null,
            isRepaymentHistoryLoadingMore = false,
            repaymentHistoryLoadMoreError = null,
        )
    },
    onFailure = { error ->
        copy(
            isRepaymentHistoryLoading = false,
            repaymentHistoryError = error.toUiText(R.string.debt_repayment_history_load_failed),
            isRepaymentHistoryLoadingMore = false,
            repaymentHistoryLoadMoreError = null,
        )
    },
)

private fun DebtDetailUiState.withNextRepaymentHistoryPage(
    result: Result<DebtRepaymentHistory>,
    expectedDebtPublicId: String,
    expectedPage: Int,
): DebtDetailUiState = result.fold(
    onSuccess = { next ->
        val current = repaymentHistory
        if (current == null ||
            next.debtPublicId != expectedDebtPublicId ||
            next.debtPublicId != current.debtPublicId ||
            next.page != expectedPage
        ) {
            copy(
                isRepaymentHistoryLoadingMore = false,
                repaymentHistoryLoadMoreError = UiText.res(
                    R.string.debt_repayment_history_load_more_failed,
                ),
            )
        } else {
            val seenPublicIds = current.items.mapTo(mutableSetOf()) { it.publicId }
            val newItems = next.items.filter { seenPublicIds.add(it.publicId) }
            copy(
                repaymentHistory = current.copy(
                    items = current.items + newItems,
                    page = next.page,
                    pageSize = next.pageSize,
                    total = next.total,
                ),
                isRepaymentHistoryLoadingMore = false,
                repaymentHistoryLoadMoreError = null,
            )
        }
    },
    onFailure = { error ->
        copy(
            isRepaymentHistoryLoadingMore = false,
            repaymentHistoryLoadMoreError = error.toUiText(
                R.string.debt_repayment_history_load_more_failed,
            ),
        )
    },
)

private const val REPAYMENT_HISTORY_FIRST_PAGE = 1
