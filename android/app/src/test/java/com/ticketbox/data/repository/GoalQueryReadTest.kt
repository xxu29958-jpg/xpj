package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.squareup.moshi.Moshi
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class GoalQueryReadTest {
    @Test fun listMakesUnvisitedDetailReadableAfterRepositoryRecreation() = runTest {
        val f = GoalReadFixture()
        val read = f.repository.goals("2026-09", timezone = "Asia/Tokyo").getOrThrow()
        assertFalse(read.fromCache)
        f.api.offline = true
        val reopened = f.repository
        val detail = reopened.goal("goal-jpy", timezone = "Asia/Tokyo").getOrThrow()
        assertEquals(read.value.single(), detail.value)
        assertEquals(read.fetchedAt, detail.fetchedAt)
        assertTrue(detail.fromCache)
        assertEquals("JPY", detail.value.homeCurrencyCode)
        assertNull(detail.value.spentAmountCents)
        assertNull(detail.value.progressPercent)
    }

    @Test fun emptyListReplacesItsOriginalMembershipAndRemainsReadable() = runTest {
        val f = GoalReadFixture()
        f.repository.goals("2026-09").getOrThrow()
        f.api.goals = emptyList()
        val empty = f.repository.goals("2026-09").getOrThrow()
        f.api.offline = true
        val saved = f.repository.goals("2026-09").getOrThrow()
        assertTrue(saved.fromCache)
        assertEquals(empty.value, saved.value)
        assertTrue(saved.value.isEmpty())
    }

    @Test fun querySnapshotsCannotCrossMonthArchiveTypeTimezoneOrBinding() = runTest {
        val f = GoalReadFixture()
        f.repository.goals("2026-09", timezone = "Asia/Tokyo").getOrThrow()
        f.api.offline = true
        assertTrue(f.repository.goals("2026-08", timezone = "Asia/Tokyo").isFailure)
        assertTrue(f.repository.goals("2026-09", includeArchived = true, timezone = "Asia/Tokyo").isFailure)
        assertTrue(f.repository.debtGoals(timezone = "Asia/Tokyo").isFailure)
        assertTrue(f.repository.goal("goal-jpy", timezone = "UTC").isFailure)
        assertTrue(f.repository.goal("never-read", timezone = "Asia/Tokyo").isFailure)
        val old = f.binding
        f.session.clear()
        f.session.saveToken("replacement-session")
        assertTrue(f.repository.goals("2026-09", expectedBinding = old, timezone = "Asia/Tokyo").isFailure)
        assertTrue(f.repository.goals("2026-09", timezone = "Asia/Tokyo").isFailure)
    }

    @Test fun httpRefusalsAreNotOfflineSuccessAndAccessDenialRetiresBothReadOwners() = runTest {
        for (status in listOf(401, 403, 404, 409, 502)) {
            val f = GoalReadFixture()
            f.repository.goals("2026-09").getOrThrow()
            val statsQuery = StatsQuery(f.binding, "2026-09")
            f.stats.monthlyStats(statsQuery).getOrThrow()
            f.api.failure = HttpException(Response.error<Any>(status, "".toResponseBody()))
            val refused = f.repository.goal("goal-jpy")
            assertTrue(refused.isFailure, "HTTP $status must remain a refusal")
            assertEquals(status, (refused.exceptionOrNull() as RepositoryException).httpStatusCode)
            f.api.failure = null
            f.api.offline = true
            if (status == 401 || status == 403) {
                assertTrue(f.repository.goals("2026-09").isFailure)
                assertTrue(f.stats.monthlyStats(statsQuery).isFailure)
            }
        }
    }

    @Test fun decodingFailureDoesNotMasqueradeAsTransportUnavailability() = runTest {
        val f = GoalReadFixture()
        f.repository.goals("2026-09").getOrThrow()
        val adapter = Moshi.Builder().build().adapter(Any::class.java)
        val decodingErrors = listOf("\"unterminated", "").map { body ->
            requireNotNull(runCatching { adapter.fromJson(body) }.exceptionOrNull())
        }
        assertTrue(decodingErrors.all { it is java.io.IOException })
        for (error in decodingErrors) {
            f.api.failure = error
            assertTrue(f.repository.goals("2026-09").isFailure)
        }
        f.api.failure = null
        f.api.offline = true
        assertTrue(f.repository.goals("2026-09").getOrThrow().fromCache)
    }

    @Test fun accessDenialStillRetiresSnapshotsWhenItsResponseBodyCannotBeRead() = runTest {
        val f = GoalReadFixture()
        f.repository.goals("2026-09").getOrThrow()
        val unreadableBody = object : okhttp3.ResponseBody() {
            override fun contentType(): okhttp3.MediaType? = null
            override fun contentLength() = 0L
            override fun source(): okio.BufferedSource = throw java.net.ConnectException("response body interrupted")
        }
        f.api.failure = HttpException(Response.error<Any>(403, unreadableBody))
        val denied = f.repository.goal("goal-jpy")
        assertEquals(403, (denied.exceptionOrNull() as RepositoryException).httpStatusCode)
        f.api.failure = null
        f.api.offline = true
        assertTrue(f.repository.goals("2026-09").isFailure)
    }

    @Test fun statsAccessDenialIsNotCachedSuccessAndAlsoRetiresGoalSnapshots() = runTest {
        val f = GoalReadFixture()
        val query = StatsQuery(f.binding, "2026-09")
        f.stats.monthlyStats(query).getOrThrow()
        f.repository.goals("2026-09").getOrThrow()
        f.api.failure = HttpException(Response.error<Any>(403, "".toResponseBody()))
        val denied = f.stats.monthlyStats(query)
        assertTrue(denied.isFailure)
        assertEquals(403, (denied.exceptionOrNull() as RepositoryException).httpStatusCode)
        f.api.failure = null
        f.api.offline = true
        assertTrue(f.stats.monthlyStats(query).isFailure)
        assertTrue(f.repository.goal("goal-jpy").isFailure)
    }

    @Test fun olderListCannotOverwriteANewerDetailOrListResponse() = runTest {
        val f = GoalReadFixture()
        val repository = f.repository
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        f.api.listResponder = { entered.complete(Unit); release.await(); GoalListResponseDto(listOf(readGoalDto())) }
        val earlier = async { repository.goals("2026-09") }
        entered.await()
        f.api.listResponder = null
        f.api.goals = listOf(readGoalDto().copy(name = "新目标", rowVersion = 3))
        val latest = repository.goals("2026-09").getOrThrow()
        repository.goal("goal-jpy").getOrThrow()
        release.complete(Unit)
        assertTrue(earlier.await().isFailure)
        f.api.offline = true
        assertEquals(latest.value, repository.goals("2026-09").getOrThrow().value)
        assertEquals("新目标", repository.goal("goal-jpy").getOrThrow().value.name)
    }

    @Test fun accessDenialOrExplicitClearPreventsAnInflightStatsReadFromPublishingOrRestoring() = runTest {
        for (deny in listOf(true, false)) {
            val f = GoalReadFixture()
            f.repository.goals("2026-09").getOrThrow()
            val query = StatsQuery(f.binding, "2026-09")
            val entered = CompletableDeferred<Unit>()
            val release = CompletableDeferred<Unit>()
            f.api.statsResponder = { entered.complete(Unit); release.await(); MonthlyStatsDto("JPY", month = "2026-09", totalAmountCents = 12, count = 1,
                byCategory = listOf(com.ticketbox.data.remote.dto.CategoryStatsDto("购物", 12, 1))) }
            val earlier = async { f.stats.monthlyStats(query) }
            entered.await()
            if (deny) {
                f.api.failure = HttpException(Response.error<Any>(403, "".toResponseBody()))
                assertTrue(f.repository.goal("goal-jpy").isFailure)
            } else f.stats.clearLocalCache()
            release.complete(Unit)
            assertTrue(earlier.await().isFailure)
            f.api.failure = null
            f.api.offline = true
            assertTrue(f.stats.monthlyStats(query).isFailure)
            assertTrue(f.repository.goals("2026-09").isFailure)
        }
    }
}
