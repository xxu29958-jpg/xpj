package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto
import com.ticketbox.data.remote.dto.DebtGoalTargetDateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Presentation labels accompany the frozen command; they never supply financial facts. */
@JsonClass(generateAdapter = true)
data class DebtGoalEditPayload(
    val goalName: String,
    val request: DebtGoalLinksReplaceRequestDto? = null,
    val selectedLabels: Map<String, String> = emptyMap(),
    val dateRequest: DebtGoalTargetDateRequestDto? = null,
    val goalVersion: Int? = null,
)

internal fun JsonAdapter<DebtGoalEditPayload>.readDebtEdit(row: OutboxRow): DebtGoalEditPayload? =
    runCatching { fromJson(row.payloadJson) }.getOrNull()?.takeIf {
        row.targetId.startsWith("goal:") &&
            row.targetId.length > "goal:".length && !row.idempotencyKey.isNullOrBlank() &&
            row.expectedRowVersion > 0 && it.matchesCommand(row)
    }

private fun DebtGoalEditPayload.matchesCommand(row: OutboxRow): Boolean = when (row.type) {
    PendingMutationType.ReplaceGoalDebtLinks -> dateRequest == null && request?.let {
        it.expectedRowVersion == row.expectedRowVersion && it.debtPublicIds.isNotEmpty() &&
            it.debtPublicIds.all(String::isNotBlank) && it.debtPublicIds.distinct() == it.debtPublicIds
    } == true
    PendingMutationType.SetGoalTargetDate -> request == null && dateRequest?.let {
        it.expectedRowVersion == row.expectedRowVersion && goalVersion != null &&
            (it.targetDate == null || runCatching { java.time.LocalDate.parse(it.targetDate).toString() == it.targetDate }.getOrDefault(false))
    } == true
    else -> false
}

internal fun DebtGoalEditPayload.acceptsReceipt(row: OutboxRow, receipt: GoalDto): Boolean =
    receipt.ledgerId == row.ledgerId && row.targetId == "goal:${receipt.publicId}" &&
        receipt.goalType == "debt_repayment" && receipt.rowVersion == row.expectedRowVersion + 1 &&
        when (row.type) {
            PendingMutationType.ReplaceGoalDebtLinks ->
                receipt.debtRepayment?.linkedDebts?.map { it.debtPublicId }?.toSet() == request?.debtPublicIds?.toSet()
            PendingMutationType.SetGoalTargetDate -> receipt.debtRepayment?.let {
                it.targetDate == dateRequest?.targetDate && it.goalVersion == goalVersion
            } == true
            else -> false
        }

/** The only Android writer for debt goal edits; each queue row contains exactly one command. */
class DebtGoalEditDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<DebtGoalEditPayload>,
    private val receiptAdapter: JsonAdapter<GoalDto>,
    override val type: PendingMutationType = PendingMutationType.ReplaceGoalDebtLinks,
    private val onAccepted: suspend (OutboxRow) -> Unit,
) : OutboxMutationDispatcher {
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val original = payloadAdapter.readDebtEdit(row)?.takeIf { row.type == type }
            ?: return DispatchResult.Failure("原目标修改无法读取，已保留记录，请核对。")
        return try {
            val api = apiProvider(row)
            val id = row.targetId.removePrefix("goal:")
            val receipt = if (type == PendingMutationType.SetGoalTargetDate)
                api.setGoalTargetDate(id, requireNotNull(original.dateRequest), row.idempotencyKey, timezone = null)
            else api.replaceGoalDebtLinks(id, requireNotNull(original.request), row.idempotencyKey, timezone = null)
            if (!original.acceptsReceipt(row, receipt)) DispatchResult.Failure("返回的目标与原修改不匹配，已保留记录。")
            else {
                onAccepted(row)
                DispatchResult.Success(newRowVersion = receipt.rowVersion, receiptJson = receiptAdapter.toJson(receipt))
            }
        } catch (error: HttpException) {
            when (val result = mapOutboxHttpException(error)) {
                is DispatchResult.Discarded -> DispatchResult.Failure("目标无法读取，原修改已保留，请核对。", definitelyRejected = true)
                else -> result
            }
        } catch (error: IOException) {
            logNetworkWarning("operation=$type transport interrupted", error)
            DispatchResult.RetryableFailure("目标修改的连接中断，将继续核对原提交。")
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            logNetworkWarning("operation=$type replay failed", error)
            DispatchResult.Failure("目标修改的结果无法确认，已保留原提交，请核对。")
        }
    }
}
