package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import com.ticketbox.data.remote.dto.InstallmentsDto
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.data.repository.InstallmentInputWire
import com.ticketbox.data.repository.InstallmentPeriodInput
import com.ticketbox.data.repository.CreditAllocationInput
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.start
import com.ticketbox.viewmodel.reviseAgreement

private fun amount(value: Long, currency: String) = formatDisplayAmount(value, CurrencyDisplay.forRecord(currency))

@Composable
internal fun InstallmentFields(input: FundsInput, data: InstallmentsDto?, enabled: Boolean, vm: FundsViewModel) {
    Text("按已经成立的合约填写。逐期本金只重排已有欠款，未来费用还不会记为消费。")
    FundsField("合约名称", input.name, enabled) { value -> vm.edit { it.copy(name = value) } }
    FundsField("合约来源与变更依据", input.source, enabled) { value -> vm.edit { it.copy(source = value) } }
    Text("纳入哪些未偿本金", style = MaterialTheme.typography.titleSmall)
    data?.draws.orEmpty().filter { it.remainingMinor > 0 && (it.agreementPublicId == null || it.agreementPublicId == input.previousAgreement) }.forEach { draw ->
        Row {
            Checkbox(draw.publicId in input.drawIds, { chosen -> vm.edit { it.copy(drawIds = if (chosen) it.drawIds + draw.publicId else it.drawIds - draw.publicId) } }, enabled = enabled)
            Text("${draw.note} · ${draw.occurredOn}\n未偿 ${amount(draw.remainingMinor, input.currency)}")
        }
    }
    Text("逐期明细 · ${input.currency}", style = MaterialTheme.typography.titleSmall)
    val periods = InstallmentInputWire.periods.fromJson(input.periodsJson).orEmpty()
    periods.forEachIndexed { index, row ->
        fun put(value: InstallmentPeriodInput) = vm.edit { it.copy(periodsJson = InstallmentInputWire.periods.toJson(
            periods.toMutableList().also { rows -> rows[index] = value })) }
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            FundsField("第 ${index + 1} 期到期日（YYYY-MM-DD）", row.date, enabled) { put(row.copy(date = it)) }
            FundsField("该期本金", row.principal, enabled, money = true) { put(row.copy(principal = it)) }
            FundsField("计划费用", row.fee, enabled, money = true) { put(row.copy(fee = it)) }
            TextButton(onClick = { vm.edit { it.copy(periodsJson = InstallmentInputWire.periods.toJson(periods.filterIndexed { n, _ -> n != index })) } }, enabled = enabled) { Text("移除这期") }
        }
    }
    AppSecondaryButton("添加一期", enabled = enabled && periods.size < 120) { vm.edit {
        it.copy(periodsJson = InstallmentInputWire.periods.toJson(periods + InstallmentPeriodInput())) } }
    Text("更新合约时只填写剩余排期；旧合约、已还本金和已付费用仍保留。", style = MaterialTheme.typography.bodySmall)
}

@Composable
internal fun InstallmentPaymentFields(input: FundsInput, data: InstallmentsDto?, enabled: Boolean, vm: FundsViewModel) {
    val allocations = InstallmentInputWire.allocations.fromJson(input.allocationJson).orEmpty()
    fun put(value: CreditAllocationInput) = vm.edit { it.copy(allocationJson = InstallmentInputWire.allocations.toJson(
        allocations.filter { row -> row.id != value.id } + value)) }
    Text("本金付到哪里 · ${input.currency}", style = MaterialTheme.typography.titleSmall)
    Text("有分期时明确本次支付的期次；提前还、部分还都填实际金额。这里的费用包含在上方的新费用中，已记过的费用不能再记一次。")
    val validIds = mutableSetOf<String>()
    data?.agreements.orEmpty().filter { it.active }.forEach { agreement ->
        Text("${agreement.name} · 版本 ${agreement.revision}")
        if (agreement.needsReview) Text("退款或更正已改变来源本金，请先更新剩余排期。", color = MaterialTheme.colorScheme.error)
        agreement.periods.filter { it.principalMinor > it.paidPrincipalMinor }.forEach { period ->
            validIds.add(period.publicId)
            val row = allocations.firstOrNull { it.id == period.publicId } ?: CreditAllocationInput(period.publicId, "period")
            Text("第 ${period.position} 期 · ${period.dueOn} · 未付本金 ${amount(period.principalMinor - period.paidPrincipalMinor, input.currency)}")
            FundsField("本次本金", row.principal, enabled, money = true) { put(row.copy(principal = it)) }
            FundsField("其中本次新发生费用", row.fee, enabled, money = true) { put(row.copy(fee = it)) }
        }
    }
    data?.draws.orEmpty().filter { it.agreementPublicId == null && it.remainingMinor > 0 }.forEach { draw ->
        validIds.add(draw.publicId)
        val row = allocations.firstOrNull { it.id == draw.publicId } ?: CreditAllocationInput(draw.publicId, "draw")
        Text("${draw.note} · 未分期本金 ${amount(draw.remainingMinor, input.currency)}")
        FundsField("本次清偿", row.principal, enabled, money = true) { put(row.copy(principal = it)) }
    }
    allocations.filter { it.id !in validIds && (it.principal.isNotBlank() || it.fee.isNotBlank()) }.forEach { row ->
        Text("原分配已不在当前待还项目中：本金 ${row.principal}，费用 ${row.fee}。原输入保留，请核对。")
        TextButton(onClick = { vm.edit { it.copy(allocationJson = InstallmentInputWire.allocations.toJson(allocations - row)) } }, enabled = enabled) { Text("移除此项原分配") }
    }
    FundsField("全部清偿后多付的溢缴款", input.overpayment, enabled, money = true) { value -> vm.edit { it.copy(overpayment = value) } }
}

@Composable
internal fun InstallmentHistory(data: InstallmentsDto?, canModify: Boolean, vm: FundsViewModel) {
    Text("真实分期", style = MaterialTheme.typography.titleMedium)
    if (canModify) AppSecondaryButton("记录分期合约") { vm.start("installments") }
    data?.agreements.orEmpty().forEach { agreement ->
        Text("${agreement.name} · 版本 ${agreement.revision} · ${if (agreement.active) "当前合约" else "历史合约"}")
        Text("${agreement.agreedOn} · ${agreement.source}", style = MaterialTheme.typography.bodySmall)
        if (agreement.needsReview) Text("本金已被退款或更正改变，请按实际合约更新剩余排期；已付费用保留。")
        agreement.periods.forEach { period ->
            Text("第 ${period.position} 期 · ${period.dueOn}\n本金 ${amount(period.principalMinor, data!!.currencyCode)} · 已付 ${amount(period.paidPrincipalMinor, data.currencyCode)}\n计划费用 ${amount(period.plannedFeeMinor, data.currencyCode)} · 已付 ${amount(period.paidFeeMinor, data.currencyCode)}")
        }
        if (agreement.active && canModify) AppSecondaryButton("更新剩余排期") { vm.reviseAgreement(agreement) }
    }
}
