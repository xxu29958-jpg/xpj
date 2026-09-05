package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class CreateDebtDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<DebtCreateOutboxPayload>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.CreateDebt
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Debt create")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val key = row.idempotencyKey?.takeIf { it.isNotBlank() }
            ?: return DispatchResult.Failure("debt_create_intent_invalid")
        if (row.targetId != "$DEBT_CREATE_TARGET_PREFIX$key" || row.expectedRowVersion != 0L) {
            return DispatchResult.Failure("debt_create_intent_invalid")
        }
        val payload = payloadAdapter.readSupportedDebtCreate(row.payloadJson)
            ?: return DispatchResult.Failure("debt_create_payload_unsupported")
        return try {
            apiProvider(row).createDebt(payload.request, key)
            DispatchResult.Success()
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            val code = errors.parseHttpError(error).errorCode
            when {
                error.code() == 409 && code == "idempotency_key_in_progress" ->
                    DispatchResult.RetryableFailure("debt_create_response_pending")
                error.code() == 408 || error.code() == 429 || error.code() in 500..599 ->
                    DispatchResult.RetryableFailure("debt_create_connection_interrupted")
                else -> DispatchResult.Failure("debt_create_rejected")
            }
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("debt_create_connection_interrupted")
        } catch (_: RepositoryException) {
            DispatchResult.Failure("debt_create_binding_changed")
        } catch (_: Exception) {
            // The request may already have committed. Retain the same intent for explicit recovery.
            DispatchResult.Failure("debt_create_response_unverified")
        }
    }
}
