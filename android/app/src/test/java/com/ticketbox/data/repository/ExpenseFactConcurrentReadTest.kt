package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import com.ticketbox.data.remote.dto.ExpenseRevisionPageDto
import java.net.ConnectException
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.test.runTest
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@RunWith(Parameterized::class)
internal class ExpenseFactConcurrentReadTest(private val query: String) : ExpensePendingRepositoryOutboxTestBase() {
    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun queries() = listOf("bundle", "history")
    }

    @Test
    fun startingAnotherReadDoesNotInvalidateASuccessfulFactRead() = runTest {
        val api = ConcurrentFactApi()
        val repository = buildRepository(api)
        val first = async { read(repository) }
        api.started[0].await()
        val second = async { read(repository) }
        api.started[1].await()
        try {
            api.replies[0].complete(1)
            assertEquals(expected(1), first.await().getOrThrow().value)
            api.replies[1].complete(2)
            assertEquals(expected(2), second.await().getOrThrow().value)
        } finally {
            api.replies.forEach { it.complete(2) }
        }
    }

    @Test
    fun lateReadSharesTheAcceptedFactAndCannotRevertTheOfflineSnapshot() = runTest {
        val api = ConcurrentFactApi()
        val repository = buildRepository(api)
        val first = async { read(repository) }
        api.started[0].await()
        val second = async { read(repository) }
        api.started[1].await()
        try {
            api.replies[1].complete(2)
            val accepted = second.await().getOrThrow()
            assertEquals(expected(2), accepted.value)
            api.replies[0].complete(1)
            val late = first.await().getOrThrow()
            assertEquals(accepted, late, "Both readers must receive the newer accepted net or revision history")
            assertFalse(late.fromCache)
            api.offline = true
            val reopened = read(repository).getOrThrow()
            assertTrue(reopened.fromCache)
            assertEquals(expected(2), reopened.value, "Late GET must not roll back the persistent fact read")
        } finally {
            api.replies.forEach { it.complete(2) }
        }
    }

    @Test
    fun cancellingACompetingPageReadDoesNotPoisonTheRemainingReader() = runTest {
        val api = ConcurrentFactApi()
        val repository = buildRepository(api)
        val first = async { read(repository) }
        api.started[0].await()
        val leavingPage = async { read(repository) }
        api.started[1].await()
        leavingPage.cancelAndJoin()
        api.replies[0].complete(2)
        assertEquals(expected(2), first.await().getOrThrow().value)
    }

    @Test
    fun knownAccessRefusalRetiresEvenTheSharedAcceptedSnapshot() = runTest {
        for (status in listOf(401, 403, 404)) {
            val api = ConcurrentFactApi()
            val repository = buildRepository(api)
            api.replies[0].complete(2)
            assertEquals(expected(2), read(repository).getOrThrow().value)
            val late = async { read(repository) }
            api.started[1].await()
            api.replies[2].completeExceptionally(retrofit2.HttpException(retrofit2.Response.error<Any>(status,
                okhttp3.ResponseBody.create(null, ""))))
            try {
                assertTrue(read(repository).isFailure)
                api.replies[1].complete(1)
                assertTrue(late.await().isFailure, "A late $query must not reuse a snapshot after HTTP $status")
                api.offline = true
                assertTrue(read(repository).isFailure, "The rejected fact must not reopen from its persisted history")
            } finally {
                api.replies.forEach { it.complete(2) }
            }
        }
    }

    private suspend fun read(repository: ExpenseRepository): Result<ReadSnapshot<Any>> = when (query) {
        "bundle" -> repository.fetchExpenseFactBundle(9).map { ReadSnapshot(it.value, it.fetchedAt, it.fromCache) }
        else -> repository.fetchExpenseRevisions(9).map { ReadSnapshot(it.value, it.fetchedAt, it.fromCache) }
    }

    private fun expected(version: Int): Any = when (query) {
        "bundle" -> bundle(version).toDomain()
        else -> history(version).toDomain()
    }

    private class ConcurrentFactApi : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
        val started = List(3) { CompletableDeferred<Unit>() }
        val replies = List(3) { CompletableDeferred<Int>() }
        private val calls = AtomicInteger()
        @Volatile var offline = false

        private suspend fun version(): Int {
            if (offline) throw ConnectException("offline")
            val call = calls.getAndIncrement()
            started[call].complete(Unit)
            return replies[call].await()
        }

        override suspend fun expenseFactBundle(id: String): ExpenseFactBundleDto = bundle(version())
        override suspend fun expenseRevisions(id: Long, page: Int, pageSize: Int, snapshotRevision: Long?):
            ExpenseRevisionPageDto = history(version())
    }
}

private fun bundle(version: Int): ExpenseFactBundleDto {
    val amount = if (version == 1) 1_200L else 1_725L
    val wire = expenseFactBundleDtoFixture(root = confirmedExpenseDtoFixture(
        ConfirmedExpenseFixture(amountCents = amount, rowVersion = version.toLong())),
        rootStreamAmountCents = amount, lineageHomeNetCents = amount - 300)
    return wire.copy(financialSummary = wire.financialSummary.copy(grossOriginalMinor = amount,
        grossHomeAmountCents = amount, remainingRefundableOriginalMinor = amount - 300))
}

private fun history(version: Int) = ExpenseRevisionPageDto((version downTo 1).map {
    ExpenseRevisionDto("revision-$it", it.toLong(), "corrected", "核对 $it", listOf("note"),
        after = mapOf("note" to "历史 $it"), createdAt = "2026-10-01T00:00:00Z")
}, 1, 50, version, version.toLong())
