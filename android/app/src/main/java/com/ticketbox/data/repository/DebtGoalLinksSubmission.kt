package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Presentation labels accompany the frozen command; they never supply financial facts. */
@JsonClass(generateAdapter = true)
data class DebtGoalLinksPayload(
    val goalName: String,
    val request: DebtGoalLinksReplaceRequestDto,
    val selectedLabels: Map<String, String>,
)

internal fun JsonAdapter<DebtGoalLinksPayload>.readDebtLinks(row: OutboxRow): DebtGoalLinksPayload? =
    runCatching { fromJson(row.payloadJson) }.getOrNull()?.takeIf {
        row.type == PendingMutationType.ReplaceGoalDebtLinks && row.targetId.startsWith("goal:") &&
            row.targetId.length > "goal:".length && !row.idempotencyKey.isNullOrBlank() &&
            row.expectedRowVersion > 0 && it.request.expectedRowVersion == row.expectedRowVersion &&
            it.request.debtPublicIds.isNotEmpty() && it.request.debtPublicIds.all(String::isNotBlank) &&
            it.request.debtPublicIds.distinct() == it.request.debtPublicIds
    }

internal fun DebtGoalLinksPayload.acceptsReceipt(row: OutboxRow, receipt: GoalDto): Boolean =
    receipt.ledgerId == row.ledgerId && row.targetId == "goal:${receipt.publicId}" &&
        receipt.goalType == "debt_repayment" && receipt.rowVersion == request.expectedRowVersion + 1 &&
        receipt.debtRepayment?.linkedDebts?.map { it.debtPublicId }?.toSet() == request.debtPublicIds.toSet()

/** The only Android writer for replacing links; the queue keeps body, binding, OCC and key. */
class ReplaceGoalDebtLinksDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<DebtGoalLinksPayload>,
    private val receiptAdapter: JsonAdapter<GoalDto>,
    private val onAccepted: suspend (OutboxRow) -> Unit,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.ReplaceGoalDebtLinks

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val original = payloadAdapter.readDebtLinks(row)
            ?: return DispatchResult.Failure("原关联修改无法读取，已保留记录，请核对。")
        return try {
            val receipt = apiProvider(row).replaceGoalDebtLinks(row.targetId.removePrefix("goal:"), original.request,
                idempotencyKey = row.idempotencyKey, timezone = null)
            if (!original.acceptsReceipt(row, receipt)) DispatchResult.Failure("返回的目标与原关联修改不匹配，已保留记录。")
            else {
                onAccepted(row)
                DispatchResult.Success(newRowVersion = receipt.rowVersion, receiptJson = receiptAdapter.toJson(receipt))
            }
        } catch (error: HttpException) {
            when (val result = mapOutboxHttpException(error)) {
                is DispatchResult.Discarded -> DispatchResult.Failure("目标无法读取，原关联修改已保留，请核对。", definitelyRejected = true)
                else -> result
            }
        } catch (error: IOException) {
            logNetworkWarning("operation=ReplaceGoalDebtLinks transport interrupted", error)
            DispatchResult.RetryableFailure("关联修改的连接中断，将继续核对原提交。")
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            logNetworkWarning("operation=ReplaceGoalDebtLinks replay failed", error)
            DispatchResult.Failure("关联修改的结果无法确认，已保留原提交，请核对。")
        }
    }
}
