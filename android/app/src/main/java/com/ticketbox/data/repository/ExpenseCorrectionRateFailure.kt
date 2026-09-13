package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.MissingExchangeRateDto

internal const val CORRECTION_RATE_PENDING = "exchange_rate_pending"
private val correctionRateAdapter = Moshi.Builder().build().adapter(MissingExchangeRateDto::class.java)

/** Only this original's server refusal supplies the pair and date; the command remains untouched. */
internal fun NetworkErrorHandler.ParsedError.correctionRateFailure(): String =
    missingExchangeRate?.takeIf { it.canEnterManualRate() }?.let {
        "$CORRECTION_RATE_PENDING:${correctionRateAdapter.toJson(it)}"
    } ?: CORRECTION_RATE_PENDING

internal fun readCorrectionRateFailure(error: String): MissingExchangeRateDto? =
    error.takeIf { it.startsWith("$CORRECTION_RATE_PENDING:") }?.substringAfter(':')?.let { json ->
        runCatching { correctionRateAdapter.fromJson(json)?.takeIf { it.canEnterManualRate() } }.getOrNull()
    }
