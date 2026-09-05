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
)

data class RuntimeCurrencyCapabilityDto(
    @param:Json(name = "request_binding")
    val requestBinding: String?,
)

data class RuntimeWriteCompatibility(
    val conclusion: String,
    val apiVersion: String?,
    val requestBinding: String?,
) {
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
    )
