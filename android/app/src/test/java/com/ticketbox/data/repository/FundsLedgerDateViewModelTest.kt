package com.ticketbox.data.repository

import android.app.Application
import androidx.lifecycle.viewModelScope
import androidx.room.Room
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.domain.model.FundsOverview
import com.ticketbox.domain.model.ExpenseAccountingTime
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.start
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class FundsLedgerDateViewModelTest {
    @Test fun unavailableOverviewRequiresExplicitDateBeforeFreezingOriginalCommand() = runBlocking {
        withFundsDate {
            val vm = model()
            awaitFundsDate { vm.state.value.error != null }
            assertEquals(1, vm.state.value.accounts.size)
            assertNull(vm.state.value.overview)
            vm.start("create")
            awaitFundsDate { stored() != null }
            assertEquals("", assertNotNull(vm.state.value.task.input).date)
            vm.edit { it.copy(name = "银行卡", currency = "JPY", opening = "1200") }
            vm.submit()
            awaitFundsDate { !vm.state.value.busy && vm.state.value.error != null }
            assertNull(assertNotNull(stored()).commandJson)
            assertTrue(fixture.pending.rows.isEmpty())

            vm.edit { it.copy(date = "2024-02-29") }
            vm.submit()
            awaitFundsDate { fixture.pending.rows.isNotEmpty() }
            val frozen = assertNotNull(stored())
            val original = fixture.pending.rows.values.single()
            assertEquals("2024-02-29", FundsWire.command.fromJson(original.payload)?.create?.openingDate)
            vm.viewModelScope.cancel()
            probe.valuationDate = "2024-06-01"
            val reopened = model()
            awaitFundsDate { reopened.state.value.task.frozen && reopened.state.value.overview != null }
            reopened.resume()
            reopened.start("create")
            reopened.submit()
            awaitFundsDate { !reopened.state.value.busy }
            assertEquals("2024-02-29", reopened.state.value.task.input?.date)
            assertEquals(frozen, stored())
            assertEquals(listOf(original), fixture.pending.rows.values.toList())
        }
    }

    @Test fun valuationDateOnlyInitializesNewInputAndRawDraftSurvivesRecovery() = runBlocking {
        withFundsDate {
            probe.valuationDate = "2024-05-31"
            val vm = model()
            awaitFundsDate { vm.state.value.overview != null }
            vm.start("create")
            awaitFundsDate { stored() != null }
            assertEquals("2024-05-31", vm.state.value.task.input?.date)
            vm.edit { it.copy(date = "2024-02-29") }
            awaitFundsDate { stored()?.inputJson?.contains("2024-02-29") == true }
            val original = stored()
            vm.viewModelScope.cancel()
            probe.valuationDate = "2024-06-01"
            val reopened = model()
            awaitFundsDate { reopened.state.value.task.input != null && reopened.state.value.overview != null }
            reopened.resume()
            reopened.start("create")
            assertEquals("2024-02-29", reopened.state.value.task.input?.date)
            assertEquals(original, stored())
            assertTrue(fixture.pending.rows.isEmpty())
        }
    }

    @Test fun captureWithoutAccountingDayStaysUnknownAndRecordedCaptureDayIsPreserved() = runBlocking {
        for (date in listOf(null, "2024-02-29")) withFundsDate {
            probe.valuationDate = "2024-06-01"
            val vm = model(capturedRepayment(date))
            awaitFundsDate { vm.state.value.repaymentCapture != null }
            assertNull(vm.state.value.overview)
            vm.start("create")
            awaitFundsDate { stored() != null }
            val input = assertNotNull(vm.state.value.task.input)
            assertEquals(date.orEmpty(), input.date)
            assertEquals("capture", input.sourceRepaymentDraftId)
            assertEquals(date.orEmpty(), FundsWire.input.fromJson(assertNotNull(stored()).inputJson)?.date)
        }
    }

    @Test fun editWithoutDateFieldStillEnqueuesAccountEdit() = runBlocking {
        withFundsDate {
            val vm = model()
            awaitFundsDate { vm.state.value.error != null }
            vm.open("bank")
            awaitFundsDate { vm.state.value.detail != null }
            vm.start("edit")
            vm.edit { it.copy(name = "改名银行卡", date = "") }
            vm.submit()
            awaitFundsDate { !vm.state.value.busy }
            assertNull(vm.state.value.error)
            val command = FundsWire.command.fromJson(fixture.pending.rows.values.single().payload)
            assertEquals("改名银行卡", command?.edit?.name)
        }
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
private suspend fun withFundsDate(block: suspend FundsDateFixture.() -> Unit) {
    Dispatchers.setMain(Dispatchers.Unconfined)
    val fixture = FundsDateFixture()
    try { fixture.block() } finally {
        fixture.models.forEach { it.viewModelScope.cancel() }
        fixture.database.close()
        Dispatchers.resetMain()
    }
}

private suspend fun awaitFundsDate(condition: suspend () -> Boolean) = withTimeout(10_000) {
    while (!condition()) delay(10)
}

private class FundsDateFixture {
    val probe = FundsDateProbe()
    val fixture = GoalReadFixture { probe }
    val database = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java)
        .allowMainThreadQueries().setQueryExecutor { it.run() }.setTransactionExecutor { it.run() }.build()
    private val repository = FundsRepository(fixture.provider, database, fixture.outbox,
        DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
    val models = mutableListOf<FundsViewModel>()
    fun model(capture: RepaymentDraft? = null): FundsViewModel {
        val captures = capture?.let { value -> object : RepaymentDraftActions {
            override fun canModifyLedger() = true
            override suspend fun readDrafts(expectedBinding: LogicalSessionBinding?) =
                Result.success(ReadSnapshot(listOf(value), value.createdAt, false))
            override suspend fun readCaptures(binding: LogicalSessionBinding) =
                Result.success(ReadSnapshot(emptyList<com.ticketbox.domain.model.PaymentCapture>(), value.createdAt, false))
        } }
        return FundsViewModel(repository, repaymentDraftId = capture?.publicId, captures = captures).also { models += it }
    }
    suspend fun stored() = fixture.binding.let { database.fundsInputDao().get(it.serverUrl, it.ownerKey, it.ledgerId) }
}

private class FundsDateProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    var valuationDate: String? = null
    override suspend fun fundsAccounts() = listOf(FinancialAccountDto("bank", "银行卡", "owner", 1,
        "bank", "JPY", "ledger", null, null, 1, false, 1200, 1200, "2024-05-01", "已核对", null, true))
    override suspend fun fundsAccountChoices() = emptyList<com.ticketbox.domain.model.AccountChoice>()
    override suspend fun fundsAccount(id: String) = fundsAccounts().single { it.publicId == id }
    override suspend fun existingFundDebts() = emptyList<com.ticketbox.domain.model.ExistingDebtChoice>()
    override suspend fun fundsOverview() = FundsOverview("JPY",
        valuationDate ?: throw java.io.IOException("overview unavailable"), 1200, 0, 1200, 1, 0, 0)
}

private fun capturedRepayment(date: String?) = RepaymentDraft(
    publicId = "capture", source = "notification", amountCents = 1200, homeCurrencyCode = "JPY",
    merchantLabel = "信用卡还款", capturedAt = "2024-05-31T16:00:00Z", status = "pending",
    committedDebtPublicId = null, committedRepaymentPublicId = null, createdAt = "2024-05-31T16:00:00Z", resolvedAt = null,
    accountingTime = date?.let { ExpenseAccountingTime("date_only", accountingDate = it) },
)
