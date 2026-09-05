package com.ticketbox.viewmodel

import com.ticketbox.domain.model.DebtListLens
import kotlinx.coroutines.Dispatchers
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
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtListLensTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun personalTaskKeepsItsServerLensOnReloadAndRefresh() = runTest(dispatcher) {
        val repository = FakeDebtActions()
        val viewModel = DebtListViewModel(repository, repository.creation, DebtListLens.Payables)
        advanceUntilIdle()
        viewModel.reload()
        advanceUntilIdle()
        viewModel.refresh()
        advanceUntilIdle()

        assertTrue(repository.listLenses.isNotEmpty())
        assertEquals(setOf(DebtListLens.Payables), repository.listLenses.toSet())
    }

    @Test
    fun existingConsumersKeepTheWholeLedgerByDefault() = runTest(dispatcher) {
        val repository = FakeDebtActions()
        DebtListViewModel(repository, repository.creation)
        advanceUntilIdle()

        assertEquals(listOf(DebtListLens.Ledger), repository.listLenses)
    }
}
