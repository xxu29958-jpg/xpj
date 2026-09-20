package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION

data class RuntimeCompatibilityDto(
    @param:Json(name = "api_version")
    val apiVersion: String,
    @param:Json(name = "write_compatibility")
    val writeCompatibility: String,
    val capabilities: RuntimeProductCapabilitiesDto,
)

data class RuntimeProductCapabilitiesDto(
    val currency: RuntimeCurrencyCapabilityDto,
    @param:Json(name = "upload_original_receipt_version")
    val uploadOriginalReceiptVersion: Int? = null,
    @param:Json(name = "accounting_time_input_version")
    val accountingTimeInputVersion: Int? = null,
    @param:Json(name = "original_attachment_version")
    val originalAttachmentVersion: Int? = null,
    @param:Json(name = "debt_activity_read_version")
    val debtActivityReadVersion: Int? = null,
)

data class RuntimeCurrencyCapabilityDto(
    @param:Json(name = "request_binding")
    val requestBinding: String?,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String? = null,
    @param:Json(name = "minor_unit_exponent")
    val minorUnitExponent: Int? = null,
    @param:Json(name = "read_compatibility")
    val readCompatibility: String? = null,
)

data class RuntimeWriteCompatibility(
    val conclusion: String,
    val apiVersion: String?,
    val requestBinding: String?,
    val uploadOriginalReceiptVersion: Int? = null,
    val accountingTimeInputVersion: Int? = null,
    val originalAttachmentVersion: Int? = null,
    val debtActivityReadVersion: Int? = null,
) {
    val supportsOriginalAttachment: Boolean get() = originalAttachmentVersion == 1 && apiVersion == CURRENT_TICKETBOX_API_VERSION
    val supportsAccountingTimeInput: Boolean get() = accountingTimeInputVersion == 1

    val canWrite: Boolean
        get() = conclusion == "compatible" &&
            apiVersion == CURRENT_TICKETBOX_API_VERSION &&
            !requestBinding.isNullOrBlank()

    companion object {
        fun compatible(apiVersion: String, requestBinding: String) =
            RuntimeWriteCompatibility("compatible", apiVersion, requestBinding)

        fun blocked(conclusion: String) =
            RuntimeWriteCompatibility(conclusion, null, null)
    }
}

fun RuntimeCompatibilityDto.toWriteCompatibility(): RuntimeWriteCompatibility =
    RuntimeWriteCompatibility(
        conclusion = writeCompatibility,
        apiVersion = apiVersion,
        requestBinding = capabilities.currency.requestBinding,
        uploadOriginalReceiptVersion = capabilities.uploadOriginalReceiptVersion,
        accountingTimeInputVersion = capabilities.accountingTimeInputVersion,
        originalAttachmentVersion = capabilities.originalAttachmentVersion,
        debtActivityReadVersion = capabilities.debtActivityReadVersion,
    )
