package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.PendingDebtAdjustment
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.UiText

/**
 * 欠款详情与 external/manual 事实动作：记还款、调整本金、作废欠款或作废一笔还款。
 * 同一个动作面板与提交 owner 持有目标和草稿。每次命令携带已读取的 parent Debt rowVersion，
 * 已确认命令换入服务端 Debt；调整先保留原意图，确认同步后重读。成员/拆账仍走对方确认流程。
 */
data class DebtDetailUiState(
    val binding: LogicalSessionBinding? = null,
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
    val adjustmentSnapshotLoaded: Boolean = false,
    val locallyAcceptedAdjustmentId: Long? = null,
    /** Original OCC of a confirmed adjustment whose newer canonical fold has not been installed. */
    val adjustmentRefreshAfterVersion: Long? = null,
    /** A local stop allows the same RV, but only after a post-observation canonical read. */
    val adjustmentRefreshAtVersion: Long? = null,
) {
    val canWriteActions: Boolean
        get() = canModify && debt != null && !isSubmitting && adjustmentSnapshotLoaded &&
            pendingAdjustments.none { it.isUnresolved } && locallyAcceptedAdjustmentId == null &&
            adjustmentRefreshAfterVersion == null && adjustmentRefreshAtVersion == null

    val adjustmentWriteMessage: UiText?
        get() = when {
            adjustmentRefreshAfterVersion != null || adjustmentRefreshAtVersion != null ->
                UiText.res(R.string.debt_adjustment_refresh_required)
            pendingAdjustments.any { it.isUnresolved } || locallyAcceptedAdjustmentId != null ->
                UiText.res(R.string.debt_adjustment_write_waiting)
            !adjustmentSnapshotLoaded && debt != null -> UiText.res(R.string.debt_adjustment_checking)
            else -> null
        }

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

/** Updates the existing detail projection; Room rows remain the command authority. */
internal fun DebtDetailUiState.withAdjustmentRows(
    rows: List<PendingDebtAdjustment>,
    newlyTerminal: Boolean,
    initial: Boolean,
): DebtDetailUiState {
    val confirmedVersion = rows.filter { it.row.status == PendingMutationStatus.Done }
        .mapNotNull { it.row.expectedRowVersion }.maxOrNull()
    val stoppedVersion = rows.filter { it.row.status == PendingMutationStatus.Abandoned }
        .mapNotNull { it.row.expectedRowVersion }.maxOrNull()
    val needsRefresh = newlyTerminal || confirmedVersion != null && (debt?.rowVersion ?: 0) <= confirmedVersion
    return copy(
        pendingAdjustments = rows.filter { it.row.status != PendingMutationStatus.Done },
        adjustmentSnapshotLoaded = true,
        locallyAcceptedAdjustmentId = locallyAcceptedAdjustmentId?.takeUnless { id -> rows.any { it.row.id == id } },
        adjustmentRefreshAfterVersion = if (needsRefresh && confirmedVersion != null) maxOf(adjustmentRefreshAfterVersion ?: 0, confirmedVersion)
            else adjustmentRefreshAfterVersion,
        adjustmentRefreshAtVersion = if (initial || newlyTerminal) maxOf(adjustmentRefreshAtVersion ?: 0, stoppedVersion ?: 0)
            else adjustmentRefreshAtVersion,
    )
}
