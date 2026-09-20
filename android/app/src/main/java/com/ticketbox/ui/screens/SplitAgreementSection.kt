package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SplitAgreementUiState
import com.ticketbox.viewmodel.SplitAgreementViewModel

@Composable
internal fun SplitAgreementSection(
    state: SplitAgreementUiState,
    model: SplitAgreementViewModel,
    onOpenDebt: (String) -> Unit,
) {
    AppSectionGroup {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            Text("拆账约定与结算", style = MaterialTheme.typography.titleMedium)
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            state.message?.let { Text(it) }
            if (state.loading) Text("正在核对双方约定…")
            QuietOutlinedButton(text = "重新核对约定", onClick = model::refresh, enabled = !state.loading)
            state.agreement?.let { agreement ->
                val display = CurrencyDisplay.forRecord(agreement.homeCurrencyCode)
                SplitAgreementFacts(state, display, onOpenDebt)
                if (agreement.viewerIsParty) {
                    SplitAgreementProposal(state, model, display)
                }
            }
            SplitAgreementSubmissions(state, model)
        }
    }
}

@Composable
private fun SplitAgreementForm(state: SplitAgreementUiState, model: SplitAgreementViewModel, display: CurrencyDisplay) {
    val agreement = state.agreement ?: return
    AppTextInput(AppTextInputState("新约定份额（${agreement.homeCurrencyCode}）", state.shareInput, enabled = !state.busy),
        AppTextInputActions(model::editShare))
    QuietOutlinedButton(text = "预览新份额的结算", onClick = model::refresh, enabled = !state.busy && !state.loading)
    if (state.previewReady) {
        if (agreement.preview.requiresExplicitSettlement) {
            Text("已有免除或特别结算约定：默认保留当前待结算，请双方明确确认。参考值不自动恢复已免除金额。")
        }
        agreement.preview.cashBasedSettlementNetAmountCents?.let {
            Text("按实际付款计算的参考：${splitSettlementLabel(it, display)}")
        }
        AppTextInput(AppTextInputState("最终待结算（正数由原接收方付，负数由原发送方返）", state.settlementInput,
            enabled = !state.busy), AppTextInputActions(model::editSettlement))
        AppTextInput(AppTextInputState("原因", state.reason, enabled = !state.busy, singleLine = false),
            AppTextInputActions(model::editReason))
        SplitSettlementConfirmation(state, model)
        QuietOutlinedButton(text = "提出新约定", onClick = model::propose, enabled = state.canPropose)
    }
}

@Composable
private fun SplitSettlementConfirmation(state: SplitAgreementUiState, model: SplitAgreementViewModel) {
    Row {
        Checkbox(checked = state.confirmed, onCheckedChange = model::confirm, enabled = !state.busy && !state.loading)
        Text("我已核对份额、已付／已返与免除，并确认本次结算方向和金额。")
    }
}

internal fun splitSettlementLabel(amount: Long, display: CurrencyDisplay): String = when {
    amount > 0 -> "原接收方仍需付 ${formatDisplayAmount(amount, display)}"
    amount < 0 -> "原发送方需返 ${formatDisplayAmount(-amount, display)}"
    else -> "无需再付或返"
}

