package com.ticketbox.viewmodel

import android.app.Application
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.*
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.*
import com.ticketbox.data.repository.*
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.runCurrent
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode
import kotlin.test.*

@RunWith(RobolectricTestRunner::class)
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class MonthlyArrangementRoomDraftTest {
    @Test fun realSelectionRevisionsRecoverTheOriginalDraftWithoutCrossingOwnersOrLedgers() = budgetTest {
        val fixture = RoomDraftFixture()
        try {
            val original = fixture.binding()
            val draft = MonthlyArrangementDraft("JPY", "1200", "300", 4, true)
            fixture.repository.storeArrangementDraft(original, "2026-09", draft)
            fixture.session.switchLedgerForFixture("other", "Other")
            val other = fixture.binding()
            assertNotEquals(original.bindingRevision, other.bindingRevision)
            assertNull(fixture.repository.arrangementDraft(other, "2026-09"))
            fixture.session.switchLedgerForFixture(original.ledgerId, "Original")
            val returned = fixture.binding()
            assertNotEquals(original.bindingRevision, returned.bindingRevision)
            assertEquals(draft, fixture.repository.arrangementDraft(returned, "2026-09"))
            assertTrue(fixture.repository.enqueueArrangement(original, "2026-09", draft.request()).isFailure,
                "A stable draft key must not bypass exact request binding")
            assertEquals(draft, fixture.repository.arrangementDraft(returned, "2026-09"))
            fixture.session.rebindToDifferentServerForFixture("https://other.example.test", "synthetic-other")
            assertNull(fixture.repository.arrangementDraft(fixture.binding(), "2026-09"))
        } finally { fixture.db.close() }
    }

    @Test fun initialDoneProjectionCannotCancelDelayedRoomDraftRestoration() = budgetTest {
        val fixture = RoomDraftFixture()
        try {
            val binding = fixture.binding()
            val draft = MonthlyArrangementDraft("JPY", "2400", "700", 1, true)
            fixture.repository.storeArrangementDraft(binding, "2026-09", draft)
            val draftReadStarted = CompletableDeferred<Unit>()
            val releaseDraft = CompletableDeferred<Unit>()
            fixture.beforeDraftRead = { draftReadStarted.complete(Unit); releaseDraft.await() }
            val releaseInitialDone = CompletableDeferred<Unit>()
            val base = FakeBudgetActions(budget())
            val repository = object : BudgetActions by base {
                override fun observeLedgerAccessState() = flow { emit(LedgerAccessState(binding, "owner")); awaitCancellation() }
                override suspend fun arrangement(binding: LogicalSessionBinding, month: String) = fixture.repository.arrangement(binding, month)
                override suspend fun arrangementDraft(binding: LogicalSessionBinding, month: String) = fixture.repository.arrangementDraft(binding, month)
                override suspend fun storeArrangementDraft(binding: LogicalSessionBinding, month: String, draft: MonthlyArrangementDraft?) =
                    fixture.repository.storeArrangementDraft(binding, month, draft)
                override fun observeArrangements(binding: LogicalSessionBinding) = flow {
                    releaseInitialDone.await(); emit(listOf(fixture.confirmed())); awaitCancellation()
                }
            }
            val vm = BudgetAdviceViewModel(repository, initialMonth = "2026-09")
            runCurrent()
            assertTrue(draftReadStarted.isCompleted)
            releaseInitialDone.complete(Unit)
            runCurrent()
            assertTrue(vm.uiState.value.arrangementLoading)
            releaseDraft.complete(Unit)
            runCurrent()
            assertEquals(draft, vm.uiState.value.arrangementDraft)
            assertTrue(vm.uiState.value.arrangementPending.single().isConfirmed)
            assertEquals(1200L, vm.uiState.value.arrangementRead?.response?.arrangement?.savingsTargetCents)
            assertFalse(vm.uiState.value.arrangementLoading)
            vm.editArrangement(false, "800")
            runCurrent()
            assertEquals("2400", vm.uiState.value.arrangementDraft?.savings)
            assertEquals(draft.copy(buffer = "800"), fixture.repository.arrangementDraft(binding, "2026-09"))
        } finally { fixture.db.close() }
    }
}

private class RoomDraftFixture {
    val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java)
        .allowMainThreadQueries().setQueryExecutor { it.run() }.setTransactionExecutor { it.run() }.build()
    val session = TestSessionFixture().apply { saveToken("synthetic-arrangement-session") }
    val adapters = OutboxAdapterGraph()
    private val receipt = MonthlyArrangementDto("owner", "2026-09", "JPY", 1200, 300, 1, "2026-09-27T00:00:00Z")
    private val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun monthlyArrangement(month: String) = MonthlyArrangementResponseDto(binding().ledgerId, month, receipt)
    }
    private val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?) = api
    }, session)
    private val outbox = testOutboxRepository(FakePendingMutationDao(), bindingProvider = { provider.currentSession().toOutboxBinding() })
    var beforeDraftRead: suspend () -> Unit = {}
    private val dao = object : MonthlyArrangementCacheDao by db.monthlyArrangementCacheDao() {
        override suspend fun read(bindingKey: String, month: String, kind: String): MonthlyArrangementCacheEntity? {
            if (kind == "draft") beforeDraftRead()
            return db.monthlyArrangementCacheDao().read(bindingKey, month, kind)
        }
    }
    val repository = MonthlyArrangementRepository(provider, outbox, dao, adapters.arrangementSaveAdapter, adapters.arrangementReceiptAdapter, { _, _ -> })
    fun binding() = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    fun confirmed(): PendingMonthlyArrangement {
        val intent = MonthlyArrangementPayload(1, receipt.month, MonthlyArrangementSaveRequest("JPY", 1200, 300))
        val row = OutboxRow(1, binding().serverUrl, "owner", binding().ownerKey, PendingMutationType.SaveMonthlyArrangement,
            "monthly_arrangement:${receipt.month}", adapters.arrangementSaveAdapter.toJson(intent), 0, PendingMutationStatus.Done,
            0, null, receipt.updatedAt, receipt.updatedAt, receipt.updatedAt, "original-key", adapters.arrangementReceiptAdapter.toJson(receipt))
        return PendingMonthlyArrangement(row, intent, receipt)
    }
}
