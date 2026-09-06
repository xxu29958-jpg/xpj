package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

class RecordDebtAdjustmentDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val adapter: JsonAdapter<DebtAdjustmentPayload>,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.RecordDebtAdjustment

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val intent = row.describeDebtAdjustment(adapter).intent
            ?: return DispatchResult.Failure("debt_adjustment_payload_unsupported")
        return try {
            apiProvider(row).recordDebtAdjustment(intent.subject.publicId, intent.request, row.idempotencyKey)
            // Do not cascade a new OCC: an adjustment's original command is immutable.
            DispatchResult.Success()
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            when (val result = mapOutboxHttpException(error)) {
                // Missing target does not prove that this particular adjustment was applied.
                is DispatchResult.Discarded -> DispatchResult.Failure(result.reason)
                else -> result
            }
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("debt_adjustment_connection_interrupted")
        } catch (_: RepositoryException) {
            DispatchResult.Failure("debt_adjustment_binding_changed")
        } catch (_: Exception) {
            DispatchResult.Failure("debt_adjustment_response_unverified")
        }
    }
}
