package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing

/**
 * ADR-0049 §B 完整 installment 的 Android UI（**仅外部 installment 债**）：① 新建外部债选「分期还款」后才显示的
 * 可选期数输入；② 详情屏的分期计划卡（合约还清日 / 已还期数进度 / 每期无息估算）。两者都自守渲染条件，让
 * DebtListScreen / DebtDetailScreen 各只多一行调用、不撑过 detekt LongMethod 门。
 *
 * 红线：还清日是**合约确定值**（建账 + 期数×周期，后端 `installment_payoff_date`），措辞「按分期合约……」与
 * /web KPI 行一致（[[feedback_three_surface_visual_sync]]），不带速率「前后」语气；每期金额是**无息估算**（本金÷期数），
 * 明确标「估算不含手续费」。**完成措辞绝不基于「已还期数==总期数」**——提额调整会让已还期数达到 N/N 而剩余仍 > 0
 * （后端 installment_paid_count docstring），卡片只显示中性进度，「已还清」由 [Debt.isCleared] 在别处决定。
 */

/**
 * 每期本金估算（分）：本金 ÷ 期数 的整数 **floor**（非四舍五入），镜像后端 `per_period = principal // count`
 * （backend/app/services/debt_service/_installment.py）。这是标注「估算不含手续费」的无息估算，改一处口径
 * 必同步另一处。count≤0 → 0（防御除零，实际不会发生——已排期债 count ≥ 1）。
 */
internal fun installmentPerPeriodCents(principalCents: Long, count: Long): Long =
    if (count <= 0L) 0L else principalCents / count

/**
 * 详情屏是否显示分期计划卡：**进行中**（[Debt.isOpen]）且**已排期**（[Debt.isInstallmentScheduled]）的 installment
 * 外部债才显示。这是红线 R1（提额 adjustment 让已还期数达 N/N 而剩余仍 >0）的兜底之一：已结清/作废债把整张卡移除，
 * 不会在「已早还清」的债上显示一个未来的合约还清日 + N/N 进度这种矛盾画面（完成措辞由 [Debt.isCleared] 在别处决定）。
 */
internal fun shouldShowInstallmentCard(debt: Debt): Boolean = debt.isOpen && debt.isInstallmentScheduled

/**
 * 分期进度对（已还期数 clamp 到 [0, 总期数], 总期数）：纯中性进度，**绝不**含「完成/已还清」判定。clamp 是防御
 * （后端已 `min(paid//per, count)`，但 UI 不再二次越界显示「已还 13/12 期」）。**红线 R1**：即便 paidCount==count
 * （提额情形）这里也只返回 `(count, count)` 这个中性对，不进入任何完成分支——「已还清」永远由 [Debt.isCleared] 决定。
 */
internal fun installmentProgressPair(paidCount: Long?, count: Long): Pair<Long, Long> =
    (paidCount ?: 0L).coerceIn(0L, count) to count

/**
 * 新建外部债表单的「分期期数（可选）」字段：仅在 [kind] 为 installment 时渲染（自带前置 Spacer，故 DebtDraftForm
 * 只多一行调用）。期数原文回 [onValueChange]，范围/解析由 DebtDraftUi.parsedInstallmentCount 收口。
 */
@Composable
internal fun DebtInstallmentCountField(kind: String, countInput: String, onValueChange: (String) -> Unit) {
    if (kind != DebtKinds.INSTALLMENT) return
    Spacer(Modifier.size(AppSpacing.compactGap))
    OutlinedTextField(
        value = countInput,
        onValueChange = onValueChange,
        label = { Text(stringResource(R.string.debt_create_label_installment_count)) },
        supportingText = { Text(stringResource(R.string.debt_create_installment_count_hint)) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = Modifier.fillMaxWidth(),
    )
}

/**
 * 详情屏的分期计划卡 item：仅对**进行中且已排期**的 installment 外部债渲染（[Debt.isInstallmentScheduled]）。
 * 已结清 / 作废债不显示（合约还清日对已早还清的债是未来值，显示会矛盾；状态以摘要卡的状态徽章为准）。
 */
fun LazyListScope.debtInstallmentItem(debt: Debt, currency: CurrencyDisplay) {
    if (!shouldShowInstallmentCard(debt)) return
    item { DebtInstallmentCard(debt = debt, currency = currency) }
}

@Composable
private fun DebtInstallmentCard(debt: Debt, currency: CurrencyDisplay) {
    val count = debt.installmentCount ?: return
    val period = debt.installmentPeriodMonths
    val (paidPeriods, totalPeriods) = installmentProgressPair(debt.installmentPaidCount, count)
    val scheduleText = if (period == null || period == 1L) {
        stringResource(R.string.debt_installment_schedule_monthly, count)
    } else {
        stringResource(R.string.debt_installment_schedule_periodic, count, period)
    }
    val payoff = debt.installmentPayoffDate?.let { parsePayoffYearMonth(it) }
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
            Text(
                stringResource(R.string.debt_installment_card_title),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.size(AppSpacing.miniGap))
            Text(scheduleText, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(R.string.debt_installment_progress, paidPeriods, totalPeriods),
                style = MaterialTheme.typography.bodyMedium,
            )
            payoff?.let { (year, month) ->
                Spacer(Modifier.size(AppSpacing.smallGap))
                Text(
                    stringResource(R.string.debt_installment_payoff, year, month),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(
                    R.string.debt_installment_per_period,
                    formatDisplayAmount(installmentPerPeriodCents(debt.principalAmountCents, count), currency),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
