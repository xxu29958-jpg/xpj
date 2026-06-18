package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0049 §3 (slice 8c) 欠款详情 + 记账管理 —— 进入欠款详情后记还款（§3.1）/ 调整本金（§3.3）/
 * 作废欠款（§3.5）。三类写都是直接提交事实（external/manual 欠款；成员/拆账欠款走 slice8d 的对方
 * 确认流程，后端 [guard_direct_fact_writable] 对其返回 409），均带 §2.1 OCC 载体
 * （[DebtDetailUiState.debt] 的 `rowVersion`）。提交成功后用服务端折叠后的 [Debt] 原子替换本地态，
 * 故下一次写自动用新的 `rowVersion`。
 *
 * 一个统一的动作面板（[activeAction]）承载三类写：还款只填金额、调整填金额+原因、作废只填原因，
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
)

/** The three direct fact writes a detail action panel can submit (ADR-0049 §3.1 / §3.3 / §3.5). */
enum class DebtAction { Repayment, Adjustment, Void }

/**
 * A one-shot member-debt 两清 celebration signal (ADR-0049 §5.2 / slice 8e-4): the viewer witnessed a
 * member Debt cross open→cleared (non-forgiven) in this VM lifetime. [counterpartyLabel] picks the
 * named vs anonymous body copy. Presentation metadata only — never a financial truth.
 */
data class DebtSettleCelebration(val counterpartyLabel: String?)

class DebtDetailViewModel(
    private val repository: DebtActions,
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
        loadedPublicId = publicId
        refresh()
    }

    fun refresh() {
        val publicId = loadedPublicId ?: return
        val gen = ++loadGeneration
        latestRefreshGeneration = gen
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.getDebt(publicId)
            // Drop a load superseded by a newer load or a committed write — before celebration
            // detection (a discarded snapshot must not record a status edge). Clear our loading flag
            // only when no newer refresh now owns it (a non-refresh superseder — submit — would
            // otherwise leave the screen stuck loading).
            if (gen != loadGeneration) {
                if (gen == latestRefreshGeneration) {
                    _state.update { it.copy(isLoading = false) }
                }
                return@launch
            }
            result.fold(
                onSuccess = { debt ->
                    detectSettleCelebration(debt)
                    _state.update {
                        it.copy(
                            isLoading = false,
                            debt = debt,
                            canModify = repository.canModifyLedger(),
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

    fun openAction(action: DebtAction) {
        _state.update {
            it.copy(
                activeAction = action,
                amountInput = "",
                reasonInput = "",
                adjustmentIncrease = true,
                validationError = null,
            )
        }
    }

    fun updateAmount(value: String) {
        _state.update { it.copy(amountInput = value, validationError = null) }
    }

    fun updateReason(value: String) {
        _state.update { it.copy(reasonInput = value, validationError = null) }
    }

    fun setAdjustmentSign(increase: Boolean) {
        _state.update { it.copy(adjustmentIncrease = increase, validationError = null) }
    }

    fun dismissAction() {
        _state.update {
            it.copy(
                activeAction = null,
                amountInput = "",
                reasonInput = "",
                validationError = null,
                isSubmitting = false,
            )
        }
    }

    fun submit() {
        val current = _state.value
        val debt = current.debt ?: return
        val action = current.activeAction ?: return
        // 元→分走共享 BigDecimal 解析器（§3 禁 Double 存金额）；sign-agnostic，>0 magnitude 由
        // validateDebtAction 按动作类型校验（调整的正负来自 adjustmentIncrease 开关）。
        val amountCents = parseAmountCents(current.amountInput)
        val reason = current.reasonInput.trim()
        validateDebtAction(action, amountCents, reason)?.let { errorRes ->
            _state.update { it.copy(validationError = UiText.res(errorRes)) }
            return
        }
        _state.update { it.copy(isSubmitting = true) }
        val magnitude = amountCents ?: 0L
        viewModelScope.launch {
            val result = when (action) {
                DebtAction.Repayment ->
                    repository.recordRepayment(debt.publicId, debt.rowVersion, magnitude)
                DebtAction.Adjustment ->
                    repository.recordAdjustment(
                        debt.publicId,
                        debt.rowVersion,
                        if (current.adjustmentIncrease) magnitude else -magnitude,
                        reason,
                    )
                DebtAction.Void ->
                    repository.voidDebt(debt.publicId, debt.rowVersion, reason)
            }
            result.fold(
                onSuccess = { updated ->
                    // Supersede any in-flight refresh so its stale fold can't revert this committed
                    // write (which would make the next write's OCC carrier stale → a 409).
                    loadGeneration++
                    detectSettleCelebration(updated)
                    _state.update {
                        it.copy(
                            debt = updated,
                            activeAction = null,
                            amountInput = "",
                            reasonInput = "",
                            isSubmitting = false,
                            validationError = null,
                            flashMessage = UiText.res(debtActionDoneRes(action)),
                        )
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

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    /** Ack the 两清 celebration once the overlay has played (ADR-0049 §5.3). */
    fun consumeCelebration() {
        _celebration.value = null
    }

    // §5.2 边沿检测：crossedEdge（本 VM 内先见非-cleared、后变 cleared）= 在场目击两清；首次见已 cleared
    // 的债 prev=null → 不撒花（P1#4）。!isForgiven → forgive 走 §5.6 暖语分叉不撒；viewerIsDebtor != null →
    // 非当事方（fact 路径无 viewer 上下文 / 第三方成员）不撒；isMember → 外部债走会计框架不撒。每笔一次性（celebratedDebtIds）。
    private fun detectSettleCelebration(newDebt: Debt) {
        val prev = previousStatusByPublicId[newDebt.publicId]
        val crossedEdge = prev != null && prev != DebtLinkStatuses.CLEARED && newDebt.isCleared
        if (newDebt.isMember &&
            newDebt.viewerIsDebtor != null &&
            crossedEdge &&
            !newDebt.isForgiven &&
            !celebratedDebtIds.contains(newDebt.publicId)
        ) {
            celebratedDebtIds += newDebt.publicId
            _celebration.value = DebtSettleCelebration(counterpartyLabel = newDebt.counterpartyLabel)
        }
        previousStatusByPublicId[newDebt.publicId] = newDebt.status
    }
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
    DebtAction.Void -> if (reason.isEmpty()) R.string.debt_action_void_validation else null
}

@StringRes
private fun debtActionDoneRes(action: DebtAction): Int = when (action) {
    DebtAction.Repayment -> R.string.debt_action_repayment_done
    DebtAction.Adjustment -> R.string.debt_action_adjustment_done
    DebtAction.Void -> R.string.debt_action_void_done
}
