package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.CurrencyChoiceField
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel

private val fundKinds = linkedMapOf("cash" to "现金", "bank" to "银行卡", "wallet" to "余额账户", "credit" to "信用账户")
private val fundActions = mapOf("create" to "添加账户", "edit" to "编辑账户", "repay" to "记录还款",
    "void_repayment" to "撤销错误的还款",
    "income" to "记录实际收入", "loan" to "记录贷款到账", "transfer" to "账户间转账", "reconciliation" to "核对余额", "funding" to "付款来源", "installments" to "记录真实分期")
private fun money(value: Long, currency: String) = formatDisplayAmount(value, CurrencyDisplay.forRecord(currency))
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
            state.fundingPage -> item {
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
            detail != null -> {
                item {
                    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                        Text(detail.balanceLabel(), style = MaterialTheme.typography.headlineMedium)
                        Text("${fundKinds[detail.kind]} · ${if (detail.visibility == "private") "仅自己" else "账本共享"}" +
                            (detail.tail?.let { " · 尾号 $it" } ?: ""))
                        Text("期初 ${detail.openingDate} · ${detail.openingSource}", style = MaterialTheme.typography.bodySmall)
                        detail.creditTerms?.let { FundsCreditTermsRead(it, detail.currencyCode) }
                        if (detail.unallocatedCreditMinor > 0) Text("其中 ${money(detail.unallocatedCreditMinor, detail.currencyCode)} 是尚未指定到逐笔本金的退款或预付款。已计入账户余额，不表示其它购买或分期期次已经还清。")
                        if (detail.balanceMinor == null) Text("已记录净变动 ${money(detail.recordedChangeMinor, detail.currencyCode)}，这不是可用余额。")
                        detail.observation?.let { check -> Text("外部快照 ${check.occurredOn} · ${check.source}：${money(check.observedMinor, detail.currencyCode)}\n待解释差异 ${money(check.differenceMinor, detail.currencyCode)}") }
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
                        Text("实际变动", style = MaterialTheme.typography.titleMedium)
                    }
                }
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
            else -> {
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
                            Text(account.name, style = MaterialTheme.typography.titleSmall)
                            Text("${fundKinds[account.kind]} · ${if (account.visibility == "private") "仅自己" else "账本共享"}" +
                                if (account.archived) " · 已归档" else "", style = MaterialTheme.typography.bodySmall)
                        }
                        Text(account.balanceLabel())
                    }
                }
            }
        }
    }
}

@Composable
private fun FundsEditor(state: FundsUiState, input: FundsInput, vm: FundsViewModel) {
    val enabled = !state.task.frozen && !state.busy && state.access?.canModify == true && state.access.binding == input.binding
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (input.binding != state.access?.binding) Text("这是原身份的输入。切回原身份后才能继续，内容仍保留。")
        when (input.mode) {
            "void_repayment" -> {
                Text("恢复原本金欠款、付款账户和分期未付金额，保留更正记录。已发生的费用仍保留；费用也记错或已退款时，从原费用消费办理更正或退款。")
                FundsField("撤销依据", input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
            }
            "funding" -> {
                CurrencyCode.fromStorageKeyOrNull(input.currency)?.let { currency ->
                    ExpenseFundingFields(input.fundingJson, currency, enabled) { value -> vm.edit { it.copy(fundingJson = value) } }
                }
                FundsField("本次核对依据", input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
            }
            "repay" -> {
                FundsPaymentFields(input, state.accounts, enabled, vm)
                InstallmentPaymentFields(input, state.installments, enabled, vm)
            }
            "installments" -> InstallmentFields(input, state.installments, enabled, vm)
            "create", "edit" -> {
                if (input.mode == "create") FundsAccountChoices(state.accountChoices, enabled, vm)
                FundsAccountFields(input, enabled, vm)
                if (input.kind == "credit") FundsCreditTermsFields(input, enabled, vm)
            }
            else -> FundsActivityFields(input, state.accounts, enabled, vm)
        }
        if (input.mode !in setOf("edit", "funding")) FundsField("${if (input.mode == "create") "期初日期" else "实际日期"}（YYYY-MM-DD）", input.date, enabled) { value -> vm.edit { it.copy(date = value) } }
        FundsSubmission(state, enabled, vm)
    }
}

@Composable
private fun FundsAccountFields(input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    FundsField("账户名称", input.name, enabled) { value -> vm.edit { it.copy(name = value) } }
    if (input.mode == "create") {
        androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            fundKinds.forEach { (kind, label) -> FilterChip(input.kind == kind, { vm.edit { it.copy(kind = kind) } }, { Text(label) }, enabled = enabled) }
        }
        CurrencyChoiceField(CurrencyCode.fromStorageKeyOrNull(input.currency), enabled, title = "选择账户实际币种") { value -> vm.edit { it.copy(currency = value.storageKey) } }
        Row { Switch(input.visibility == "ledger", { shared -> vm.edit { it.copy(visibility = if (shared) "ledger" else "private") } }, enabled = enabled)
            Text("允许当前账本成员查看和使用") }
        Text("默认仅自己可见。私人账户用于家庭消费时，不向其他成员公开余额。", style = MaterialTheme.typography.bodySmall)
        FundsField(if (input.kind == "credit") "期初欠款（${input.currency}）" else "期初余额（${input.currency}）", input.opening, enabled, money = true) { value -> vm.edit { it.copy(opening = value) } }
        Text("填 0 表示已核对为零；留空表示待核对。", style = MaterialTheme.typography.bodySmall)
        FundsField("期初依据", input.source, enabled) { value -> vm.edit { it.copy(source = value) } }
    } else Row {
        Switch(input.archived, { value -> vm.edit { it.copy(archived = value) } }, enabled = enabled)
        Text("归档账户，保留全部历史")
    }
    FundsField("银行或平台（选填）", input.institution, enabled) { value -> vm.edit { it.copy(institution = value) } }
    FundsField("尾号（选填，最多 4 位）", input.tail, enabled) { value -> vm.edit { it.copy(tail = value) } }
}

