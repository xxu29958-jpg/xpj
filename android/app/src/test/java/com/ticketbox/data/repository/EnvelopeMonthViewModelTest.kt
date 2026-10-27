package com.ticketbox.data.repository

import android.app.Application
import androidx.lifecycle.viewModelScope
import androidx.room.Room
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.domain.model.Envelopes
import com.ticketbox.domain.model.FundsOverview
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.openEnvelopes
import com.ticketbox.viewmodel.startEnvelope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Dispatchers
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

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class EnvelopeMonthViewModelTest {
    @Test fun failedOverviewRequiresSelectionAndRecoveredDefaultsCannotRewriteStoredEnvelopeInput() = runBlocking {
        Dispatchers.setMain(Dispatchers.Unconfined)
        val probe = EnvelopeMonthProbe()
        val fixture = GoalReadFixture { probe }
        val database = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java)
            .allowMainThreadQueries().setQueryExecutor { it.run() }.setTransactionExecutor { it.run() }.build()
        val repository = FundsRepository(fixture.provider, database, fixture.outbox,
            DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        val models = mutableListOf<FundsViewModel>()
        fun model() = FundsViewModel(repository).also { models += it }
        val binding = fixture.binding
        val inputs = database.fundsInputDao()
        try {
            val vm = model()
            awaitState { vm.state.value.error != null }
            assertEquals(1, vm.state.value.accounts.size)
            assertNull(vm.state.value.overview)
            vm.openEnvelopes(); vm.startEnvelope()
            assertNotNull(vm.state.value.error)
            assertNull(vm.state.value.envelopeMonth)
            assertTrue(probe.requestedMonths.isEmpty())
            assertNull(inputs.get(binding.serverUrl, binding.ownerKey, binding.ledgerId))
            assertTrue(fixture.pending.rows.isEmpty())

            probe.overviewUnavailable = false
            vm.refresh(); awaitState { vm.state.value.overview != null }
            assertNotNull(vm.state.value.overview, "Recovered overview: ${vm.state.value.error}")
            vm.openEnvelopes(); awaitState { vm.state.value.envelopes != null }
            assertEquals(listOf("2024-05"), probe.requestedMonths)
            vm.openEnvelopes("2024-02"); awaitState { vm.state.value.envelopes?.month == "2024-02" }
            vm.startEnvelope()
            awaitState { inputs.get(binding.serverUrl, binding.ownerKey, binding.ledgerId) != null }
            val original = assertNotNull(inputs.get(binding.serverUrl, binding.ownerKey, binding.ledgerId))
            assertEquals("2024-02", FundsWire.input.fromJson(original.inputJson)?.envelopeMonth)
            vm.viewModelScope.cancel()

            val reopened = model()
            awaitState { reopened.state.value.task.input != null && reopened.state.value.overview != null }
            reopened.resume(); awaitState { reopened.state.value.envelopes?.month == "2024-02" }
            assertEquals("2024-02", reopened.state.value.envelopeMonth)
            assertEquals("2024-02", probe.requestedMonths.last())
            assertEquals(original, inputs.get(binding.serverUrl, binding.ownerKey, binding.ledgerId))
            assertTrue(fixture.pending.rows.isEmpty())
        } finally {
            models.forEach { it.viewModelScope.cancel() }
            database.close()
            Dispatchers.resetMain()
        }
    }
}

private suspend fun awaitState(condition: suspend () -> Boolean) = withTimeout(10_000) {
    while (!condition()) delay(10)
}

private class EnvelopeMonthProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    var overviewUnavailable = true
    val requestedMonths = mutableListOf<String>()
    override suspend fun fundsAccounts() = listOf(FinancialAccountDto("bank", "银行卡", "owner", 1,
        "bank", "JPY", "ledger", null, null, 1, false, 1200, 1200, "2024-05-01", "已核对", null, true))
    override suspend fun fundsAccountChoices() = emptyList<com.ticketbox.domain.model.AccountChoice>()
    override suspend fun existingFundDebts() = emptyList<com.ticketbox.domain.model.ExistingDebtChoice>()
    override suspend fun fundsOverview(): FundsOverview {
        if (overviewUnavailable) throw java.io.IOException("overview unavailable")
        return FundsOverview("JPY", "2024-05-31", 1200, 0, 1200, 1, 0, 0)
    }
    override suspend fun envelopes(month: String): Envelopes {
        requestedMonths += month
        return Envelopes("owner", month, "JPY", 1, "2024-05-31T00:00:00Z", "2024-05-31",
            1200, 0, 1200, emptyList(), emptyList(), emptyList(), emptyList())
    }
}
