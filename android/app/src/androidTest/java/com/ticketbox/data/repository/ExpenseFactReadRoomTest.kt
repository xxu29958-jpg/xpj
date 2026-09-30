package com.ticketbox.data.repository

import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import com.ticketbox.data.remote.dto.ExpenseRevisionPageDto
import java.net.ConnectException
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

class ExpenseFactReadRoomTest {
    private var failure: Throwable? = null
    private val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext) { delegate ->
        object : ApiService by delegate {
            override suspend fun expenseFactBundle(id: String): ExpenseFactBundleDto {
                failure?.let { throw it }
                return delegate.expenseFactBundle(id)
            }
            override suspend fun expenseRevisions(id: Long, page: Int, pageSize: Int, snapshotRevision: Long?): ExpenseRevisionPageDto {
                failure?.let { throw it }
                return ExpenseRevisionPageDto(listOf(ExpenseRevisionDto("original-history", 1, "corrected", "核对小票",
                    listOf("note"), after = mapOf("note" to "已确认历史"), createdAt = "2026-09-30T00:00:00Z")), page, pageSize, 1, 1)
            }
        }
    }
    @After fun close() = fixture.close()

    @Test fun coldHistoryIsVisibleOfflineButKnown403SurvivesAnotherRoomReopenUntilFreshAuthorization() = runBlocking {
        val id = fixture.network.current.id
        val repository = fixture.reopen().expenseRepository
        val known = repository.fetchExpenseFactBundle(id).getOrThrow()
        val history = repository.fetchExpenseRevisions(id).getOrThrow()
        failure = ConnectException("offline")
        val cold = fixture.reopen().expenseRepository
        assertEquals(known.value, cold.fetchExpenseFactBundle(id).getOrThrow().value)
        val restored = cold.fetchExpenseRevisions(id).getOrThrow()
        assertTrue(restored.fromCache)
        assertEquals(history.value, restored.value)
        assertEquals(history.fetchedAt, restored.fetchedAt)
        assertTrue(cold.fetchExpenseFromLocalCache(id).isSuccess)
        failure = HttpException(Response.error<Any>(403, "{\"error\":\"forbidden\"}".toResponseBody()))
        assertTrue(cold.fetchExpenseFactBundle(id).isFailure)
        failure = ConnectException("offline")
        val denied = fixture.reopen().expenseRepository
        assertTrue(denied.fetchExpenseRevisions(id).isFailure)
        assertTrue(denied.fetchExpenseFromLocalCache(id).isFailure)
        failure = null
        assertTrue(!denied.fetchExpenseFactBundle(id).getOrThrow().fromCache)
        assertTrue(denied.fetchExpenseFromLocalCache(id).isSuccess)
    }
}