@Composable
private fun SplitAgreementFacts(state: SplitAgreementUiState, display: CurrencyDisplay, onOpenDebt: (String) -> Unit) {
    val agreement = state.agreement ?: return
    Text("原份额 ${formatDisplayAmount(agreement.originalShareAmountCents, display)} · 当前约定 ${formatDisplayAmount(agreement.agreedShareAmountCents, display)}")
    Text("原接收方已付 ${formatDisplayAmount(agreement.originalPaidAmountCents, display)} · 原发送方已返 ${formatDisplayAmount(agreement.returnPaidAmountCents, display)}")
    Text("原往来已免除 ${formatDisplayAmount(agreement.originalForgivenAmountCents, display)} · 返还已免除 ${formatDisplayAmount(agreement.returnForgivenAmountCents, display)}")
    Text("当前结算：${splitSettlementLabel(agreement.settlementNetAmountCents, display)}")
    Text("新约定不修改双方私有流水；商家退款与双方实际返款分别核对。")
    if (agreement.originalDebt.publicId != state.task?.debtPublicId) {
        QuietOutlinedButton(text = "查看原往来与还款", onClick = { onOpenDebt(agreement.originalDebt.publicId) })
    }
    agreement.returnDebt?.takeIf { it.publicId != state.task?.debtPublicId }?.let { debt ->
        QuietOutlinedButton(text = "查看返还、还款与免除", onClick = { onOpenDebt(debt.publicId) })
    }
    if (agreement.pendingRepaymentDebtPublicIds.isNotEmpty()) {
        Text("双方还有待核对的还款。请先处理申报，再核对本次结算；输入会保留。")
        agreement.pendingRepaymentDebtPublicIds.forEach { id ->
            if (id == state.task?.debtPublicId) Text("本笔待核对申报见下方还款区。")
            else QuietOutlinedButton(text = "处理${if (id == agreement.originalDebt.publicId) "原往来" else "返还往来"}的申报",
                onClick = { onOpenDebt(id) })
        }
    }
}

@Composable
private fun SplitAgreementProposal(state: SplitAgreementUiState, model: SplitAgreementViewModel, display: CurrencyDisplay) {
    val agreement = state.agreement ?: return
    agreement.pendingProposal?.let { proposal ->
        Text("${if (proposal.proposedByYou) "你提出的" else "对方提出的"}新约定：${formatDisplayAmount(proposal.newShareAmountCents, display)}")
        Text("约定后结算：${splitSettlementLabel(proposal.settlementNetAmountCents, display)}")
        Text(proposal.reason)
        if (!proposal.proposedByYou) {
            SplitSettlementConfirmation(state, model)
            QuietOutlinedButton(text = "接受新约定", onClick = { model.resolve(true) },
                enabled = !state.busy && !state.loading && state.previewReady && state.confirmed &&
                    agreement.pendingRepaymentDebtPublicIds.isEmpty())
        }
        QuietOutlinedButton(text = if (proposal.proposedByYou) "撤回提议" else "拒绝提议",
            onClick = { model.resolve(false) }, enabled = !state.busy && !state.loading)
    } ?: SplitAgreementForm(state, model, display)
}

@Composable
private fun SplitAgreementSubmissions(state: SplitAgreementUiState, model: SplitAgreementViewModel) {
    state.rows.filter { it.status != PendingMutationStatus.Done }.forEach { row ->
        state.intents[row.id]?.create?.let { submitted ->
            Text("原提交原因：${submitted.reason}")
            state.agreement?.homeCurrencyCode?.let { currency ->
                val display = CurrencyDisplay.forRecord(currency)
                Text("原提交份额 ${formatDisplayAmount(submitted.newShareAmountCents, display)} · ${splitSettlementLabel(submitted.settlementNetAmountCents, display)}")
            }
        }
        if (row.lastError in com.ticketbox.data.repository.SPLIT_SHARE_REFUSALS) {
            Text("新份额超出原单可分摊金额。结束本地提交后重新拟定份额；对方提议可拒绝后再商议。")
        }
        Text(when (row.status) {
            PendingMutationStatus.Conflict -> "原提交与最新事实冲突。结束这次本地提交后，可保留草稿重新核对。"
            PendingMutationStatus.Failed -> "原提交需要核对。结束本地提交会保留当前草稿。"
            else -> "原提交等待同步，请勿重复发起。"
        })
        if (row.status == PendingMutationStatus.Failed && row.lastError !in com.ticketbox.data.repository.SPLIT_SHARE_REFUSALS) {
            QuietOutlinedButton(text = "重试原提交", onClick = { model.recover(row, false) })
        }
        if (row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
            QuietOutlinedButton(text = "结束这次本地提交", onClick = { model.recover(row, true) })
        }
    }
}
