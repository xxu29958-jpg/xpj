package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
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
 * stand-in to the real server id. The returned ``rowVersion`` cascades onto
 * same-target PENDING rows (a chained offline edit against the same
 * ``expense:local:{client_ref}`` gets the real token).
 */
class CreateExpenseDispatcher(
    private val apiProvider: () -> ApiService,
    private val payloadAdapter: JsonAdapter<ExpenseManualCreateRequestDto>,
    private val applyServerIdentity: suspend (ledgerId: String, clientRef: String, created: ExpenseDto) -> Unit,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.CreateExpense

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
        val clientRef = request.clientRef
            ?: return DispatchResult.Failure("CreateExpense row missing client_ref")

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
            apiProvider().createManualExpense(request)
        } catch (e: HttpException) {
            return mapHttpException(e)
        } catch (e: IOException) {
            return DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            return DispatchResult.Failure(e.message ?: "POST manual expense threw")
        }

        return try {
            applyServerIdentity(row.ledgerId, clientRef, created)
            DispatchResult.Success(newRowVersion = created.rowVersion)
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
        val body = e.response()?.errorBody()?.string().orEmpty()
        val message = extractServerMessage(body) ?: e.message().orEmpty()
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

    private fun extractServerMessage(body: String): String? {
        val key = "\"message\":\""
        val start = body.indexOf(key)
        if (start < 0) return null
        val begin = start + key.length
        val end = body.indexOf('"', begin)
        if (end < 0) return null
        return body.substring(begin, end)
    }
}
