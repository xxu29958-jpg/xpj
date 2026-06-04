package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * ADR-0041 P1 (review): an offline items-replace / acknowledge-mismatch replay
 * bumps the PARENT expense's ``row_version``. The items/ack wrapper response
 * now carries that fresh ``row_version`` directly, so the dispatchers read it
 * off the 2xx body (no second GET) and return it as
 * [DispatchResult.Success]'s ``newRowVersion`` so [OutboxDrainEngine] can
 * cascade the fresh token onto a chained same-target PENDING row (e.g.
 * items→confirm), preventing a spurious 409 on the follow-up.
 *
 * These pin that the dispatchers surface the PARENT's row_version (distinct
 * from the outbox row's own, now-stale, token). The engine's cascade of a
 * non-null Success is already covered by
 * [OutboxDrainEngineTest.successCascadesNewTokenToSameTargetPendingRows].
 */
class ItemsCascadeDispatcherTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private val parentRowVersion = 99L

    /**
     * Delegate-backed fake whose items / acknowledge-mismatch responses report
     * a parent ``row_version`` distinct from the outbox row's stale token (1L),
     * so a passing assertion proves the dispatcher reads ``row_version`` off
     * the response body rather than echoing the row's own token.
     */
    private fun apiWithParentRowVersion(): ApiService {
        val delegate = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        return object : ApiService by delegate {
            override suspend fun replaceExpenseItems(
                id: Long,
                request: ExpenseItemReplaceRequestDto,
            ): ExpenseItemsResponseDto = itemsResponseWithParentRowVersion(id)

            override suspend fun acknowledgeExpenseItemsMismatch(
                id: Long,
                request: ExpenseStateTokenRequest,
                idempotencyKey: String?,
            ): ExpenseItemsResponseDto = itemsResponseWithParentRowVersion(id)
        }
    }

    private fun itemsResponseWithParentRowVersion(id: Long): ExpenseItemsResponseDto =
        ExpenseItemsResponseDto(
            expenseId = id,
            rowVersion = parentRowVersion,
            parentAmountCents = 0L,
            itemsTotalAmountCents = 0L,
            mismatchCents = 0L,
            items = emptyList(),
        )

    private fun row(type: PendingMutationType, payloadJson: String): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = type,
        targetId = "expense:42",
        payloadJson = payloadJson,
        expectedRowVersion = 1L, // stale — distinct from the parent's 99L
        status = PendingMutationStatus.InFlight,
        retryCount = 1,
        lastError = null,
        createdAt = "2026-05-20T12:00:00.000Z",
        attemptedAt = "2026-05-20T12:00:00.000Z",
        completedAt = null,
        // ADR-0042: AcknowledgeItemsMismatch now requires a key (the dispatcher
        // fails a keyless row). ReplaceItems ignores it. Supply one so both
        // cascade tests exercise the success path.
        idempotencyKey = "key-cascade",
    )

    @Test
    fun `replaceItems dispatch surfaces parent row_version for cascade`() = runTest {
        val api = apiWithParentRowVersion()
        val payload = moshi.adapter(ExpenseItemReplaceRequestDto::class.java)
            .toJson(ExpenseItemReplaceRequestDto(expectedRowVersion = 0L, items = emptyList()))
        val dispatcher = ReplaceItemsDispatcher(
            apiProvider = { api },
            payloadAdapter = moshi.adapter(ExpenseItemReplaceRequestDto::class.java),
        )

        val result = dispatcher.dispatch(row(PendingMutationType.ReplaceItems, payload))

        assertEquals(DispatchResult.Success(newRowVersion = parentRowVersion), result)
    }

    @Test
    fun `acknowledgeMismatch dispatch surfaces parent row_version for cascade`() = runTest {
        val api = apiWithParentRowVersion()
        val payload = moshi.adapter(ExpenseStateTokenRequest::class.java)
            .toJson(ExpenseStateTokenRequest(expectedRowVersion = 0L))
        val dispatcher = AcknowledgeItemsMismatchDispatcher(
            apiProvider = { api },
            payloadAdapter = moshi.adapter(ExpenseStateTokenRequest::class.java),
        )

        val result = dispatcher.dispatch(row(PendingMutationType.AcknowledgeItemsMismatch, payload))

        assertEquals(DispatchResult.Success(newRowVersion = parentRowVersion), result)
    }
}
