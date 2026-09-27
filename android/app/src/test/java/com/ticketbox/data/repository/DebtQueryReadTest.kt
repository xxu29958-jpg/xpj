package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.DebtKindSetRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalListResponseDto
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.domain.model.DebtListLens
import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.ExpenseDao
import java.net.ConnectException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DebtQueryReadTest {
    @Test fun aReadRefusalDuringDirectDispatchCannotTurnTheOriginalRealAckIntoFailureOrRestoreOldReads() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        val reader = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val repository = DebtRepository(fixture.provider, reader)
        repository.getDebt("jpy-debt").getOrThrow()
        val getStarted = CompletableDeferred<Unit>()
        val refuseGet = CompletableDeferred<Unit>()
        api.detail = { getStarted.complete(Unit); refuseGet.await()
            throw HttpException(Response.error<Any>(403, """{"error":"forbidden"}""".toResponseBody())) }
        val get = async { repository.getDebt("jpy-debt") }
        getStarted.await()
        val postStarted = CompletableDeferred<Unit>()
        val ack = CompletableDeferred<Unit>()
        api.commandReplyGate = { postStarted.complete(Unit); ack.await() }
        val post = async { repository.setDebtKind("jpy-debt", 4, "installment") }
        postStarted.await()
        refuseGet.complete(Unit)
        assertEquals(403, (get.await().exceptionOrNull() as RepositoryException).httpStatusCode)
        assertEquals(1, fixture.dao.debtDirectBarriers(logicalBindingAdapter.toJson(fixture.binding)).size,
            "Refusal retires read payloads while preserving the executing command's evidence")
        ack.complete(Unit)
        assertEquals(5L, post.await().getOrThrow().rowVersion)
        api.offline = true
        assertTrue(DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator).detail(fixture.binding, "jpy-debt").isFailure)
        assertEquals(1, api.commands)
        api.offline = false
        assertEquals(5L, reader.detail(fixture.binding, "jpy-debt").getOrThrow().value.rowVersion)
    }

    @Test fun directUnauthorizedPersistsSharedRefusalWhileWriteOnlyForbiddenAndConflictKeepTheOriginalRead() = runTest {
        for (status in listOf(401, 403, 409)) {
            val api = DebtReadApi()
            val fixture = GoalReadFixture { api }
            val settings = boundSettingsStore()
            val dao = object : ExpenseDao by fixture.dao {
                override suspend fun clearReadSnapshotsForBinding(bindingKey: String) { throw SQLiteException("Read cleanup unavailable") }
            }
            fun coordinator() = LocalLedgerSessionCoordinator(settings, fixture.session.sessionStore, dao)
            val repository = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, dao, coordinator()))
            val original = repository.getDebt("jpy-debt").getOrThrow()
            api.commandFailure = HttpException(Response.error<Any>(status, """{"error":"write_refused"}""".toResponseBody()))
            assertEquals(status, (repository.setDebtKind("jpy-debt", 4, "installment").exceptionOrNull() as RepositoryException).httpStatusCode)
            api.offline = true
            val result = DebtQueryReader(fixture.provider, dao, coordinator()).detail(fixture.binding, "jpy-debt")
            if (status == 401) assertTrue(result.isFailure)
            else assertEquals(original.copy(fromCache = true), result.getOrThrow())
            assertEquals(1, api.commands)
        }
    }

    @Test fun anotherReaderCannotConsumeAStillExecutingDirectTokenBeforeItsAckAndFailedCleanup() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        var cleanupFails = false
        val queryDao = object : ExpenseDao by fixture.dao {
            override suspend fun settleDebtDirectReads(bindingKey: String, ledgerId: String, tokens: List<String>, expectedEpoch: Long?) {
                if (cleanupFails) throw SQLiteException("Debt read DELETE failed")
                fixture.dao.settleDebtDirectReads(bindingKey, ledgerId, tokens, expectedEpoch)
            }
        }
        val first = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, queryDao, fixture.coordinator))
        val original = first.getDebt("jpy-debt").getOrThrow()
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        api.commandReplyGate = { started.complete(Unit); release.await() }
        val write = async { first.setDebtKind("jpy-debt", 4, "installment") }
        started.await()
        val second = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, queryDao, fixture.coordinator))
        assertEquals(5L, second.getDebt("jpy-debt").getOrThrow().value.rowVersion)
        assertEquals(1, queryDao.debtDirectBarriers(logicalBindingAdapter.toJson(fixture.binding)).size)
        assertEquals(original.fetchedAt, fixture.dao.statsProjections(logicalBindingAdapter.toJson(fixture.binding),
            "debt_detail", "", "jpy-debt", "UTC").single().fetchedAt)
        cleanupFails = true
        release.complete(Unit)
        assertEquals(5L, write.await().getOrThrow().rowVersion)
        api.offline = true
        val reopened = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, queryDao, fixture.coordinator))
        assertTrue(reopened.getDebt("jpy-debt").isFailure)
        assertEquals(1, api.commands)
    }

    @Test fun getStartedBeforeDirectAcceptanceCannotReconcileItsFailedCleanupWithAnOldDebt() = runTest {
        val api = DebtReadApi()
        val postStarted = CompletableDeferred<Unit>()
        val accept = CompletableDeferred<Unit>()
        val fixture = GoalReadFixture { object : ApiService by api {
            override suspend fun setDebtKind(publicId: String, request: DebtKindSetRequestDto, idempotencyKey: String?): DebtDto {
                postStarted.complete(Unit)
                accept.await()
                return api.setDebtKind(publicId, request, idempotencyKey)
            }
        } }
        var cleanupFails = false
        val dao = object : ExpenseDao by fixture.dao {
            override suspend fun settleDebtDirectReads(bindingKey: String, ledgerId: String, tokens: List<String>, expectedEpoch: Long?) {
                if (cleanupFails) throw SQLiteException("Accepted read cleanup unavailable")
                fixture.dao.settleDebtDirectReads(bindingKey, ledgerId, tokens, expectedEpoch)
            }
        }
        fun repository() = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, dao, fixture.coordinator))
        repository().getDebt("jpy-debt").getOrThrow()
        val post = async { repository().setDebtKind("jpy-debt", 4, "installment") }
        postStarted.await()
        val getStarted = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        api.detail = { val old = readDebt(); getStarted.complete(Unit); release.await(); old }
        val old = async { repository().getDebt("jpy-debt") }
        getStarted.await()
        cleanupFails = true
        try { accept.complete(Unit); assertEquals(5L, post.await().getOrThrow().rowVersion) }
        finally { release.complete(Unit) }
        assertTrue(old.await().isFailure, "A GET issued before the type change committed cannot consume its later accepted barrier")
        api.offline = true
        assertTrue(repository().getDebt("jpy-debt").isFailure)
        cleanupFails = false
        api.offline = false
        val current = repository().getDebt("jpy-debt").getOrThrow()
        assertEquals("installment", current.value.debtKind)
        assertEquals("JPY", current.value.homeCurrencyCode)
        assertFalse(current.fromCache)
        assertEquals(1, api.commands)
    }

    @Test fun proposalReadRefusalRetiresTheSameDebtSnapshotWithoutAddingAnOfflineProposalCache() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        val repository = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        repository.getDebt("jpy-debt").getOrThrow()
        val task = DebtTask(fixture.binding, "jpy-debt")
        assertEquals(emptyList(), repository.proposals.listRepaymentProposals(task).getOrThrow())
        api.failure = HttpException(Response.error<Any>(403, """{"error":"forbidden"}""".toResponseBody()))
        assertEquals(403, (repository.proposals.listRepaymentProposals(task).exceptionOrNull() as RepositoryException).httpStatusCode)
        api.failure = null
        api.offline = true
        val reopened = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        assertTrue(reopened.getDebt("jpy-debt").isFailure)
        assertTrue(reopened.proposals.listRepaymentProposals(task).isFailure)
        api.offline = false
        assertFalse(reopened.getDebt("jpy-debt").getOrThrow().fromCache)
        assertEquals(0, api.commands)
    }

    @Test fun failedAcceptedOutboxPublicationBlocksOldReadsUntilTheOriginalDeliverySettles() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        var unpublished = false
        val queryDao = object : ExpenseDao by fixture.dao {
            override suspend fun hasUnpublishedAcceptedDebt(ownerKey: String, ledgerId: String) = unpublished
        }
        val reader = DebtQueryReader(fixture.provider, queryDao, fixture.coordinator)
        reader.detail(fixture.binding, "jpy-debt").getOrThrow()
        unpublished = true
        api.offline = true
        val reopened = DebtQueryReader(fixture.provider, queryDao, fixture.coordinator)
        assertTrue(reopened.detail(fixture.binding, "jpy-debt").isFailure)
        api.offline = false
        api.detail = { readDebt().copy(rowVersion = 5, remainingAmountCents = 600) }
        assertEquals(600L, reopened.detail(fixture.binding, "jpy-debt").getOrThrow().value.remainingAmountCents)
        api.offline = true
        assertTrue(reopened.detail(fixture.binding, "jpy-debt").isFailure)
        reopened.invalidate(fixture.binding)
        unpublished = false
        api.offline = false
        val restored = reopened.detail(fixture.binding, "jpy-debt").getOrThrow()
        api.offline = true
        assertEquals(restored.fetchedAt, reopened.detail(fixture.binding, "jpy-debt").getOrThrow().fetchedAt)
        assertEquals(0, api.commands)
    }

    @Test fun originalCurrencyAndReadTimeSurviveReaderRecreationButUnknownDebtDoesNotExistOffline() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        val reader = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val first = reader.detail(fixture.binding, "jpy-debt").getOrThrow()
        assertFalse(first.fromCache)
        api.offline = true
        val reopened = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val saved = reopened.detail(fixture.binding, "jpy-debt").getOrThrow()
        assertTrue(saved.fromCache)
        assertEquals(first.value, saved.value)
        assertEquals(first.fetchedAt, saved.fetchedAt)
        assertEquals(1200L, saved.value.originalAmountMinor)
        assertEquals("JPY", saved.value.homeCurrencyCode)
        assertTrue(reopened.detail(fixture.binding, "never-read").isFailure)
    }

    @Test fun resourceNotFoundSurvivesRecreationWithoutRevokingAnotherDebtAndFreshDetailRestoresIt() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        var deletionFails = true
        val queryDao = object : ExpenseDao by fixture.dao {
            override suspend fun clearDebtResourceSnapshots(bindingKey: String, publicId: String) {
                if (deletionFails) throw SQLiteException("Debt read DELETE failed")
                fixture.dao.clearDebtResourceSnapshots(bindingKey, publicId)
            }
        }
        val reader = DebtQueryReader(fixture.provider, queryDao, fixture.coordinator)
        reader.list(fixture.binding, DebtListLens.Ledger).getOrThrow()
        reader.detail(fixture.binding, "jpy-debt").getOrThrow()
        api.failure = HttpException(Response.error<Any>(404, """{"error":"debt_not_found"}""".toResponseBody()))
        assertEquals(404, (reader.detail(fixture.binding, "jpy-debt").exceptionOrNull() as RepositoryException).httpStatusCode)
        api.failure = null
        api.offline = true
        val reopened = DebtQueryReader(fixture.provider, queryDao, fixture.coordinator)
        assertTrue(reopened.detail(fixture.binding, "jpy-debt").isFailure)
        val list = reopened.list(fixture.binding, DebtListLens.Ledger).getOrThrow()
        assertEquals(listOf("other-debt"), list.value.debts.map { it.publicId })
        assertTrue(list.fromCache)
        deletionFails = false
        api.offline = false
        assertFalse(reopened.detail(fixture.binding, "jpy-debt").getOrThrow().fromCache)
        api.offline = true
        assertEquals("jpy-debt", reopened.detail(fixture.binding, "jpy-debt").getOrThrow().value.publicId)
    }

    @Test fun cachedDebtTakenBeforeAnotherOwnersAcceptedChangeCannotBePublishedAfterIt() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        val cached = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var pauseCachedRead = false
        val queryDao = object : ExpenseDao by fixture.dao {
            override suspend fun debtSnapshotIfCurrent(query: StatsProjectionCacheEntity, epoch: Long): StatsProjectionCacheEntity? {
                val saved = fixture.dao.debtSnapshotIfCurrent(query, epoch)
                if (pauseCachedRead) { cached.complete(Unit); release.await() }
                return saved
            }
        }
        val reader = DebtQueryReader(fixture.provider, queryDao, fixture.coordinator)
        val original = reader.detail(fixture.binding, "jpy-debt").getOrThrow()
        pauseCachedRead = true
        api.offline = true
        val old = async { reader.detail(fixture.binding, "jpy-debt") }
        cached.await()
        try {
            api.offline = false
            val other = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
            assertEquals("installment", other.setDebtKind("jpy-debt", original.value.rowVersion, "installment").getOrThrow().debtKind)
        } finally { release.complete(Unit) }
        assertTrue(old.await().isFailure, "A retrieved old cache row cannot outlive another owner's accepted type change")
        pauseCachedRead = false
        val fresh = reader.detail(fixture.binding, "jpy-debt").getOrThrow()
        assertEquals("installment", fresh.value.debtKind)
        assertEquals("JPY", fresh.value.homeCurrencyCode)
        assertEquals(1200L, fresh.value.originalAmountMinor)
        assertFalse(fresh.fromCache)
        assertEquals(1, api.commands)
    }

    @Test fun acceptedWriteRetiresPersistedAndInFlightReadsAcrossDifferentReadersWithoutSeedingAQuery() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        val reader = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        reader.detail(fixture.binding, "jpy-debt").getOrThrow()
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        api.detail = { val captured = readDebt(); started.complete(Unit); release.await(); captured }
        val old = async { reader.detail(fixture.binding, "jpy-debt") }
        started.await()
        DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator).invalidate(fixture.binding)
        release.complete(Unit)
        assertTrue(old.await().isFailure)
        api.offline = true
        val reopened = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        assertTrue(reopened.detail(fixture.binding, "jpy-debt").isFailure)
        api.offline = false
        api.detail = { readDebt().copy(rowVersion = 5, remainingAmountCents = 600) }
        val fresh = reopened.detail(fixture.binding, "jpy-debt").getOrThrow()
        assertEquals(600L, fresh.value.remainingAmountCents)
        api.offline = true
        assertEquals(fresh.fetchedAt, reopened.detail(fixture.binding, "jpy-debt").getOrThrow().fetchedAt)
    }

    @Test fun laterOlderReadReturnsTheAcceptedNewerQueryAndItsOriginalSourceEvenWhenPublicationFails() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        var saveFails = false
        val queryDao = object : ExpenseDao by fixture.dao {
            override suspend fun saveDebtSnapshotIfCurrent(snapshot: StatsProjectionCacheEntity, epoch: Long, restoredPublicId: String?) {
                if (saveFails) throw SQLiteException("Debt snapshot write failed")
                fixture.dao.saveDebtSnapshotIfCurrent(snapshot, epoch, restoredPublicId)
            }
        }
        val reader = DebtQueryReader(fixture.provider, queryDao, fixture.coordinator)
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        api.detail = { val captured = readDebt(); started.complete(Unit); release.await(); captured }
        val old = async { reader.detail(fixture.binding, "jpy-debt") }
        started.await()
        api.detail = { readDebt().copy(rowVersion = 5, remainingAmountCents = 600) }
        val fresh = reader.detail(fixture.binding, "jpy-debt").getOrThrow()
        saveFails = true
        release.complete(Unit)
        val late = old.await().getOrThrow()
        assertEquals(fresh.value, late.value)
        assertEquals(fresh.fetchedAt, late.fetchedAt)
        assertTrue(late.fromCache)
        api.offline = true
        assertEquals(fresh.fetchedAt, reader.detail(fixture.binding, "jpy-debt").getOrThrow().fetchedAt)
    }

    @Test fun acceptedDirectWriteWithFailedCleanupCannotReviveOldDebtAfterRecreationAndFreshReadRepairsOnlyTheQuery() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        var cleanupFails = true
        val queryDao = object : ExpenseDao by fixture.dao {
            override suspend fun settleDebtDirectReads(bindingKey: String, ledgerId: String, tokens: List<String>, expectedEpoch: Long?) {
                if (cleanupFails) throw SQLiteException("Debt read DELETE failed")
                fixture.dao.settleDebtDirectReads(bindingKey, ledgerId, tokens, expectedEpoch)
            }
        }
        val reader = DebtQueryReader(fixture.provider, queryDao, fixture.coordinator)
        val repository = DebtRepository(fixture.provider, reader)
        repository.getDebt("jpy-debt").getOrThrow()
        assertEquals(5L, repository.setDebtKind("jpy-debt", 4, "installment").getOrThrow().rowVersion)
        assertEquals(1, api.commands)
        api.offline = true
        val reopened = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, queryDao, fixture.coordinator))
        assertTrue(reopened.getDebt("jpy-debt").isFailure)
        assertEquals(1, api.commands)
        cleanupFails = false
        api.offline = false
        val restored = reopened.getDebt("jpy-debt").getOrThrow()
        assertFalse(restored.fromCache)
        assertEquals(5L, restored.value.rowVersion)
        assertEquals("installment", restored.value.debtKind)
        api.offline = true
        assertEquals(restored.fetchedAt, reopened.getDebt("jpy-debt").getOrThrow().fetchedAt)
        assertEquals(1, api.commands)
    }

    @Test fun definitiveDirectRejectionKeepsTheOriginalReadButUnknownAcceptanceRequiresFreshQueryRepair() = runTest {
        val api = DebtReadApi()
        val fixture = GoalReadFixture { api }
        val repository = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        val original = repository.getDebt("jpy-debt").getOrThrow()
        api.commandFailure = HttpException(Response.error<Any>(409, """{"error":"state_conflict"}""".toResponseBody()))
        assertTrue(repository.setDebtKind("jpy-debt", 4, "installment").isFailure)
        api.offline = true
        assertEquals(original.fetchedAt, repository.getDebt("jpy-debt").getOrThrow().fetchedAt)
        api.offline = false
        api.commandFailure = ConnectException("ACK lost")
        api.acceptBeforeFailure = true
        assertTrue(repository.setDebtKind("jpy-debt", 4, "installment").isFailure)
        api.offline = true
        val reopened = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        assertTrue(reopened.getDebt("jpy-debt").isFailure)
        api.offline = false
        assertEquals(5L, reopened.getDebt("jpy-debt").getOrThrow().value.rowVersion)
        assertEquals(2, api.commands)
    }
}

