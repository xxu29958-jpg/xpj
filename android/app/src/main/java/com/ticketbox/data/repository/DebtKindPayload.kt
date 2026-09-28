package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtKindSetRequestDto
import com.ticketbox.domain.model.DebtKinds
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

@JsonClass(generateAdapter = true)
data class DebtKindPayload(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: DebtKindSetRequestDto,
) : DebtWriteIntent { override val expectedRowVersion: Long get() = request.expectedRowVersion }

internal fun OutboxRow.describeDebtKind(adapter: JsonAdapter<DebtKindPayload>): PendingDebtWrite {
    val parsed = try { adapter.fromJson(payloadJson) }
        catch (_: JsonDataException) { null } catch (_: IOException) { null }
    val intent = parsed?.takeIf {
        it.revision == 1 && it.subject.publicId.isNotBlank() && it.subject.homeCurrencyCode.isNotBlank() &&
            it.originSessionGeneration.isNotBlank() && it.originBindingRevision.isNotBlank() &&
            it.request.debtKind in DebtKinds.ORDERED && it.expectedRowVersion > 0 &&
            it.expectedRowVersion == expectedRowVersion && targetId == debtWriteTarget(it.subject.publicId) &&
            !idempotencyKey.isNullOrBlank()
    }
    return PendingDebtWrite(this, intent)
}

/** Classification has no monetary input; the original receipt is separate from current debt facts. */
class SetDebtKindDispatcher internal constructor(private val guard: LedgerRequestGuard,
    private val adapter: JsonAdapter<DebtKindPayload>, private val receiptAdapter: JsonAdapter<DebtDto>) : OutboxMutationDispatcher {
    override val type = PendingMutationType.SetDebtKind
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = row.describeDebtKind(adapter).kind
            ?: return DispatchResult.Failure("debt_kind_payload_unsupported", definitelyRejected = true)
        return try {
            val result = guard.bind(expectedLedgerId = row.ledgerId).serviceForOriginalDebtWrite(row, intent)
                .setDebtKind(intent.subject.publicId, intent.request, row.idempotencyKey)
            if (result.matchesOriginalKind(intent, row)) DispatchResult.Success(receiptJson = receiptAdapter.toJson(result))
            else DispatchResult.Failure("debt_kind_response_unverified")
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            mapDebtWriteHttpException(error, intent.subject.publicId)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("debt_kind_connection_interrupted")
        } catch (_: RepositoryException) {
            DispatchResult.Failure("debt_kind_binding_changed", definitelyRejected = true)
        } catch (_: Exception) {
            DispatchResult.Failure("debt_kind_response_unverified")
        }
    }
}

private fun DebtDto.matchesOriginalKind(intent: DebtKindPayload, row: OutboxRow): Boolean =
    publicId == intent.subject.publicId && ledgerId == row.ledgerId &&
        homeCurrencyCode == intent.subject.homeCurrencyCode && rowVersion == intent.expectedRowVersion + 1 &&
        debtKind == intent.request.debtKind
