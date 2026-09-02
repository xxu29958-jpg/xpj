package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayDate
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.viewmodel.DebtRepaymentHistoryUiState

/**
 * 单笔还款作废入口的展示资格（纯呈现规则，镜像服务端 guard_direct_fact_writable）：
 * 仅 external+manual 欠款、可写角色、整笔未作废（整笔 voided 是 terminal，服务端对后续
 * fact 一律 debt_already_voided）、该笔还款仍 active 时才出现；member/bill_split 的历史
 * 永远只读。已两清(cleared)不拦——作废一笔后服务端会重开父欠款。
 */
internal fun repaymentVoidActionAllowed(debt: Debt, canModify: Boolean, repayment: DebtRepayment): Boolean =
    debt.isDirectWritable && canModify && debt.status != DebtLinkStatuses.VOIDED && repayment.isActive

/**
 * 还款记录段（只读历史 + 单笔作废入口）：分页一次一页（服务端只有 page/total，无 snapshot
 * cursor——不拼暗示同快照的假 timeline）；加载失败只在本段内提示+重试，不阻断上方的还款/调整
 * 命令。金额按父欠款本位币（响应信封 homeCurrencyCode）显示，原币字段仅作 raw 展示、不换算。
 */
@Composable
internal fun DebtRepaymentHistorySection(
    debt: Debt,
    canModify: Boolean,
    history: DebtRepaymentHistoryUiState,
    callbacks: DebtRepaymentHistoryCallbacks,
) {
    AppSectionGroup(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Text(
            text = stringResource(R.string.debt_repayment_history_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
        )
        history.error?.let { error ->
            AppStatusBanner(message = error, tone = MessageTone.Danger)
            QuietOutlinedButton(
                text = stringResource(R.string.common_retry),
                onClick = callbacks.onRetry,
            )
        }
        when {
            history.isLoading && history.items.isEmpty() -> Row(
                modifier = Modifier.fillMaxWidth().padding(vertical = AppSpacing.smallGap),
                horizontalArrangement = Arrangement.Center,
            ) {
                CircularProgressIndicator(modifier = Modifier.size(24.dp))
            }
            history.items.isEmpty() && history.error == null -> Text(
                text = stringResource(R.string.debt_repayment_history_empty),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            else -> history.items.forEachIndexed { index, repayment ->
                DebtRepaymentHistoryRow(
                    repayment = repayment,
                    homeCurrencyCode = history.homeCurrencyCode,
                    showDivider = index < history.items.lastIndex,
                    voidAllowed = repaymentVoidActionAllowed(debt, canModify, repayment),
                    onVoid = { callbacks.onVoidRepayment(repayment) },
                )
            }
        }
        DebtRepaymentHistoryPager(history = history, onLoadPage = callbacks.onLoadPage)
    }
}

@Composable
private fun DebtRepaymentHistoryRow(
    repayment: DebtRepayment,
    homeCurrencyCode: String?,
    showDivider: Boolean,
    voidAllowed: Boolean,
    onVoid: () -> Unit,
) {
    val recordDisplay = CurrencyDisplay.forRecord(homeCurrencyCode)
    AppListRow(settled = !repayment.isActive, showDivider = showDivider) {
        Column(modifier = Modifier.weight(1f)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                Text(
                    text = formatDisplayAmount(repayment.amountCents, recordDisplay),
                    style = MaterialTheme.typography.bodyLarge.tabularNum(),
                    fontWeight = FontWeight.Medium,
                )
                if (!repayment.isActive) {
                    DebtStatusBadge(
                        text = stringResource(R.string.debt_repayment_voided_badge),
                        tone = debtLinkStatusTone(DebtLinkStatuses.VOIDED),
                    )
                }
            }
            Text(
                text = displayDate(repayment.paidAt),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            repayment.originalAmountLine(homeCurrencyCode)?.let { originalLine ->
                Text(
                    text = originalLine,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            repayment.voidFact?.reason?.takeIf { it.isNotBlank() }?.let { reason ->
                Text(
                    text = stringResource(R.string.debt_repayment_voided_reason, reason),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (voidAllowed) {
            QuietOutlinedButton(text = stringResource(R.string.debt_repayment_void_action), onClick = onVoid)
        }
    }
}

/** 原币行：仅在原币与父欠款本位币不同且金额齐备时显示（raw 字段直显，不客户端换算）。 */
@Composable
private fun DebtRepayment.originalAmountLine(homeCurrencyCode: String?): String? {
    val originalCode = originalCurrencyCode ?: return null
    val originalMinor = originalAmountMinor ?: return null
    if (originalCode == homeCurrencyCode) return null
    return stringResource(
        R.string.debt_repayment_original_amount,
        formatDisplayAmount(originalMinor, CurrencyDisplay.forRecord(originalCode)),
    )
}

/** 分页 footer：仅在确有上一页/下一页时出现；一次一页，加载中禁用防重复请求。 */
@Composable
private fun DebtRepaymentHistoryPager(
    history: DebtRepaymentHistoryUiState,
    onLoadPage: (Int) -> Unit,
) {
    if (!history.hasPrevious && !history.hasNext) return
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        QuietOutlinedButton(
            text = stringResource(R.string.debt_repayment_history_newer),
            enabled = history.hasPrevious && !history.isLoading,
            onClick = { onLoadPage(history.page - 1) },
        )
        Text(
            text = stringResource(R.string.debt_repayment_history_total, history.total),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        QuietOutlinedButton(
            text = stringResource(R.string.debt_repayment_history_older),
            enabled = history.hasNext && !history.isLoading,
            onClick = { onLoadPage(history.page + 1) },
        )
    }
}

/** 单笔还款作废的选中还款只读摘要（金额 + 日期）；金额按 record raw code 显示（不走
 *  amountInputCurrency 枚举兜底——未知码只读展示不能被洗成 CNY）。 */
@Composable
internal fun DebtRepaymentVoidTarget(repayment: DebtRepayment, homeCurrencyCode: String?) {
    DebtSummaryRow(
        label = stringResource(R.string.debt_action_repayment_void_target_label),
        value = stringResource(
            R.string.debt_action_repayment_void_target_value,
            formatDisplayAmount(repayment.amountCents, CurrencyDisplay.forRecord(homeCurrencyCode)),
            displayDate(repayment.paidAt),
        ),
    )
}

/** 动作面板的后果提示：整笔作废与单笔还款作废各有自己的诚实文案，其余动作无警告。 */
@Composable
internal fun DebtActionWarning(action: DebtAction) {
    val warningRes = when (action) {
        DebtAction.Void -> R.string.debt_action_void_warning
        DebtAction.RepaymentVoid -> R.string.debt_action_repayment_void_warning
        else -> return
    }
    Text(stringResource(warningRes), style = MaterialTheme.typography.bodySmall, color = LocalStateTokens.current.warn.fg)
}
