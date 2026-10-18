package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.CurrencyChoiceField
import com.ticketbox.viewmodel.FundsViewModel

@Composable
internal fun FundsActivityFields(input: FundsInput, accounts: List<FinancialAccountDto>, enabled: Boolean, vm: FundsViewModel) {
    Text(when (input.mode) {
        "income" -> "记录已经到账的收入；收入计划不改变余额。"
        "loan" -> "实际到账与本金义务同时保存；贷款不计收入。"
        "transfer" -> "转出与到账同时保存，不产生消费或收入。"
        else -> "先保留外部快照，核对后可记录差额更正，原历史保留。"
    })
    val label = when (input.mode) {
        "reconciliation" -> if (input.kind == "credit") "已核对欠款，溢缴款填负数" else "已核对余额"
        "transfer" -> "实际转出金额"
        else -> "实际到账金额"
    }
    FundsField("$label（${input.currency}）", input.activityAmount, enabled, money = true) { value -> vm.edit { it.copy(activityAmount = value) } }
    when (input.mode) {
        "transfer" -> FundsTransferFields(input, accounts, enabled, vm)
        "loan" -> {
            FundsField("贷款方 / 贷款名称", input.loanName, enabled) { value -> vm.edit { it.copy(loanName = value) } }
            CurrencyChoiceField(CurrencyCode.fromStorageKeyOrNull(input.loanCurrency), enabled, title = "选择合同本金币种") { currency -> vm.edit { it.copy(loanCurrency = currency.storageKey) } }
            FundsField("已发生本金（${input.loanCurrency}）", input.loanPrincipal, enabled, money = true) { value -> vm.edit { it.copy(loanPrincipal = value) } }
            Text("本金与到账分别记录，不据此猜测费用。")
        }
        "reconciliation" -> {
            Row {
                Switch(input.applyAdjustment, { value -> vm.edit { it.copy(applyAdjustment = value) } }, enabled = enabled)
                Text("已核对：记录差额更正并建立余额基准")
            }
            Text("关闭时只保存快照和待解释差异，不改余额。")
        }
    }
    FundsField("来源与说明", input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
}

@Composable
private fun FundsTransferFields(input: FundsInput, accounts: List<FinancialAccountDto>, enabled: Boolean, vm: FundsViewModel) {
    var choosing by rememberSaveable { mutableStateOf(false) }
    AppSecondaryButton(input.payerName.ifBlank { "选择实际收款账户" }, enabled = enabled) { choosing = true }
    if (choosing) AlertDialog(onDismissRequest = { choosing = false }, title = { Text("实际收款账户") },
        text = { LazyColumn { items(accounts.filter { it.kind != "credit" && !it.archived && it.publicId != input.accountId }) { account ->
            TextButton(onClick = { vm.choosePayer(account); choosing = false }) { Text("${account.name} · ${account.currencyCode}") }
        } } }, confirmButton = { TextButton(onClick = { choosing = false }) { Text("返回") } })
    FundsField("实际到账（${input.payerCurrency.ifBlank { "先选账户" }}）", input.otherAmount, enabled, money = true) { value -> vm.edit { it.copy(otherAmount = value) } }
}
