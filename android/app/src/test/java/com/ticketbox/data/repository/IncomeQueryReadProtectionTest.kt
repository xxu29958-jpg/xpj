package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.IncomeQueryCacheDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class IncomeQueryReadProtectionTest {
    @Test fun unreadableDurableProtectionPreventsSendingTheCommand() = runTest {
        val fixture = GoalReadFixture()
        val cache = object : IncomeQueryCacheDao by FakeIncomeQueryCacheDao() {
            override suspend fun beginWrite(barrier: StatsProjectionCacheEntity): Boolean = throw SQLiteException("disk unavailable")
        }
        val reader = IncomeQueryReader(fixture.provider, cache, fixture.coordinator)
        var sends = 0
        val result = runCatching { reader.directWrite(fixture.binding) { sends++; "accepted" } }
        assertTrue(result.isFailure)
        assertEquals(0, sends)
    }

    @Test fun failedCacheCleanupDoesNotEraseTheReceivedSuccessAndItsBarrierSurvives() = runTest {
        val fixture = GoalReadFixture()
        val retained = FakeIncomeQueryCacheDao()
        val cache = object : IncomeQueryCacheDao by retained {
            override suspend fun finishWrite(barrier: StatsProjectionCacheEntity, accepted: Boolean) {
                throw SQLiteException("cleanup unavailable")
            }
        }
        val reader = IncomeQueryReader(fixture.provider, cache, fixture.coordinator)
        assertEquals("original accepted result", reader.directWrite(fixture.binding) { "original accepted result" })
        assertEquals(1, retained.barriers(logicalBindingAdapter.toJson(fixture.binding)).size)
    }

    @Test fun rejectedWritePermissionKeepsReadAuthorityAndPreviouslyObservedValues() = runTest {
        val fixture = GoalReadFixture()
        val cache = FakeIncomeQueryCacheDao()
        val key = logicalBindingAdapter.toJson(fixture.binding)
        val snapshot = StatsProjectionCacheEntity(key, fixture.binding.ledgerId, "income_list", "", "active", "", "UTC",
            "a previously validated response", "2026-09-28T10:00:00Z")
        cache.save(snapshot)
        val reader = IncomeQueryReader(fixture.provider, cache, fixture.coordinator)
        val failure = runCatching {
            reader.directWrite(fixture.binding) { throw HttpException(Response.error<Any>(403, """{"error":"forbidden"}""".toResponseBody())) }
        }.exceptionOrNull() as RepositoryException
        assertEquals(403, failure.httpStatusCode)
        assertNull(fixture.coordinator.snapshotAccessDenials.value)
        assertEquals(snapshot, cache.cached(key, "income_list", "active", cache.protection(key)))
        assertTrue(cache.barriers(key).isEmpty())
    }
}
