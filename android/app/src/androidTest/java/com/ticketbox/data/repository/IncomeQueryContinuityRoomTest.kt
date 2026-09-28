package com.ticketbox.data.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.data.remote.dto.IncomePlanListResponseDto
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** A fresh repository graph must recover actual GETs from disk, not from original write receipts. */
class IncomeQueryContinuityRoomTest {
    private val fixture = IncomePlanConnectedFixture(ApplicationProvider.getApplicationContext<Context>())

    @After fun close() = fixture.close()

    @Test fun previouslyReadIncomeForecastSurvivesDatabaseCloseAndOfflineReopenWithoutInventingWrites() = runBlocking {
        val first = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(first.observeActiveLedgerAccess().first()).binding
        val observed = first.listActive(binding).getOrThrow()
        assertEquals("2026-09", observed.month)
        assertEquals(10_000L, observed.expectedAmountCents)
        fixture.advanceToOctober()
        fixture.network.failReads = true
        val reopened = fixture.reopen().incomePlanRepository.listActive(binding)
        assertTrue("A known income forecast disappeared after an offline process-style reopen: ${reopened.exceptionOrNull()}", reopened.isSuccess)
        val retained = reopened.getOrThrow()
        assertTrue(retained.fromCache)
        assertEquals(observed.fetchedAt, retained.fetchedAt)
        assertEquals(observed.plans, retained.plans)
        assertEquals(observed.month, retained.month)
        assertEquals(observed.expectedAmountCents, retained.expectedAmountCents)
        assertTrue(fixture.stored().isEmpty())
        assertTrue(fixture.network.creationCalls.isEmpty() && fixture.network.calls.isEmpty())
    }

    @Test fun previouslyReadIncomeDefinitionsSurviveOfflineReopenWithoutConsultingCurrentPlanAsHistory() = runBlocking {
        val first = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(first.observeActiveLedgerAccess().first()).binding
        val observed = first.history(binding, "income-1", null).getOrThrow()
        assertEquals("八月工资预测", observed.value.items.single().snapshot.label)
        fixture.network.current = fixture.network.current.copy(label = "现在的另一名称", amountCents = 99_999)
        fixture.network.failReads = true
        val reopened = fixture.reopen().incomePlanRepository.history(binding, "income-1", null)
        assertTrue("Read definitions disappeared after an offline reopen: ${reopened.exceptionOrNull()}", reopened.isSuccess)
        assertEquals(observed.value, reopened.getOrThrow().value)
        assertEquals(observed.fetchedAt, reopened.getOrThrow().fetchedAt)
        assertTrue(reopened.getOrThrow().fromCache)
        assertTrue(fixture.stored().isEmpty())
        assertTrue(fixture.network.creationCalls.isEmpty() && fixture.network.calls.isEmpty())
    }

