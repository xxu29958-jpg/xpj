package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** The queued preview and key are immutable; accepted applications only need read refresh. */
class ApplyConfirmedRulesDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<RuleApplicationPayload>,
    private val receiptAdapter: JsonAdapter<RuleApplyConfirmedResponseDto>,
    private val refreshConfirmed: suspend (OutboxRow) -> Unit,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.ApplyConfirmedRules
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Rule application")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = runCatching { payloadAdapter.fromJson(row.payloadJson) }.getOrNull()
        if (payload?.supports(row) != true) return DispatchResult.Failure("原应用内容无法核对，已保留原任务。")
        return try {
            val receipt = apiProvider(row).applyConfirmedRules(
                RuleApplyConfirmedRequestDto(confirm = true, previewToken = payload.previewToken),
                maxScan = payload.maxScan, idempotencyKey = row.idempotencyKey)
            if (!payload.accepts(row, receipt)) DispatchResult.Failure(RULE_APPLICATION_UNVERIFIED)
            else {
                val refreshRequired = try {
                    if (receipt.changedCount > 0) refreshConfirmed(row)
                    false
                } catch (error: Exception) {
                    // The verified first receipt survives cancellation or failure of the later read.
                    if (error !is CancellationException && error !is RepositoryException) {
                        logNetworkWarning("operation=ApplyConfirmedRules accepted read failed", error)
                    }
                    true
                }
                DispatchResult.Success(receiptJson = receiptAdapter.toJson(receipt), acceptedReadRefreshRequired = refreshRequired)
            }
        } catch (error: HttpException) {
            val parsed = errors.parseHttpError(error)
            if (parsed.errorCode in setOf("preview_stale", "preview_required")) {
                DispatchResult.Failure(requireNotNull(parsed.errorCode), definitelyRejected = true)
            } else if (error.code() == 404) DispatchResult.Failure(RULE_APPLICATION_UNVERIFIED)
            else mapOutboxHttpError(error.code(), parsed)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("连接中断，保留原应用等待核实。")
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            logNetworkWarning("operation=ApplyConfirmedRules unexpected replay failure", error)
            DispatchResult.Failure(RULE_APPLICATION_UNVERIFIED)
        }
    }
}
