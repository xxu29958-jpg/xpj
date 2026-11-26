package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import java.time.LocalDate
import java.time.format.DateTimeParseException

private val versionFormat = Regex("^\\d{4}-\\d{2}-\\d{2}$")
private val clientDate = LocalDate.parse(CURRENT_TICKETBOX_API_VERSION)

private fun protocolDate(value: String?): LocalDate? {
    if (value == null || !versionFormat.matches(value)) return null
    return try {
        LocalDate.parse(value).takeIf { it.year > 0 }
    } catch (_: DateTimeParseException) {
        null
    }
}

private fun serverSupportsClient(version: String?): Boolean =
    protocolDate(version)?.let { it >= clientDate } == true

private fun clientMeetsFloor(minimum: String?): Boolean =
    protocolDate(minimum)?.let { it <= clientDate } == true

private fun acceptsReader(server: String?, readFloor: String? = null): Boolean =
    serverSupportsClient(server) && clientMeetsFloor(readFloor ?: server)

data class RuntimeCompatibilityDto(
    @param:Json(name = "api_version")
    val apiVersion: String,
    @param:Json(name = "write_compatibility")
    val writeCompatibility: String,
    val capabilities: RuntimeProductCapabilitiesDto,
    @param:Json(name = "min_read_client_version")
    val minReadClientVersion: String? = null,
    @param:Json(name = "min_write_client_version")
    val minWriteClientVersion: String? = null,
    @param:Json(name = "supported_payload_revisions")
    val supportedPayloadRevisions: Map<String, List<Int>>? = null,
) {
    val readerVersionAccepted: Boolean get() = acceptsReader(apiVersion, minReadClientVersion)
    val writerVersionAccepted: Boolean get() = readerVersionAccepted && clientMeetsFloor(minWriteClientVersion ?: apiVersion)
}

data class RuntimeProductCapabilitiesDto(
    val currency: RuntimeCurrencyCapabilityDto,
    @param:Json(name = "upload_original_receipt_version")
    val uploadOriginalReceiptVersion: Int? = null,
    @param:Json(name = "accounting_time_input_version")
    val accountingTimeInputVersion: Int? = null,
    @param:Json(name = "repayment_time_input_version")
    val repaymentTimeInputVersion: Int? = null,
    @param:Json(name = "original_attachment_version")
    val originalAttachmentVersion: Int? = null,
    @param:Json(name = "original_attachment_create_version")
    val originalAttachmentCreateVersion: Int? = null,
    @param:Json(name = "debt_activity_read_version")
    val debtActivityReadVersion: Int? = null,
    @param:Json(name = "debt_bill_source_version")
    val debtBillSourceVersion: Int? = null,
    @param:Json(name = "expense_confirmation_version")
    val expenseConfirmationVersion: Int? = null,
    @param:Json(name = "notification_batch_version")
    val notificationBatchVersion: Int? = null,
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
    val originalAttachmentCreateVersion: Int? = null,
    val debtActivityReadVersion: Int? = null,
    val repaymentTimeInputVersion: Int? = null,
    val debtBillSourceVersion: Int? = null,
    val expenseConfirmationVersion: Int? = null,
    val notificationBatchVersion: Int? = null,
    val readerVersionAccepted: Boolean = acceptsReader(apiVersion),
    val writerVersionAccepted: Boolean = readerVersionAccepted,
    val supportedPayloadRevisions: Map<String, List<Int>>? = null,
) {
    val supportsOriginalAttachment: Boolean get() = originalAttachmentVersion == 1 && serverSupportsClient(apiVersion)
    private fun acceptsPayload(family: String, revision: Int, legacy: Int?): Boolean =
        if (supportedPayloadRevisions == null) legacy == revision else revision in supportedPayloadRevisions[family].orEmpty()

    val supportsAccountingTimeInput: Boolean get() = acceptsPayload("accounting_time_input", 1, accountingTimeInputVersion)
    val supportsRepaymentTimeInput: Boolean get() = acceptsPayload("repayment_time_input", 1, repaymentTimeInputVersion)
    val supportsFirstAttachment: Boolean get() = acceptsPayload("original_attachment_create", 1, originalAttachmentCreateVersion)
    val supportsDebtBillSource: Boolean get() = acceptsPayload("debt_bill_source", 1, debtBillSourceVersion)
    val supportsAtomicConfirmation: Boolean get() = acceptsPayload("expense_confirmation", 2, expenseConfirmationVersion)
    val supportsNotificationBatch: Boolean get() = acceptsPayload("notification_batch", 1, notificationBatchVersion)

    val canWrite: Boolean
        get() = conclusion == "compatible" &&
            writerVersionAccepted &&
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
        conclusion = if (writerVersionAccepted) writeCompatibility else "client_upgrade_required",
        readerVersionAccepted = readerVersionAccepted,
        supportedPayloadRevisions = supportedPayloadRevisions,
        writerVersionAccepted = writerVersionAccepted,
        apiVersion = apiVersion,
        requestBinding = capabilities.currency.requestBinding,
        uploadOriginalReceiptVersion = capabilities.uploadOriginalReceiptVersion,
        accountingTimeInputVersion = capabilities.accountingTimeInputVersion,
        repaymentTimeInputVersion = capabilities.repaymentTimeInputVersion,
        originalAttachmentVersion = capabilities.originalAttachmentVersion,
        originalAttachmentCreateVersion = capabilities.originalAttachmentCreateVersion,
        debtActivityReadVersion = capabilities.debtActivityReadVersion,
        debtBillSourceVersion = capabilities.debtBillSourceVersion,
        expenseConfirmationVersion = capabilities.expenseConfirmationVersion,
        notificationBatchVersion = capabilities.notificationBatchVersion,
    )
