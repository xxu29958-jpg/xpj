package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.remote.dto.InstallmentCommandDto
import com.ticketbox.data.remote.dto.InstallmentPeriodInputDto
import com.ticketbox.data.remote.dto.InstallmentPaymentPartDto
import com.ticketbox.data.remote.dto.CreditDrawPaymentPartDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.parseExactMoneyMinor

@JsonClass(generateAdapter = true)
data class InstallmentPeriodInput(val date: String = "", val principal: String = "", val fee: String = "")
@JsonClass(generateAdapter = true)
data class CreditAllocationInput(val id: String, val kind: String, val principal: String = "", val fee: String = "")

internal object InstallmentInputWire {
    private val moshi = Moshi.Builder().build()
    val periods = moshi.adapter<List<InstallmentPeriodInput>>(Types.newParameterizedType(List::class.java, InstallmentPeriodInput::class.java))
    val allocations = moshi.adapter<List<CreditAllocationInput>>(Types.newParameterizedType(List::class.java, CreditAllocationInput::class.java))
}

internal fun installmentAmount(value: String, currency: String): Long = requireNotNull(parseExactMoneyMinor(value,
    requireNotNull(CurrencyCode.fromStorageKeyOrNull(currency)))) { "请核对合约原币金额和小数位。" }

internal fun FundsInput.installmentCommand() = InstallmentCommandDto(version, name, source, date, previousAgreement.ifBlank { null },
    drawIds, requireNotNull(InstallmentInputWire.periods.fromJson(periodsJson)).map { row ->
        java.time.LocalDate.parse(row.date)
        InstallmentPeriodInputDto(row.date, installmentAmount(row.principal, currency),
            row.fee.takeIf(String::isNotBlank)?.let { installmentAmount(it, currency) } ?: 0L)
    })

internal fun FundsInput.paymentAllocation(): Pair<List<InstallmentPaymentPartDto>, List<CreditDrawPaymentPartDto>> {
    val inputs = requireNotNull(InstallmentInputWire.allocations.fromJson(allocationJson))
        .filter { it.principal.isNotBlank() || it.fee.isNotBlank() }
    return inputs.filter { it.kind == "period" }.map { InstallmentPaymentPartDto(it.id,
        it.principal.takeIf(String::isNotBlank)?.let { value -> installmentAmount(value, currency) } ?: 0L,
        it.fee.takeIf(String::isNotBlank)?.let { value -> installmentAmount(value, currency) } ?: 0L) } to
        inputs.filter { it.kind == "draw" }.map { CreditDrawPaymentPartDto(it.id, installmentAmount(it.principal, currency)) }
}
