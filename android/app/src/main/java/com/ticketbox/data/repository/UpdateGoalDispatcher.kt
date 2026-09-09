package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

/** Replays the original goal edit and accepts only its matching committed receipt. */
class UpdateGoalDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<GoalUpdateRequestDto>,
    private val receiptAdapter: JsonAdapter<GoalDto>,
    private val onAccepted: suspend (OutboxRow) -> Unit,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.UpdateGoal

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val publicId = parseGoalPublicId(row.targetId)
            ?: return DispatchResult.Failure("原目标无法确认，已保留未发送的修改，请核对。")
        if (row.expectedRowVersion <= 0) return DispatchResult.Failure("原目标版本无法确认，请保留记录并核对。")

        // ADR-0042: an UpdateGoal row MUST carry an idempotency key (every
        // enqueue mints one). A null key means a malformed / pre-ADR-0042 row
        // the server would 422 anyway — surface it as a visible FAILED row the
        // user can drop, not a silent server round-trip + Discard.
        val idempotencyKey = row.idempotencyKey?.takeIf { it.isNotBlank() }
            ?: return DispatchResult.Failure("UpdateGoal row missing idempotency key")

        val request = payloadAdapter.readGoalUpdate(row)
            ?: return DispatchResult.Failure("原修改内容无法读取，已保留记录，请核对。")
        if (!request.hasCapturedGoalCurrency()) return DispatchResult.Failure("原修改缺少可确认的币种，原金额已保留，请核对。")

        return try {
            val updated = apiProvider(row).updateGoal(publicId, request, idempotencyKey, timezone = null)
            if (!request.acceptsGoalReceipt(row, updated)) {
                DispatchResult.Failure("返回的目标与原提交不匹配，已保留记录。")
            } else {
                onAccepted(row)
                DispatchResult.Success(newRowVersion = updated.rowVersion, receiptJson = receiptAdapter.toJson(updated))
            }
        } catch (e: HttpException) {
            mapOutboxHttpException(e)
        } catch (e: IOException) {
            DispatchResult.RetryableFailure(e.message ?: "network IO failure")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DispatchResult.Failure(e.message ?: "PATCH goal threw")
        }
    }

    private fun parseGoalPublicId(targetId: String): String? {
        val prefix = "goal:"
        if (!targetId.startsWith(prefix)) return null
        val publicId = targetId.removePrefix(prefix)
        return publicId.takeIf { it.isNotBlank() }
    }
}

/** Reads existing flat payloads without changing their durable body or original OCC. */
internal fun JsonAdapter<GoalUpdateRequestDto>.readGoalUpdate(row: OutboxRow): GoalUpdateRequestDto? =
    try {
        fromJson(row.payloadJson)?.takeIf { row.expectedRowVersion > 0 && !row.idempotencyKey.isNullOrBlank() &&
            (it.expectedRowVersion == 0L || it.expectedRowVersion == row.expectedRowVersion) }
            ?.copy(expectedRowVersion = row.expectedRowVersion)
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }

internal fun GoalUpdateRequestDto.hasCapturedGoalCurrency(): Boolean =
    homeCurrencyCode != null && CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)?.storageKey == homeCurrencyCode

internal fun GoalUpdateRequestDto.acceptsGoalReceipt(row: OutboxRow, receipt: GoalDto): Boolean {
    val requestedFields = listOf(name to receipt.name, month to receipt.month,
        targetAmountCents to receipt.targetAmountCents, category to receipt.category.orEmpty())
    return hasCapturedGoalCurrency() && receipt.ledgerId == row.ledgerId && row.targetId == "goal:${receipt.publicId}" &&
        receipt.goalType == "spending_limit" && receipt.homeCurrencyCode == homeCurrencyCode &&
        receipt.rowVersion == expectedRowVersion + 1 &&
        requestedFields.all { (original, accepted) -> original == null || original == accepted }
}
