package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.start
import com.ticketbox.viewmodel.voidPayment

internal val fundKinds = linkedMapOf("cash" to "现金", "bank" to "银行卡", "wallet" to "余额账户", "credit" to "信用账户")
internal val fundActions = mapOf("create" to "添加账户", "edit" to "编辑账户", "repay" to "记录还款",
    "void_repayment" to "撤销错误的还款",
    "income" to "记录实际收入", "loan" to "记录贷款到账", "transfer" to "账户间转账", "reconciliation" to "核对余额", "funding" to "付款来源", "installments" to "记录真实分期")
internal fun money(value: Long, currency: String) = formatDisplayAmount(value, CurrencyDisplay.forRecord(currency))
private fun FinancialAccountDto.balanceLabel(): String = when {
    balanceMinor == null -> "余额待核对"
    kind == "credit" && balanceMinor <= 0 -> "欠款 ${money(-balanceMinor, currencyCode)}"
    kind == "credit" -> "溢缴款 ${money(balanceMinor, currencyCode)}"
    else -> money(balanceMinor, currencyCode)
}

@Composable
fun FundsScreen(viewModel: FundsViewModel, onBack: () -> Unit, onExpense: (Long) -> Unit) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val input = state.task.input
    val detail = state.detail
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(AppPageRole.Ledger, if (state.editing) fundActions[input?.mode] ?: "资金任务"
            else if (state.fundingPage) "付款来源" else detail?.name ?: "资金账户", "现金、余额、银行卡与信用", "返回", { if (!viewModel.back()) onBack() }),
        refresh = AppSecondaryRefreshState(state.loading, viewModel::refresh),
    ) {
        state.error?.let { message -> item { Text(message, color = MaterialTheme.colorScheme.error) } }
        if (state.fromCache) item { Text("当前显示上次读取的账户；联网后刷新核对。", style = MaterialTheme.typography.bodySmall) }
        when {
            state.editing && input != null -> item { FundsEditor(state, input, viewModel) }
            state.fundingPage -> item { FundingReadPanel(state, viewModel) }
            detail != null -> accountDetail(state, detail, viewModel, onExpense)
            else -> accountsOverview(state, viewModel)
        }
    }
}

@Composable
private fun FundingReadPanel(state: FundsUiState, viewModel: FundsViewModel) {
    val input = state.task.input

    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text("补充或更正实际付款来源，不再新增消费。")
        state.funding?.let { source ->
            if (source.parts.isEmpty()) Text("付款方式未记录。")
            source.parts.forEach { part -> Text("${part.accountName} · 抵付 ${money(part.expenseAmountMinor, source.currencyCode)}" +
                if (part.includedInOpening) " · 已纳入期初" else "") }
            if (source.canEdit && state.access?.canModify == true) AppPrimaryButton(
                if (input != null) "继续原资金任务" else "核对付款来源") { viewModel.start("funding") }
        }
        if (input != null && state.funding?.canEdit != true) AppSecondaryButton("查看原资金任务", onClick = viewModel::resume)
    }

}

private fun LazyListScope.accountDetail(state: FundsUiState, detail: FinancialAccountDto, viewModel: FundsViewModel, onExpense: (Long) -> Unit) {

    item { AccountDetailHeader(state, detail, viewModel) }
    items(detail.movements, key = { it.publicId }) { row ->
        AppListRow(onClick = row.expenseId?.let { id -> { onExpense(id) } }) {
            Column(Modifier.weight(1f)) {
                Text(row.note); Text(row.occurredOn, style = MaterialTheme.typography.bodySmall)
                if (row.canVoidRepayment && row.repaymentPublicId != null && state.access?.canModify == true)
                    TextButton(onClick = { viewModel.voidPayment(row.repaymentPublicId) }) { Text("撤销错误的还款") }
            }
            Text(money(row.amountMinor, detail.currencyCode))
        }
    }

}

