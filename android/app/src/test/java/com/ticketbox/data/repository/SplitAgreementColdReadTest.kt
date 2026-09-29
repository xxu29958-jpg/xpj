package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.viewmodel.SplitAgreementViewModel
import androidx.lifecycle.viewModelScope
import java.net.ConnectException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response

@OptIn(ExperimentalCoroutinesApi::class)
class SplitAgreementColdReadTest {
    private val dispatcher = StandardTestDispatcher()
    private val models = mutableListOf<SplitAgreementViewModel>()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun teardown() { models.forEach { it.viewModelScope.cancel() }; Dispatchers.resetMain() }

    @Test fun aFreshModelCanReadPreviousAgreementFactsOfflineWithoutRestoringAConfirmation() = runTest(dispatcher) {
        var offline = false
        val fixture = GoalReadFixture { fallback ->
            object : ApiService by fallback {
                override suspend fun splitAgreement(publicId: String, newShareAmountCents: Long?): BillSplitAgreementDto {
                    if (offline) throw ConnectException("offline")
                    return splitTestAgreement()
                }
            }
        }
        val outbox = testOutboxRepository(FakePendingMutationDao(),
            bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
        fun model() = own(SplitAgreementViewModel(SplitAgreementRepository(fixture.provider, outbox,
            OutboxAdapterGraph().splitAgreementAdapter, DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator))))
        val task = DebtTask(fixture.binding, "original")
        val online = model()
        online.load(task, canModify = true)
        online.state.first { !it.loading }
        assertEquals(3000L, assertNotNull(online.state.value.agreement).originalPaidAmountCents)
        offline = true
        val cached = SplitAgreementRepository(fixture.provider, outbox, OutboxAdapterGraph().splitAgreementAdapter,
            DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)).read(task).getOrThrow()
        assertTrue(cached.fromCache)
        val restarted = model()
        restarted.load(task, canModify = true)
        restarted.state.first { !it.loading }
        val facts = assertNotNull(restarted.state.value.agreement, "Previously read agreement facts must survive a cold offline reopen")
        assertEquals(3000L, facts.originalPaidAmountCents)
        assertEquals(1000L, facts.originalForgivenAmountCents)
        assertEquals(-1000L, facts.settlementNetAmountCents)
        assertFalse(restarted.state.value.previewReady)
        restarted.confirm(true)
        assertFalse(restarted.state.value.confirmed)
        assertFalse(restarted.state.value.canPropose)
    }

    @Test fun bothPreviouslyReadEntriesKeepTheirFactsAndTimeButNeverCacheAnInputPreview() = runTest(dispatcher) {
        val f = AgreementReadFixture()
        val original = f.repository().read(f.task).getOrThrow()
        val returned = f.repository().read(f.task.copy(debtPublicId = "return")).getOrThrow()
        val preview = f.repository().load(f.task, 1200).getOrThrow()
        assertEquals(1200L, preview.preview.newShareAmountCents)
        f.offline = true
        assertEquals(original.copy(fromCache = true), f.repository().read(f.task).getOrThrow())
        assertEquals(returned.copy(fromCache = true), f.repository().read(f.task.copy(debtPublicId = "return")).getOrThrow())
        assertEquals(2000L, f.repository().read(f.task).getOrThrow().value.preview.newShareAmountCents)
    }

    @Test fun eitherMissingLegRetiresBothSnapshotsAndTheVisibleAggregateWithoutRemovingAnotherRelationship() = runTest(dispatcher) {
        val f = AgreementReadFixture()
        val live = f.repository()
        val model = own(SplitAgreementViewModel(live))
        model.load(f.task, canModify = true); model.state.first { !it.loading }
        f.repository().read(f.task.copy(debtPublicId = "return")).getOrThrow()
        val otherTask = f.task.copy(debtPublicId = "other-original")
        val other = f.repository().read(otherTask).getOrThrow()
        f.failure = "return" to HttpException(Response.error<Any>(404, """{"error":"debt_not_found"}""".toResponseBody()))
        assertTrue(live.read(f.task.copy(debtPublicId = "return")).isFailure)
        advanceUntilIdle()
        assertEquals(null, model.state.value.agreement)
        f.offline = true
        assertTrue(f.repository().read(f.task).isFailure)
        assertTrue(f.repository().read(f.task.copy(debtPublicId = "return")).isFailure)
        assertEquals(other.copy(fromCache = true), f.repository().read(otherTask).getOrThrow())
        f.offline = false; f.failure = null
        val repaired = f.repository().read(f.task).getOrThrow()
        f.offline = true
        assertEquals(repaired.copy(fromCache = true), f.repository().read(f.task).getOrThrow())
        assertTrue(f.repository().read(f.task.copy(debtPublicId = "return")).isFailure,
            "Restoring one entry cannot resurrect a previously retired aggregate at the other entry")
    }

    @Test fun accessRevocationAndAcceptedDebtChangesWithdrawStoredAgreementReads() = runTest(dispatcher) {
        val f = AgreementReadFixture()
        val model = own(SplitAgreementViewModel(f.repository()))
        model.load(f.task, canModify = true); model.state.first { !it.loading }
        f.failure = "original" to HttpException(Response.error<Any>(403, """{"error":"forbidden"}""".toResponseBody()))
        assertTrue(f.repository().read(f.task).isFailure)
        advanceUntilIdle()
        assertEquals(null, model.state.value.agreement)
        f.offline = true
        assertTrue(f.repository().read(f.task).isFailure)
        f.offline = false; f.failure = null
        f.repository().read(f.task).getOrThrow()
        f.reader().direct(f.task.binding) { Unit }
        f.offline = true
        assertTrue(f.repository().read(f.task).isFailure)
        assertTrue(f.fixture.dao.debtAgreementSnapshots(logicalBindingAdapter.toJson(f.task.binding)).isEmpty())
    }

    @Test fun aDelayedPreviousReaderCannotRemoveANewlyReadProposalWithUnchangedDebtVersions() = runTest(dispatcher) {
        val f = AgreementReadFixture()
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var calls = 0
        f.respond = { _, share ->
            calls++
            if (calls == 1) { started.complete(Unit); release.await(); splitTestAgreement() }
            else splitTestAgreement().copy(pendingProposal = splitTestProposal(),
                preview = splitTestAgreement().preview.copy(newShareAmountCents = share ?: 2000))
        }
        val late = async { f.repository().read(f.task) }
        started.await()
        val newest = f.repository().read(f.task).getOrThrow()
        assertNotNull(newest.value.pendingProposal)
        release.complete(Unit)
        assertEquals(newest.copy(fromCache = true), late.await().getOrThrow())
        f.offline = true
        assertEquals(newest.copy(fromCache = true), f.repository().read(f.task).getOrThrow())
    }

    private fun own(model: SplitAgreementViewModel) = model.also(models::add)
}