@Composable
private fun FundsPaymentFields(input: FundsInput, accounts: List<FinancialAccountDto>, enabled: Boolean, vm: FundsViewModel) {
    var choosing by rememberSaveable { mutableStateOf(false) }
    Text("记录 ${input.name} 的实际还款。本金不重复计消费；仅支付新费用时，两项本金填 0。")
    AppSecondaryButton(input.payerName.ifBlank { "选择实际扣款账户" }, enabled = enabled) { choosing = true }
    if (choosing) AlertDialog(onDismissRequest = { choosing = false }, title = { Text("实际扣款账户") },
        text = { androidx.compose.foundation.lazy.LazyColumn {
            items(accounts.filter { it.kind != "credit" && !it.archived }, key = { it.publicId }) { account ->
                TextButton(onClick = { vm.choosePayer(account); choosing = false }) { Text("${account.name} · ${account.currencyCode}") }
            }
        } }, confirmButton = { TextButton(onClick = { choosing = false }) { Text("返回") } })
    FundsField("清偿本金（${input.currency}）", input.principal, enabled, money = true) { value -> vm.edit {
        it.copy(principal = value, paid = if (it.currency == it.payerCurrency) value else it.paid)
    } }
    FundsField("本金实际扣款（${input.payerCurrency.ifBlank { "先选账户" }}）", input.paid, enabled, money = true) { value -> vm.edit { it.copy(paid = value) } }
    FundsField("同时支付的新费用（选填，${input.payerCurrency}）", input.newFee, enabled, money = true) { value -> vm.edit { it.copy(newFee = value) } }
    FundsField("费用依据", input.feeNote, enabled) { value -> vm.edit { it.copy(feeNote = value) } }
    Text("新费用另加到扣款并保存为消费；已记过的费用留空。循环信用超付保留为溢缴款，固定本金贷款不能超还。", style = MaterialTheme.typography.bodySmall)
    FundsField("说明", input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
}

@Composable
private fun FundsSubmission(state: FundsUiState, editable: Boolean, vm: FundsViewModel) {
    val original = state.task.original
    when {
        original?.status == PendingMutationStatus.Done -> {
            Text("这次资金操作已保存。")
            AppPrimaryButton("完成并查看账户", enabled = !state.busy, onClick = vm::finish)
        }
        state.task.frozen -> {
            Text(original?.lastError ?: "原提交已保留，正在核实结果。")
            if (original == null) AppPrimaryButton("继续原提交", enabled = !state.busy, onClick = vm::submit)
            if (original?.status == PendingMutationStatus.Failed) AppSecondaryButton("重试原提交", enabled = !state.busy, onClick = vm::retry)
            if (original?.status == PendingMutationStatus.Conflict || original?.lastError?.startsWith("资金请求未接受：") == true)
                AppSecondaryButton("核对最新账户后继续", enabled = !state.busy, onClick = vm::review)
        }
        else -> {
            AppPrimaryButton("确认保存", enabled = editable, onClick = vm::submit)
            AppSecondaryButton("放弃未提交的输入", enabled = !state.busy, onClick = vm::finish)
        }
    }
}

@Composable
internal fun FundsField(label: String, value: String, enabled: Boolean, money: Boolean = false, change: (String) -> Unit) {
    OutlinedTextField(value, change, enabled = enabled, label = { Text(label) }, modifier = Modifier.fillMaxWidth(),
        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = if (money) KeyboardType.Decimal else KeyboardType.Text))
}