    @Test fun unknownWriteRetiresPriorReadsButCurrentQueryNeverAcknowledgesOrRewritesOriginalSubmission() = runBlocking {
        var repo = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repo.observeActiveLedgerAccess().first()).binding
        val baseline = repo.listActive(binding).getOrThrow().plans.single()
        repo.history(binding, baseline.publicId, null).getOrThrow()
        repo.enqueueUpdate(binding, baseline, IncomePlanPatch("2026-09", baseline.rowVersion, amountCents = 12_000), CurrencyCode.CNY).getOrThrow()
        val original = fixture.stored().single()
        assertEquals(1, fixture.drain(maxAttempts = 1).failures)
        fixture.network.failReads = true
        repo = fixture.reopen().incomePlanRepository
        assertTrue(repo.listActive(binding).isFailure)
        assertTrue(repo.history(binding, baseline.publicId, null).isFailure)
        fixture.network.failReads = false
        repo.history(binding, baseline.publicId, null).getOrThrow()
        fixture.network.failReads = true
        assertTrue("A history page cannot reconcile an interrupted write", repo.history(binding, baseline.publicId, null).isFailure)
        fixture.network.failReads = false
        val reconciled = repo.listActive(binding).getOrThrow()
        assertEquals(12_000L, reconciled.expectedAmountCents)
        assertFalse(reconciled.fromCache)
        assertEquals("failed", fixture.stored().single()["status"])
        val pending = repo.observeSubmissions(binding).first().single()
        repo.recoverSubmission(binding, pending, drop = false).getOrThrow()
        fixture.network.loseResponse = false
        assertEquals(1, fixture.drain().done)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        for (key in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId")) {
            assertEquals(original[key], fixture.stored().single()[key])
        }
        fixture.network.failReads = true
        repo = fixture.reopen().incomePlanRepository
        assertTrue("The accepted original receipt must not substitute for a GET", repo.listActive(binding).isFailure)
        assertEquals("done", fixture.stored().single()["status"])
    }

    @Test fun latePreArchiveReadCannotReintroduceActivePlanAndRestoreRetiresArchivedSnapshot() = runBlocking {
        val repo = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repo.observeActiveLedgerAccess().first()).binding
        val original = fixture.network.current
        repo.listActive(binding).getOrThrow()
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        fixture.network.listing = {
            started.complete(Unit); release.await()
            IncomePlanListResponseDto(listOf(original), 10_000, "2026-09", 10_000, 1, 10_000, homeCurrencyCode = "CNY")
        }
        val late = async { repo.listActive(binding) }
        started.await()
        fixture.network.loseResponse = false
        val archived = repo.archive(binding, original.publicId, original.rowVersion, "2026-09").getOrThrow()
        release.complete(Unit)
        assertTrue(late.await().isFailure)
        fixture.network.listing = null
        fixture.network.failReads = true
        assertTrue(repo.listActive(binding).isFailure)
        fixture.network.failReads = false
        val knownArchived = repo.listIncluding(binding, IncomePlanStatus.ARCHIVED).getOrThrow()
        assertEquals(listOf(archived), knownArchived.value)
        fixture.network.failReads = true
        assertEquals(knownArchived.copy(fromCache = true), fixture.reopen().incomePlanRepository.listIncluding(binding, IncomePlanStatus.ARCHIVED).getOrThrow())
        val reopened = fixture.reopen().incomePlanRepository
        reopened.restore(binding, archived.publicId, archived.rowVersion, "2026-09").getOrThrow()
        assertTrue(reopened.listIncluding(binding, IncomePlanStatus.ARCHIVED).isFailure)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test fun deniedHistoryRetiresAllIncomeSnapshotsAcrossReopenWhileOriginalIntentRemains() = runBlocking {
        var repo = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repo.observeActiveLedgerAccess().first()).binding
        val baseline = repo.listActive(binding).getOrThrow().plans.single()
        repo.enqueueUpdate(binding, baseline, IncomePlanPatch("2026-09", baseline.rowVersion, amountCents = 12_000), CurrencyCode.CNY).getOrThrow()
        val original = fixture.stored().single()
        for (status in listOf(401, 403)) {
            fixture.network.failReads = false
            fixture.network.readFailure = null
            repo.listActive(binding).getOrThrow()
            repo.listIncluding(binding, IncomePlanStatus.ARCHIVED).getOrThrow()
            repo.history(binding, baseline.publicId, null).getOrThrow()
            fixture.network.readFailure = HttpException(Response.error<Any>(status, """{"error":"forbidden"}""".toResponseBody()))
            assertEquals(status, (repo.history(binding, baseline.publicId, null).exceptionOrNull() as RepositoryException).httpStatusCode)
            fixture.network.failReads = true
            repo = fixture.reopen().incomePlanRepository
            assertTrue(repo.listActive(binding).isFailure)
            assertTrue(repo.listIncluding(binding, IncomePlanStatus.ARCHIVED).isFailure)
            assertTrue(repo.history(binding, baseline.publicId, null).isFailure)
            assertEquals(original, fixture.stored().single())
        }
        assertTrue(fixture.network.calls.isEmpty())
    }

    @Test fun historyPagesRetainTheirOriginalCursorAndDefinitionsOnDisk() = runBlocking {
        val repo = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repo.observeActiveLedgerAccess().first()).binding
        val definition = fixture.network.service.incomePlanHistory("income-1", 20, null)
        fixture.network.history = { before ->
            if (before == null) definition.copy(nextBeforeVersion = 2) else {
                check(before == 2L)
                definition.copy(items = listOf(definition.items.single().copy(rowVersion = 1, changeKind = "baseline",
                    intentMonth = null, effectiveMonth = null, snapshot = definition.items.single().snapshot.copy(homeCurrencyCode = null))))
            }
        }
        val first = repo.history(binding, "income-1", null).getOrThrow()
        val second = repo.history(binding, "income-1", 2).getOrThrow()
        fixture.network.failReads = true
        val reopened = fixture.reopen().incomePlanRepository
        assertEquals(first.copy(fromCache = true), reopened.history(binding, "income-1", null).getOrThrow())
        assertEquals(second.copy(fromCache = true), reopened.history(binding, "income-1", 2).getOrThrow())
        assertTrue(reopened.history(binding, "income-1", 1).isFailure)
        assertEquals(null, second.value.items.single().intentMonth)
        assertEquals(null, second.value.items.single().snapshot.homeCurrencyCode)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test fun sameLedgerUnderAnotherAccountCannotReadThePreviousAccountsSnapshots() = runBlocking {
        val repo = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repo.observeActiveLedgerAccess().first()).binding
        repo.listActive(binding).getOrThrow()
        repo.history(binding, "income-1", null).getOrThrow()
        fixture.changeAccount()
        fixture.network.failReads = true
        val reopened = fixture.reopen().incomePlanRepository
        val other = requireNotNull(reopened.observeActiveLedgerAccess().first()).binding
        assertFalse(binding == other)
        assertTrue(reopened.listActive(other).isFailure)
        assertTrue(reopened.history(other, "income-1", null).isFailure)
        assertTrue(reopened.listActive(binding).isFailure)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test fun malformedFreshResponseDoesNotMasqueradeAsOfflineSuccessOrReplaceLastKnownMonth() = runBlocking {
        val repo = fixture.reopen().incomePlanRepository
        val binding = requireNotNull(repo.observeActiveLedgerAccess().first()).binding
        val known = repo.listActive(binding).getOrThrow()
        fixture.network.month = "invalid-month"
        assertTrue(repo.listActive(binding).isFailure)
        fixture.network.failReads = true
        val retained = fixture.reopen().incomePlanRepository.listActive(binding).getOrThrow()
        assertEquals(known.copy(fromCache = true), retained)
        assertTrue(fixture.stored().isEmpty())
    }
}
