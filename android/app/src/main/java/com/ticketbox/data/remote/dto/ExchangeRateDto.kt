package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ExchangeRateRequestDto(
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String,
    @param:Json(name = "rate_to_cny") val rateToHome: String,
    val source: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class ExchangeRateDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String,
    @param:Json(name = "rate_to_cny") val rateToHome: String,
    val source: String,
    @param:Json(name = "created_at") val createdAt: String,
    @param:Json(name = "updated_at") val updatedAt: String,
    @param:Json(name = "row_version") val rowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class ExchangeRateListDto(val items: List<ExchangeRateDto>)

@JsonClass(generateAdapter = true)
data class BudgetAdviceInputsDto(
    val month: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    val breakdown: DiscretionaryResponseDto,
    @param:Json(name = "missing_rates") val missingRates: List<MissingExchangeRateDto>,
    @param:Json(name = "reference_rates") val referenceRates: List<ProjectionReferenceDto> = emptyList(),
    @param:Json(name = "inputs_fingerprint") val inputsFingerprint: String? = null,
) {
    val readyForAdvice: Boolean get() = missingRates.isEmpty() && breakdown.monthlyIncomeCents != null &&
        breakdown.fixedExpensesCents != null && breakdown.spentAmountCents != null && breakdown.discretionaryCents != null
}

@JsonClass(generateAdapter = true)
data class MissingExchangeRateDto(
    @param:Json(name = "source_currency_code") val sourceCurrencyCode: String?,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String?,
) {
    fun canEnterManualRate(): Boolean =
        com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(sourceCurrencyCode)?.storageKey == sourceCurrencyCode && sourceCurrencyCode != null &&
            com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)?.storageKey == homeCurrencyCode && sourceCurrencyCode != homeCurrencyCode &&
            rateDate != null && runCatching { java.time.LocalDate.parse(rateDate).toString() == rateDate }.getOrDefault(false)
}