private class AgreementReadFixture {
    var offline = false
    var failure: Pair<String, Throwable>? = null
    var respond: suspend (String, Long?) -> BillSplitAgreementDto = { publicId, share ->
        splitTestAgreement().let { value ->
            val result = if (publicId.startsWith("other-")) value.copy(invitationPublicId = "other-invitation",
                originalDebt = value.originalDebt.copy(publicId = "other-original", sourceId = "other-invitation"),
                returnDebt = value.returnDebt?.copy(publicId = "other-return", sourceId = "other-invitation")) else value
            result.copy(preview = result.preview.copy(newShareAmountCents = share ?: result.agreedShareAmountCents))
        }
    }
    val fixture = GoalReadFixture { fallback -> object : ApiService by fallback {
        override suspend fun splitAgreement(publicId: String, newShareAmountCents: Long?): BillSplitAgreementDto {
            if (offline) throw ConnectException("offline")
            failure?.takeIf { it.first == publicId }?.second?.let { throw it }
            return respond(publicId, newShareAmountCents)
        }
    } }
    private val outbox = testOutboxRepository(FakePendingMutationDao(),
        bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
    val task get() = DebtTask(fixture.binding, "original")
    fun reader() = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
    fun repository() = SplitAgreementRepository(fixture.provider, outbox, OutboxAdapterGraph().splitAgreementAdapter, reader())
}