@Composable
private fun AccountDetailHeader(state: FundsUiState, detail: FinancialAccountDto, viewModel: FundsViewModel) {

    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(detail.balanceLabel(), style = MaterialTheme.typography.headlineMedium)
        Text("${fundKinds[detail.kind]} · ${if (detail.visibility == "private") "仅自己" else "账本共享"}" +
            (detail.tail?.let { " · 尾号 $it" } ?: ""))
        Text("期初 ${detail.openingDate} · ${detail.openingSource}", style = MaterialTheme.typography.bodySmall)
        detail.creditTerms?.let { FundsCreditTermsRead(it, detail.currencyCode) }
        if (detail.unallocatedCreditMinor > 0) Text("其中 ${money(detail.unallocatedCreditMinor, detail.currencyCode)} 是尚未指定到逐笔本金的退款或预付款。已计入账户余额，不表示其它购买或分期期次已经还清。")
        if (detail.balanceMinor == null) Text("已记录净变动 ${money(detail.recordedChangeMinor, detail.currencyCode)}，这不是可用余额。")
        detail.observation?.let { check -> Text("外部快照 ${check.occurredOn} · ${check.source}：${money(check.observedMinor, detail.currencyCode)}\n待解释差异 ${money(check.differenceMinor, detail.currencyCode)}") }
        AccountActions(state, detail, viewModel)
        Text("实际变动", style = MaterialTheme.typography.titleMedium)
    }

}

private fun LazyListScope.accountsOverview(state: FundsUiState, viewModel: FundsViewModel) {
    val input = state.task.input

    item {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            if (input != null) AppSecondaryButton("继续上次的资金任务", onClick = viewModel::resume)
            state.overview?.let { summary ->
                Text("已纳入账户净资产 ${money(summary.netWorthMinor, summary.homeCurrencyCode)}", style = MaterialTheme.typography.headlineSmall)
                Text("资产 ${money(summary.assetsMinor, summary.homeCurrencyCode)} · 负债 ${money(summary.liabilitiesMinor, summary.homeCurrencyCode)}")
                Text("${summary.valuationDate} 估值 · ${summary.includedAccounts} 个账户。${summary.unknownAccounts} 个余额待核对，${summary.missingRateAccounts} 个待补汇率，尚未计入。", style = MaterialTheme.typography.bodySmall)
            }
            if (state.access?.canModify == true) AppPrimaryButton("添加账户") { viewModel.start("create") }
            if (state.accounts.isEmpty() && !state.loading) Text("从一张常用的卡开始。期初填零表示已核对为零，留空表示尚未核对。")
        }
    }
    items(state.accounts, key = { it.publicId }) { account ->
        AppListRow(onClick = { viewModel.open(account.publicId) }) {
            Column(Modifier.weight(1f)) {
                Text(account.name + (account.tail?.let { " · $it" } ?: ""), style = MaterialTheme.typography.titleSmall)
                Text("${fundKinds[account.kind]} · ${if (account.visibility == "private") "仅自己" else "账本共享"}" +
                    if (account.archived) " · 已归档" else "", style = MaterialTheme.typography.bodySmall)
            }
            Text(account.balanceLabel())
        }
    }

}

@Composable
private fun AccountActions(state: FundsUiState, detail: FinancialAccountDto, viewModel: FundsViewModel) {
    if (detail.canEdit && state.access?.canModify == true) AppSecondaryButton("编辑账户") { viewModel.start("edit") }
    if (detail.kind == "credit" && !detail.archived && state.access?.canModify == true)
        AppPrimaryButton("记录实际还款") { viewModel.start("repay") }
    if (!detail.archived && state.access?.canModify == true) {
        if (detail.kind != "credit") listOf("income", "transfer", "loan").forEach { mode ->
            AppSecondaryButton(requireNotNull(fundActions[mode])) { viewModel.start(mode) }
        }
        if (detail.canEdit) AppSecondaryButton("核对余额") { viewModel.start("reconciliation") }
    }
    if (detail.kind == "credit") InstallmentHistory(state.installments, !detail.archived && state.access?.canModify == true, viewModel)
}
