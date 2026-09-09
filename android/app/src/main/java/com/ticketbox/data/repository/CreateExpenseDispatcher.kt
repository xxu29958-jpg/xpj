package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.domain.model.parseExactMoneyMinor
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/**
 * issue #65 slice 4: replay a queued ``POST /api/expenses/manual`` (offline
 * manual create).
 *
 * Unlike the nine OCC-token dispatchers, the create has no
 * ``expected_row_version`` — idempotency comes from the body ``client_ref``
 * (backend Slice 1 keys ``draft_idempotency_key`` on ``{device_id}:{client_ref}``).
 * So a committed-but-unseen first attempt (the POST committed server-side but the
 * response was lost → the row is still local) replays with the SAME ``client_ref``
 * and the server HITs the existing row instead of double-creating.
 *
 * On success the server-assigned identity (id / public_id / row_version) is
 * written back onto the optimistic local row via [applyServerIdentity] (resolved
 * by ``client_ref``), so the row's domain id flips from its negative local
 * stand-in to the real server id. Success leaves successor requests unchanged;
 * the server resolves a local-ref first-write token from this original receipt.
 */
class CreateExpenseDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseManualCreateRequestDto>,
    private val applyServerIdentity: suspend (ledgerId: String, clientRef: String, created: ExpenseDto) -> Unit,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.CreateExpense
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "ManualCreate")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val request = try {
            payloadAdapter.fromJson(row.payloadJson)
                ?: return DispatchResult.Failure("payload deserialised to null")
        } catch (e: JsonDataException) {
            return DispatchResult.Failure("payload JSON shape changed: ${e.message ?: "JsonDataException"}")
        } catch (e: JsonEncodingException) {
            return DispatchResult.Failure("payload JSON malformed: ${e.message ?: "JsonEncodingException"}")
        }

        // The create's idempotency lives in the body ``client_ref`` (not a header
        // / token). A null ref is a malformed / pre-slice-4 row the server would
        // double-create on — surface it as a visible FAILED row, not a silent
        // duplicate.
        val clientRef = request.clientRef?.takeIf { it.isNotBlank() }
            ?: return DispatchResult.Failure("manual_create_original_unverified")
        if (request.originalCurrency.isNullOrBlank() || request.originalAmount.isNullOrBlank()) {
            return DispatchResult.Failure("manual_create_original_unverified")
        }

        return performCreate(row, request, clientRef)
    }

    /** POST the create, then write the server identity back. Split out of
     *  [dispatch] so each stays under the cyclomatic-complexity budget. */
    private suspend fun performCreate(
        row: OutboxRow,
        request: ExpenseManualCreateRequestDto,
        clientRef: String,
    ): DispatchResult {
        val created = try {
            apiProvider(row).createManualExpense(request)
        } catch (e: HttpException) {
            return mapHttpException(e)
        } catch (e: IOException) {
            return DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            return DispatchResult.Failure(e.message ?: "POST manual expense threw")
        }

        if (!created.matchesManualCreation(request)) return DispatchResult.Failure(MANUAL_CREATE_RECEIPT_REVIEW)
        return try {
            applyServerIdentity(row.ledgerId, clientRef, created)
            DispatchResult.Success(newRowVersion = created.rowVersion, receiptJson = manualCreationReceiptJson(created.id))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // The create COMMITTED server-side; a local write-back failure is
            // transient (the re-POST is idempotent via client_ref → server HITs
            // the same row), so retry rather than FAIL — FAILING would risk a
            // duplicate if the user redid the entry by hand.
            DispatchResult.RetryableFailure(e.message ?: "create write-back failed")
        }
    }

    private fun mapHttpException(e: HttpException): DispatchResult {
        val parsed = errors.parseHttpError(e)
        if (parsed.errorCode == MANUAL_CREATE_RECEIPT_REVIEW) {
            val id = parsed.expenseId?.takeIf { it > 0 }
            return DispatchResult.Failure(MANUAL_CREATE_RECEIPT_REVIEW + (id?.let { ":$it" } ?: ""))
        }
        val message = parsed.outboxFailureMessage()
        return when (e.code()) {
            in 500..599, 408, 429 -> DispatchResult.RetryableFailure(message.ifEmpty { "server ${e.code()}" })
            // 400 / 422: a validation / payload-contract rejection
            // (amount_required, idempotency_key_reused on a materially different
            // body). It will never succeed on retry, but the user MUST see it —
            // a visible FAILED row, not a silent Discard that drops their entry.
            400, 422 -> DispatchResult.Failure(message.ifEmpty { "HTTP ${e.code()}" })
            else -> DispatchResult.Failure(message.ifEmpty { "HTTP ${e.code()}" })
        }
    }

}

internal const val MANUAL_CREATE_RECEIPT_REVIEW = "manual_create_original_requires_review"

private fun ExpenseDto.matchesManualCreation(request: ExpenseManualCreateRequestDto): Boolean {
    val currency = CurrencyCode.fromStorageKeyOrNull(request.originalCurrency) ?: return false
    val amount = request.originalAmount?.let { parseExactMoneyMinor(it, currency) } ?: return false
    return id > 0 && rowVersion > 0 && !publicId.isNullOrBlank() && status in setOf("pending", "confirmed") &&
        source == ExpenseSourceValues.MANUAL_ENTRY &&
        !homeCurrency.isNullOrBlank() && (request.homeCurrencyCode == null || request.homeCurrencyCode == homeCurrency) &&
        originalCurrencyCode == currency.storageKey && originalAmountMinor == amount
}

internal fun OutboxRow.requiresManualCreateReview(): Boolean = type == PendingMutationType.CreateExpense &&
    lastError?.substringBefore(':') in setOf("manual_create_original_unverified", MANUAL_CREATE_RECEIPT_REVIEW)

/** The server may identify the existing fact; absent or invalid identity never opens another record. */
internal fun OutboxRow.manualCreateReviewExpenseId(): Long? = lastError
    ?.takeIf { type == PendingMutationType.CreateExpense && it.startsWith("$MANUAL_CREATE_RECEIPT_REVIEW:") }
    ?.substringAfter(':')?.toLongOrNull()?.takeIf { it > 0 }
