package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException

internal const val DEBT_CREATE_PAYLOAD_REVISION = 1
internal const val DEBT_CREATE_TARGET_PREFIX = "debt_create:"

/** Required revision: unknown or older shapes cannot inherit current create defaults. */
@JsonClass(generateAdapter = true)
data class DebtCreateOutboxPayload(
    val revision: Int,
    val homeCurrencyCode: String,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: DebtCreateRequestDto,
)

enum class DebtCreationPendingState { Waiting, Sending, NeedsAttention, Unsupported }

data class PendingDebtCreation(
    val intentId: Long,
    val state: DebtCreationPendingState,
    val draft: DebtDraft?,
    val homeCurrency: CurrencyCode?,
)

data class DebtCreationQueueSnapshot(
    val binding: LogicalSessionBinding?,
    val intents: List<PendingDebtCreation> = emptyList(),
    val completedIntentIds: Set<Long> = emptySet(),
)

internal fun JsonAdapter<DebtCreateOutboxPayload>.readSupportedDebtCreate(json: String): DebtCreateOutboxPayload? =
    try {
        fromJson(json)?.takeIf {
            it.revision == DEBT_CREATE_PAYLOAD_REVISION &&
                CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode) != null &&
                it.originSessionGeneration.isNotBlank() && it.originBindingRevision.isNotBlank()
        }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }

internal fun OutboxRow.toPendingDebtCreation(adapter: JsonAdapter<DebtCreateOutboxPayload>): PendingDebtCreation {
    val payload = adapter.readSupportedDebtCreate(payloadJson)
        ?: return PendingDebtCreation(id, DebtCreationPendingState.Unsupported, null, null)
    val request = payload.request
    return PendingDebtCreation(
        intentId = id,
        state = when (status) {
            PendingMutationStatus.Pending -> DebtCreationPendingState.Waiting
            PendingMutationStatus.InFlight -> DebtCreationPendingState.Sending
            else -> DebtCreationPendingState.NeedsAttention
        },
        draft = DebtDraft(
            direction = request.direction,
            counterpartyLabel = request.counterpartyLabel.orEmpty(),
            principalAmountCents = request.principalAmountCents,
            debtKind = request.debtKind,
            installmentCount = request.installmentCount?.toInt(),
            installmentPeriodMonths = request.installmentPeriodMonths?.toInt(),
            note = request.note,
        ),
        homeCurrency = CurrencyCode.fromStorageKeyOrNull(payload.homeCurrencyCode),
    )
}