private class DebtReadApi : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
    var offline = false
    var failure: Throwable? = null
    var detail: suspend () -> DebtDto = { readDebt() }
    var commands = 0
    var commandFailure: Throwable? = null
    var acceptBeforeFailure = false
    var commandReplyGate: (suspend () -> Unit)? = null
    override suspend fun setDebtKind(publicId: String, request: DebtKindSetRequestDto, idempotencyKey: String?): DebtDto {
        commands++
        val accepted = readDebt().copy(publicId = publicId, rowVersion = request.expectedRowVersion + 1, debtKind = request.debtKind)
        if (acceptBeforeFailure || commandFailure == null) detail = { accepted }
        commandReplyGate?.invoke()
        commandFailure?.let { throw it }
        return accepted
    }
    override suspend fun debt(publicId: String): DebtDto { checkTransport(); return detail().copy(publicId = publicId) }
    override suspend fun debts(lens: String?): DebtListResponseDto {
        checkTransport()
        return DebtListResponseDto(listOf(readDebt(), readDebt().copy(publicId = "other-debt")), "JPY")
    }
    override suspend fun repaymentProposals(publicId: String): MemberRepaymentProposalListResponseDto {
        checkTransport()
        return MemberRepaymentProposalListResponseDto(emptyList())
    }
    private fun checkTransport() { failure?.let { throw it }; if (offline) throw ConnectException("offline") }
}

private fun readDebt() = DebtDto(publicId = "jpy-debt", ledgerId = "owner", direction = "i_owe",
    counterpartyType = "external", counterpartyLabel = "原日元往来", principalAmountCents = 1200,
    remainingAmountCents = 900, paidAmountCents = 300, status = "open", sourceType = "manual",
    homeCurrencyCode = "JPY", originalCurrencyCode = "JPY", originalAmountMinor = 1200,
    createdAt = "2026-07-01T06:07:08Z", updatedAt = "2026-08-09T03:04:05Z", rowVersion = 4)
