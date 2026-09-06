package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.DebtAdjustmentActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingDebtAdjustment
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 欠款详情与 external/manual 事实动作：记还款、调整本金、作废欠款或作废一笔还款。
 * 同一个动作面板与提交 owner 持有目标和草稿。每次命令携带已读取的 parent Debt rowVersion，
 * 已确认命令换入服务端 Debt；调整先保留原意图，确认同步后重读。成员/拆账仍走对方确认流程。
 */
data class DebtDetailUiState(
    val isLoading: Boolean = false,
    val debt: Debt? = null,
    val canModify: Boolean = true,
    val error: UiText? = null,
    val activeAction: DebtAction? = null,
    val repaymentToVoid: DebtRepayment? = null,
    val amountInput: String = "",
    val reasonInput: String = "",
    // Adjustment is a signed delta, but the decimal keyboard exposes no minus key, so the amount
    // field is a positive magnitude and this toggle carries the sign (true = raise `remaining`).
    val adjustmentIncrease: Boolean = true,
    val validationError: UiText? = null,
    val isSubmitting: Boolean = false,
    val flashMessage: UiText? = null,
    val pendingAdjustments: List<PendingDebtAdjustment> = emptyList(),
) {
    /**
     * 金额输入框的显示/解析同源币种：本笔欠款的服务端 `homeCurrencyCode`（JPY 零小数
     * 整数显示整数），未加载时落 display-home 兜底。显示侧（DebtActionForm 标签）与
     * 解析侧（[DebtDetailViewModel.submit]）都必须从这一条派生，禁止再读恒 Base 的
     * 环境 CurrencyDisplay（否则 JPY 欠款显示 ¥500.00 却按 JPY 实扣 500，见 PR#255 P1）。
     */
    val amountInputCurrency: CurrencyCode
        get() = debt?.let { CurrencyCode.fromStorageKey(it.homeCurrencyCode) } ?: FxContract.HomeCurrency

    /**
     * record 币种是否在客户端支持集外（PR#255 R7-2 / R10⑤）：true 时**金额动作**（还款/调整）
     * 禁用（DebtActionPanel 同条件门 + [DebtDetailViewModel.submit] fail-closed 双防）——
     * 未知码禁落 CNY 解析（零小数币种的 "1200" 会被放大成 120000 minor，100×）；
     * Void 不带金额解析，不在禁用面。
     */
    val currencyUnsupported: Boolean
        get() = debt?.let { CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode) == null } == true
}

/** Direct facts; single-payment void also requires the selected immutable repayment identity. */
enum class DebtAction { Repayment, Adjustment, Void, RepaymentVoid }

/**
 * A one-shot member-debt 两清 celebration signal (ADR-0049 §5.2 / slice 8e-4): the viewer witnessed a
 * member Debt cross open→cleared (non-forgiven) in this VM lifetime. [counterpartyLabel] picks the
 * named vs anonymous body copy. Presentation metadata only — never a financial truth.
 */
data class DebtSettleCelebration(val counterpartyLabel: String?)

