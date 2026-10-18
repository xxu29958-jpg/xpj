package com.ticketbox.ui.screens

import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.data.remote.dto.AccountChoiceDto
import com.ticketbox.data.remote.dto.CreditTermsDto
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.viewmodel.FundsViewModel

@Composable
internal fun FundsAccountChoices(choices: List<AccountChoiceDto>, enabled: Boolean, vm: FundsViewModel) {
    var choosing by rememberSaveable { mutableStateOf(false) }
    if (choices.isNotEmpty()) AppSecondaryButton("从常用账户开始", enabled = enabled) { choosing = true }
    if (choosing) AlertDialog(onDismissRequest = { choosing = false }, title = { Text("选择常用账户") },
        text = { LazyColumn { items(choices, key = { it.key }) { choice ->
            TextButton(enabled = enabled, onClick = {
                vm.edit { it.copy(name = choice.name, kind = choice.kind, institution = choice.institution) }
                choosing = false
            }) { Text(choice.name) }
        } } }, confirmButton = { TextButton(onClick = { choosing = false }) { Text("返回") } })
    Text("支持同银行多张卡、自定义名称和尾号。支付宝或微信是支付渠道时，选择实际扣款银行卡；借呗、金条、美团借钱等实际借款从收款账户记录贷款到账。", style = MaterialTheme.typography.bodySmall)
}

@Composable
internal fun FundsCreditTermsFields(input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    Text("额度与账单参考", style = MaterialTheme.typography.titleMedium)
    Text("额度不是余额，不计入资产和信封可分配资金。可用额度按页面填写，不用总额度减欠款推算。", style = MaterialTheme.typography.bodySmall)
    FundsField("授信额度（选填，${input.currency}）", input.creditLimit, enabled, money = true) { value -> vm.edit { it.copy(creditLimit = value) } }
    FundsField("页面显示的可用额度（选填）", input.availableCredit, enabled, money = true) { value -> vm.edit { it.copy(availableCredit = value) } }
    FundsField("额度查询日期（YYYY-MM-DD）", input.creditObservedOn, enabled) { value -> vm.edit { it.copy(creditObservedOn = value) } }
    FundsField("额度与账单依据", input.creditSource, enabled) { value -> vm.edit { it.copy(creditSource = value) } }
    FundsField("每月账单日（选填，1—31）", input.statementDay, enabled) { value -> vm.edit { it.copy(statementDay = value) } }
    FundsField("每月还款日（选填，1—31）", input.paymentDueDay, enabled) { value -> vm.edit { it.copy(paymentDueDay = value) } }
    Text("实际应还金额、日期和费用以你的当期账单或合约为准。这里不会生成消费、还款或未来费用。", style = MaterialTheme.typography.bodySmall)
}

@Composable
internal fun FundsCreditTermsRead(terms: CreditTermsDto, currency: String) {
    fun amount(value: Long?) = value?.let { formatDisplayAmount(it, CurrencyDisplay.forRecord(currency)) } ?: "未记录"
    Text("授信额度 ${amount(terms.creditLimitMinor)} · 可用额度 ${amount(terms.availableCreditMinor)}")
    terms.observedOn?.let { Text("${it} 查询 · ${terms.source.orEmpty()}", style = MaterialTheme.typography.bodySmall) }
    if (terms.statementDay != null || terms.paymentDueDay != null)
        Text("每月账单日 ${terms.statementDay?.toString() ?: "未记录"} · 还款日 ${terms.paymentDueDay?.toString() ?: "未记录"}，以实际账单为准。", style = MaterialTheme.typography.bodySmall)
}
