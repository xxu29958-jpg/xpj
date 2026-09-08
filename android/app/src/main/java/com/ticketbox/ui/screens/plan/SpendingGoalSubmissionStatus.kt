package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.viewmodel.SpendingGoalDetailUiState
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel

@Composable
internal fun SpendingGoalSubmissionStatus(state: SpendingGoalDetailUiState, viewModel: SpendingGoalDetailViewModel) {
    val active = state.pendingEdits.filter { !it.isDone }
    val shown = active.ifEmpty { listOfNotNull(state.pendingEdits.maxByOrNull { it.row.id }) }
    shown.forEach { pending ->
        AppContentCard {
            val text = pending.submissionText()
            AppStatusBanner(UiText.raw(text), if (pending.isDone) MessageTone.Success else MessageTone.Info)
            pending.request?.let { request ->
                request.name?.let { Text(it) }
                request.targetAmountCents?.let { amount ->
                    Text("提交的限额：" + formatDisplayAmount(amount,
                        CurrencyDisplay.forRecord(state.ledgerCurrency?.storageKey ?: "币种未确认")))
                }
                request.month?.let { Text("目标月份：$it") }
            }
            Row {
                if (pending.canRetry && state.canModify) TextButton(enabled = !state.isSaving,
                    onClick = { viewModel.recover(pending, drop = false) }) { Text("重试原提交") }
                if (pending.canDrop) TextButton(enabled = !state.isSaving,
                    onClick = { viewModel.recover(pending, drop = true) }) { Text("撤下本地修改") }
            }
        }
    }
}

private fun com.ticketbox.data.repository.PendingGoalEdit.submissionText(): String = when (row.status) {
    PendingMutationStatus.Pending -> "修改已保存在本机，等待同步；下方仍是已确认的进度。"
    PendingMutationStatus.InFlight -> "正在确认原提交，可以离开后再回来查看。"
    PendingMutationStatus.Conflict -> "目标已在别处修改。请刷新核对，撤下本地修改后重新编辑。"
    PendingMutationStatus.Failed -> if (canRetry) "暂未确认修改结果，可以重试同一份原提交。"
        else "这份修改尚未完成，请核对目标和原提交；本地记录已保留。"
    PendingMutationStatus.Done -> "这份修改已由服务器确认。"
    else -> "请核对这份本地修改。"
}
