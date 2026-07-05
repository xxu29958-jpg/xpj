package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.LedgerFakeTokenStore
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.StubApi
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class LedgerSwitcherViewModelTest {

    private val ledger = "L_owner"

    @Test
    fun refreshFailureShowsDangerTone() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(listLedgersError = RuntimeException("offline"))
            val vm = harness(api)

            vm.refresh()
            val state = vm.uiState.first { !it.loading && it.message != null }

            assertNotNull(state.message)
            assertEquals(MessageTone.Danger, state.messageTone)
            assertEquals(LedgerListLoadState.Failed, state.listLoadState)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshFailureKeepsCachedRowsButMarksListFailed() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(
                listLedgersResult = LedgerListResponseDto(
                    listOf(ledgerDto(ledger, "My receipts"), ledgerDto("L_family", "Family ledger")),
                ),
            )
            val vm = harness(api)

            vm.refresh()
            vm.uiState.first { !it.loading && it.ledgers.size == 2 }

            api.listLedgersError = RuntimeException("offline")
            vm.refresh()
            val failed = vm.uiState.first { !it.loading && it.messageTone == MessageTone.Danger }

            assertEquals(listOf(ledger, "L_family"), failed.ledgers.map { it.ledgerId })
            assertEquals(LedgerListLoadState.Failed, failed.listLoadState)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun inputErrorShowsDangerThenClearResetsNeutral() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val vm = harness(StubApi())

            vm.showInputError(UiText.res(R.string.ledger_switcher_message_name_required))

            assertEquals(UiText.res(R.string.ledger_switcher_message_name_required), vm.uiState.value.message)
            assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)

            vm.clearMessage()

            assertNull(vm.uiState.value.message)
            assertEquals(MessageTone.Neutral, vm.uiState.value.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun switchFailureShowsDangerTone() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(switchError = RuntimeException("boom"))
            val vm = harness(api)

            vm.switchTo("L_family") {}
            val state = vm.uiState.first { !it.loading && it.message != null }

            assertEquals("L_family", api.switchRequests.single())
            assertNotNull(state.message)
            assertEquals(MessageTone.Danger, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun switchSuccessKeepsSuccessToneThroughFollowUpRefresh() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(
                switchResult = LedgerSwitchResponseDto(
                    sessionToken = "new-token",
                    ledger = ledgerDto("L_family", "Family ledger"),
                    accountName = "Owner",
                    deviceName = "Phone",
                ),
                listLedgersResult = LedgerListResponseDto(
                    listOf(ledgerDto(ledger, "My receipts"), ledgerDto("L_family", "Family ledger")),
                ),
            )
            val vm = harness(api)
            var switched = false

            vm.switchTo("L_family") { switched = true }
            val state = vm.uiState.first {
                !it.loading && it.messageTone == MessageTone.Success &&
                    it.ledgers.any { ledger -> ledger.ledgerId == "L_family" }
            }

            assertTrue(switched)
            assertEquals("L_family", api.switchRequests.single())
            assertEquals(UiText.res(R.string.ledger_switcher_message_switched, "Family ledger"), state.message)
            assertEquals(MessageTone.Success, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun createSuccessKeepsSuccessToneThroughFollowUpRefresh() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(
                createResult = ledgerDto("L_new", "Travel ledger"),
                listLedgersResult = LedgerListResponseDto(
                    listOf(ledgerDto(ledger, "My receipts"), ledgerDto("L_new", "Travel ledger")),
                ),
            )
            val vm = harness(api)
            var created = false

            vm.create(" Travel ledger ") { created = true }
            val state = vm.uiState.first {
                !it.loading && it.messageTone == MessageTone.Success &&
                    it.ledgers.any { ledger -> ledger.ledgerId == "L_new" }
            }

            assertTrue(created)
            assertEquals(UiText.res(R.string.ledger_switcher_message_created, "Travel ledger"), state.message)
            assertEquals(MessageTone.Success, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    private fun harness(api: StubApi, role: String = "owner"): LedgerSwitcherViewModel {
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger(ledger, "My receipts")
            capturedRole = role
        }
        val repository = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )
        return LedgerSwitcherViewModel(repository)
    }

    private fun ledgerDto(
        ledgerId: String,
        name: String,
        role: String = "owner",
        isDefault: Boolean = false,
    ): LedgerDto = LedgerDto(
        ledgerId = ledgerId,
        name = name,
        role = role,
        isDefault = isDefault,
        createdAt = "2026-01-01T00:00:00Z",
        archivedAt = null,
    )
}
