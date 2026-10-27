package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class DebtBillSourceReferenceDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class DebtBillCaptureReceiptDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "creation_key") val creationKey: String,
    @param:Json(name = "capture_key") val captureKey: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "input_sha256") val inputSha256: String,
    @param:Json(name = "image_hash") val imageHash: String,
)

@JsonClass(generateAdapter = true)
data class DebtBillCaptureDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "creation_key") val creationKey: String,
    @param:Json(name = "capture_key") val captureKey: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    val status: String,
    @param:Json(name = "input_sha256") val inputSha256: String,
    @param:Json(name = "image_hash") val imageHash: String,
    @param:Json(name = "file_name") val fileName: String,
    @param:Json(name = "original_state") val originalState: String,
    @param:Json(name = "adopted_debt_public_id") val adoptedDebtPublicId: String? = null,
    @param:Json(name = "parse_outcome") val parseOutcome: DebtBillParseOutcomeDto? = null,
)

@JsonClass(generateAdapter = true)
data class DebtBillCaptureListDto(val captures: List<DebtBillCaptureDto>)

@JsonClass(generateAdapter = true)
data class DebtBillParseRequestDto(@param:Json(name = "expected_row_version") val expectedRowVersion: Long)

@JsonClass(generateAdapter = true)
data class DebtBillParseOutcomeDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "attempt_key") val attemptKey: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    val status: String,
    val provider: String,
    val suggestion: DebtBillParseResponseDto? = null,
    @param:Json(name = "error_code") val errorCode: String? = null,
)
