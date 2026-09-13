package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class CategoryRuleDispatcherTest {
    @Test fun refusalConflictAndTransientHttpResponsesPreserveTheOriginalIntent() = runTest {
        val f = CategoryRuleCommandFixture()
        val id = f.repository.updateCategoryRule(f.binding, f.current.toDomain(), f.current.asRequest()).getOrThrow()
        val original = f.pending(id).row
        val errors = listOf(
            Triple(409, "idempotency_key_in_progress", DispatchResult.RetryableFailure::class),
            Triple(409, "state_conflict", DispatchResult.Conflict::class),
            Triple(422, "idempotency_key_reused", DispatchResult.Failure::class),
            Triple(404, "not_found", DispatchResult.Failure::class),
        )
        errors.forEach { (status, code, expected) ->
            val api = object : ApiService by f.api {
                override suspend fun updateCategoryRule(id: Long, request: CategoryRuleUpdateRequest,
                    idempotencyKey: String?): CategoryRuleDto {
                    assertEquals(original.idempotencyKey, idempotencyKey)
                    throw HttpException(retrofit2.Response.error<CategoryRuleDto>(status,
                        """{"error":"$code","message":"Synthetic failure"}""".toResponseBody("application/json".toMediaType())))
                }
            }
            val dispatcher = CategoryRuleDispatcher(original.type, { api },
                f.adapters.categoryRuleSubmissionAdapter, f.adapters.categoryRuleReceiptAdapter)
            assertEquals(expected, dispatcher.dispatch(original)::class)
        }
        assertEquals(original, f.pending(id).row)
    }

    @Test fun unsupportedCurrencyAndAlteredOccNeverReachTheApi() = runTest {
        val f = CategoryRuleCommandFixture()
        val id = f.repository.updateCategoryRule(f.binding, f.current.toDomain(), f.current.asRequest()).getOrThrow()
        val original = f.pending(id).row
        val dispatcher = f.dispatcher(PendingMutationType.UpdateCategoryRule)
        val currencyless = original.copy(payloadJson = original.payloadJson.replace("\"JPY\"", "null"))
        assertTrue(dispatcher.dispatch(currencyless) is DispatchResult.Failure)
        assertTrue(dispatcher.dispatch(original.copy(expectedRowVersion = 8)) is DispatchResult.Failure)
        assertTrue(dispatcher.dispatch(original.copy(idempotencyKey = "")) is DispatchResult.Failure)
        assertTrue(dispatcher.dispatch(original.copy(targetId = "category_rule:0")) is DispatchResult.Failure)
        assertEquals(0, f.calls)
    }
}