class DebtDetailViewModel(
    private val repository: DebtActions,
    private val adjustments: DebtAdjustmentActions,
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
    private var loadedBinding: LogicalSessionBinding? = null
    private var adjustmentObservation: Job? = null
    private var completedAdjustments: Set<Long>? = null
    private val refreshedAdjustments = mutableSetOf<Long>()

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

    init {
        viewModelScope.launch {
            adjustments.observeActiveLedgerAccess().collect { access ->
                if (loadedBinding != null && loadedBinding != access?.binding) {
                    loadGeneration++
                    adjustmentObservation?.cancel()
                    loadedPublicId = null
                    loadedBinding = null
                    completedAdjustments = null
                    previousStatusByPublicId.clear()
                    celebratedDebtIds.clear()
                    _celebration.value = null
                    _state.value = DebtDetailUiState(canModify = false)
                } else {
                    _state.update { it.copy(canModify = repository.canModifyLedger() && access?.canModify == true) }
                }
            }
        }
    }

    fun loadDebt(publicId: String) {
        val previousPublicId = loadedPublicId
        val previousBinding = loadedBinding
        loadedPublicId = publicId
        loadedBinding = adjustments.currentAccess()?.binding
        adjustmentObservation?.cancel()
        completedAdjustments = null
        refreshedAdjustments.clear()
        _state.update { it.copy(pendingAdjustments = emptyList()) }
        loadedBinding?.let { binding ->
            adjustmentObservation = viewModelScope.launch {
                adjustments.observeAdjustments(binding, publicId).collect { rows ->
                    if (loadedBinding != binding || loadedPublicId != publicId) return@collect
                    val done = rows.filter { it.row.status == PendingMutationStatus.Done }.mapTo(mutableSetOf()) { it.row.id }
                    val newlyDone = completedAdjustments?.let { done - it }.orEmpty()
                    completedAdjustments = done
                    _state.update { it.copy(pendingAdjustments = rows.filter { row -> row.row.status != PendingMutationStatus.Done }) }
                    if (newlyDone.isNotEmpty()) { refreshedAdjustments += newlyDone; refresh() }
                }
            }
        }
        if (previousPublicId != publicId || previousBinding != loadedBinding) {
            _state.update {
                it.copy(
                    debt = null,
                    error = null,
                    activeAction = null,
                    repaymentToVoid = null,
                    amountInput = "",
                    reasonInput = "",
                    adjustmentIncrease = true,
                    validationError = null,
                    isSubmitting = false,
                    flashMessage = null,
                )
            }
        }
        refresh()
    }

    fun refresh() {
        val publicId = loadedPublicId ?: return
        val binding = loadedBinding ?: return
        val gen = ++loadGeneration
        latestRefreshGeneration = gen
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.getDebt(publicId)
            // Drop a load superseded by a newer load or a committed write — before celebration
            // detection (a discarded snapshot must not record a status edge). Clear our loading flag
            // only when no newer refresh now owns it (a non-refresh superseder — submit — would
            // otherwise leave the screen stuck loading).
            if (gen != loadGeneration || adjustments.currentAccess()?.binding != binding) {
                if (gen == latestRefreshGeneration) {
                    _state.update { it.copy(isLoading = false) }
                }
                return@launch
            }
            result.fold(
                onSuccess = { debt ->
                    detectSettleCelebration(debt, previousStatusByPublicId, celebratedDebtIds)
                        ?.let { _celebration.value = it }
                    _state.update {
                        it.copy(
                            isLoading = false,
                            debt = debt,
                            canModify = repository.canModifyLedger() && adjustments.currentAccess()?.canModify == true,
                            error = null,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isLoading = false, error = err.toUiText(R.string.debt_detail_load_failed))
                    }
                },
            )
        }
    }

    fun openAction(action: DebtAction, repayment: DebtRepayment? = null) {
        val current = _state.value
        if (current.isSubmitting) return
        if (action == DebtAction.Adjustment && current.pendingAdjustments.isNotEmpty()) return
        if (action == DebtAction.RepaymentVoid) {
            val debt = current.debt ?: return
            if (!current.canModify || !debt.isDirectWritable || debt.isVoided || repayment?.isActive != true) return
        }
        _state.update {
            it.copy(
                activeAction = action,
                repaymentToVoid = repayment.takeIf { action == DebtAction.RepaymentVoid },
                amountInput = "",
                reasonInput = "",
                adjustmentIncrease = true,
                validationError = null,
            )
        }
    }

    fun updateActionInput(amount: String = state.value.amountInput, reason: String = state.value.reasonInput) {
        _state.update { it.copy(amountInput = amount, reasonInput = reason, validationError = null) }
    }

    fun setAdjustmentSign(increase: Boolean) {
        _state.update { it.copy(adjustmentIncrease = increase, validationError = null) }
    }

    fun dismissAction() {
        if (_state.value.isSubmitting) return
        _state.update {
            it.copy(
                activeAction = null,
                repaymentToVoid = null,
                amountInput = "",
                reasonInput = "",
                validationError = null,
                isSubmitting = false,
            )
        }
    }

    fun submit() {
        val (debt, action, input) = _state.value.actionSubmission() ?: return
        val binding = loadedBinding ?: return
        if (adjustments.currentAccess()?.binding != binding) return
        input.errorRes?.let { errorRes ->
            _state.update { it.copy(validationError = UiText.res(errorRes)) }
            return
        }
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result = if (action == DebtAction.Adjustment) {
                adjustments.save(binding, debt, requireNotNull(input.amountCents), input.reason)
                    .map { DebtActionOutcome.Queued(it) }
            } else repository.performAction(debt, action, input).map { DebtActionOutcome.Committed(it) }
            if (loadedPublicId != debt.publicId || loadedBinding != binding || adjustments.currentAccess()?.binding != binding) return@launch
            result.fold(
                onSuccess = { outcome ->
                    val updated = (outcome as? DebtActionOutcome.Committed)?.debt
                    // Supersede any in-flight refresh so its stale fold can't revert this committed
                    // write (which would make the next write's OCC carrier stale → a 409).
                    if (updated != null) {
                        loadGeneration++
                        detectSettleCelebration(updated, previousStatusByPublicId, celebratedDebtIds)
                            ?.let { _celebration.value = it }
                    }
                    _state.update { it.acceptAction(outcome, action) }
                    if (outcome is DebtActionOutcome.Queued && outcome.intentId in completedAdjustments.orEmpty() &&
                        refreshedAdjustments.add(outcome.intentId)) refresh()
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

    fun recoverAdjustment(pending: PendingDebtAdjustment, drop: Boolean) {
        val binding = loadedBinding ?: return
        viewModelScope.launch {
            adjustments.recover(binding, pending, drop).onFailure { error ->
                if (loadedBinding == binding) _state.update { it.copy(error = error.toUiText(R.string.debt_action_failed)) }
            }
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

private sealed interface DebtActionOutcome {
    data class Committed(val debt: Debt) : DebtActionOutcome
    data class Queued(val intentId: Long) : DebtActionOutcome
}

/** Validated target and parsed form for this submission, captured before asynchronous work. */
private data class DebtActionSubmission(val debt: Debt, val action: DebtAction, val input: DebtActionInput)

private fun DebtDetailUiState.actionSubmission(): DebtActionSubmission? {
    if (isSubmitting || !canModify) return null
    val target = debt ?: return null
    val action = activeAction ?: return null
    if (action == DebtAction.RepaymentVoid && repaymentToVoid == null) return null
    return DebtActionSubmission(target, action, actionInput(target, action))
}

private fun DebtDetailUiState.acceptAction(outcome: DebtActionOutcome, action: DebtAction): DebtDetailUiState = copy(
    debt = (outcome as? DebtActionOutcome.Committed)?.debt ?: debt,
    activeAction = null, repaymentToVoid = null, amountInput = "", reasonInput = "",
    isSubmitting = false, validationError = null,
    flashMessage = UiText.res(if (outcome is DebtActionOutcome.Queued) R.string.debt_adjustment_saved else debtActionDoneRes(action)),
)

/** Parsed input for one attempt, not a second draft or settlement owner. */
private data class DebtActionInput(
    val amountCents: Long?,
    val reason: String,
    val repaymentPublicId: String?,
    @param:StringRes val errorRes: Int?,
)

private fun DebtDetailUiState.actionInput(debt: Debt, action: DebtAction): DebtActionInput {
    val currency = CurrencyCode.fromStorageKeyOrNull(debt.homeCurrencyCode)
    val magnitude = currency?.let { parseAmountCents(amountInput, it) }
    val reason = reasonInput.trim()
    // Only amount commands require a supported currency; voids carry identity, OCC and reason.
    val error = if ((action == DebtAction.Repayment || action == DebtAction.Adjustment) && currency == null) {
        R.string.debt_action_currency_unsupported
    } else {
        validateDebtAction(action, magnitude, reason)
    }
    return DebtActionInput(
        amountCents = if (action == DebtAction.Adjustment && !adjustmentIncrease) magnitude?.unaryMinus() else magnitude,
        reason = reason,
        repaymentPublicId = repaymentToVoid?.publicId,
        errorRes = error,
    )
}

private suspend fun DebtActions.performAction(debt: Debt, action: DebtAction, input: DebtActionInput): Result<Debt> =
    when (action) {
        DebtAction.Repayment -> recordRepayment(debt.publicId, debt.rowVersion, requireNotNull(input.amountCents))
        DebtAction.Adjustment -> error("Adjustment publishes through its durable command owner")
        DebtAction.Void -> voidDebt(debt.publicId, debt.rowVersion, input.reason)
        DebtAction.RepaymentVoid -> voidRepayment(
            debt.publicId, requireNotNull(input.repaymentPublicId), debt.rowVersion, input.reason,
        )
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
    DebtAction.Void, DebtAction.RepaymentVoid -> if (reason.isEmpty()) R.string.debt_action_void_validation else null
}

@StringRes
private fun debtActionDoneRes(action: DebtAction): Int = when (action) {
    DebtAction.Repayment -> R.string.debt_action_repayment_done
    DebtAction.Adjustment -> R.string.debt_action_adjustment_done
    DebtAction.Void -> R.string.debt_action_void_done
    DebtAction.RepaymentVoid -> R.string.debt_action_repayment_void_done
}
