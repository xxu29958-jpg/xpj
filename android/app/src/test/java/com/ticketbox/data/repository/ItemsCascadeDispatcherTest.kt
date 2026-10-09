package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals

/** The first receipt may advance our own chain, never past an unseen peer edit. */
class ItemsCascadeDispatcherTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val itemsAdapter = moshi.adapter(ExpenseItemReplaceRequestDto::class.java)
    private val splitsAdapter = moshi.adapter(ExpenseSplitReplaceRequestDto::class.java)
    private val ackAdapter = moshi.adapter(ExpenseStateTokenRequest::class.java)

    @Test
    fun acceptedSubtaskReplayLeavesTheNextOriginalIntentInConflictWithThePeer() = runTest {
        for (type in listOf(PendingMutationType.ReplaceItems, PendingMutationType.ReplaceSplits,
            PendingMutationType.AcknowledgeItemsMismatch)) {
            val api = AcceptedSubtaskApi()
            val dao = FakePendingMutationDao()
            val outbox = testOutboxRepository(dao)
            val engine = OutboxDrainEngine(outbox, listOf(
                ReplaceItemsDispatcher({ api }, itemsAdapter), ReplaceSplitsDispatcher({ api }, splitsAdapter),
                AcknowledgeItemsMismatchDispatcher({ api }, ackAdapter),
            ))
            val payload = when (type) {
                PendingMutationType.ReplaceItems -> itemsAdapter.toJson(ExpenseItemReplaceRequestDto(0, emptyList()))
                PendingMutationType.ReplaceSplits -> splitsAdapter.toJson(ExpenseSplitReplaceRequestDto(0, emptyList()))
                else -> ackAdapter.toJson(ExpenseStateTokenRequest(0))
            }
            val originalId = outbox.enqueue(type, "expense:42", payload, 1, "original-key")
            val followingPayload = itemsAdapter.toJson(ExpenseItemReplaceRequestDto(0, emptyList()))
            val followingId = outbox.enqueue(PendingMutationType.ReplaceItems, "expense:42", followingPayload, 1, "following-key")

            val result = engine.drainOnce()

            assertEquals(1, result.done)
            assertEquals(1, result.conflicts)
            assertEquals(PendingMutationStatus.Done.wireValue, dao.rows.getValue(originalId).status)
            val following = dao.rows.getValue(followingId)
            assertEquals(PendingMutationStatus.Conflict.wireValue, following.status)
            assertEquals(2L, following.expectedRowVersion)
            assertEquals("following-key", following.idempotencyKey)
            assertEquals(followingPayload, following.payload)
            assertEquals(3L, api.currentPeerVersion)
        }
    }

    /** Server accepted version 2, lost its reply, then a peer wrote version 3. */
    private class AcceptedSubtaskApi : ApiService by FakeApiService(mutableListOf(), 0) {
        var currentPeerVersion = 3L
            private set
        private fun originalItems() = ExpenseItemsResponseDto(expenseId = 42, rowVersion = 2,
            parentAmountCents = 1500, itemsTotalAmountCents = 500, mismatchCents = 1000, items = emptyList())

        override suspend fun replaceExpenseItems(id: String, request: ExpenseItemReplaceRequestDto,
            idempotencyKey: String?): ExpenseItemsResponseDto {
            if (idempotencyKey == "original-key") return originalItems()
            if (request.expectedRowVersion != currentPeerVersion) throw HttpException(Response.error<Any>(409,
                """{"error":"state_conflict","message":"账单已被其它端修改"}""".toResponseBody("application/json".toMediaType())))
            currentPeerVersion += 1
            return originalItems().copy(rowVersion = currentPeerVersion)
        }

        override suspend fun replaceExpenseSplits(id: String, request: ExpenseSplitReplaceRequestDto,
            idempotencyKey: String?): ExpenseSplitsResponseDto {
            assertEquals("original-key", idempotencyKey)
            return ExpenseSplitsResponseDto(expenseId = 42, rowVersion = 2,
                parentAmountCents = 1500, splitsTotalAmountCents = 500, mismatchCents = 1000, splits = emptyList())
        }

        override suspend fun acknowledgeExpenseItemsMismatch(id: String, request: ExpenseStateTokenRequest,
            idempotencyKey: String?): ExpenseItemsResponseDto {
            assertEquals("original-key", idempotencyKey)
            return originalItems().copy(itemsSumStatus = "mismatch_acknowledged")
        }
    }
}
