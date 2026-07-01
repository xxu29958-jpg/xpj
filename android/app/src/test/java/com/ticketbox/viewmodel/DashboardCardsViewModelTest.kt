package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.DashboardCardsActions
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DashboardCardsViewModelTest {
    @Test
    fun refreshNormalizesServerCardsAndReflectsRole() = dashboardCardsTest {
        val actions = FakeDashboardCardsActions(
            cards = listOf(
                dashboardCard("reports", position = 20),
                dashboardCard("pending", position = 0),
                dashboardCard("budget", position = 10, visible = false),
            ),
        )

        val vm = DashboardCardsViewModel(actions)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(listOf("pending", "budget", "reports"), state.cards.map { it.key })
        assertEquals(listOf(0, 1, 2), state.cards.map { it.position })
        assertTrue(state.canModify)
        assertFalse(state.dirty)
    }

    @Test
    fun saveSendsDraftOrderAndSignalsShellRefreshOnlyAfterSuccess() = dashboardCardsTest {
        val actions = FakeDashboardCardsActions(
            cards = listOf(
                dashboardCard("pending", position = 0),
                dashboardCard("budget", position = 1),
                dashboardCard("reports", position = 2),
            ),
        )
        val vm = DashboardCardsViewModel(actions)
        advanceUntilIdle()

        vm.moveCard(index = 2, delta = -1)
        vm.setVisible("budget", visible = false)
        assertTrue(vm.uiState.value.dirty)

        vm.saveCards()
        advanceUntilIdle()

        assertEquals(listOf("pending", "reports", "budget"), actions.updateCalls.single().map { it.key })
        assertEquals(listOf(0, 1, 2), actions.updateCalls.single().map { it.position })
        assertEquals(listOf(true, true, false), actions.updateCalls.single().map { it.visible })
        assertEquals(1, vm.uiState.value.savedRevision)
        assertFalse(vm.uiState.value.dirty)
        assertEquals(UiText.res(R.string.dashboard_cards_saved), vm.uiState.value.message)
    }

    @Test
    fun readonlyRoleBlocksSaveAndResetBeforeNetworkMutation() = dashboardCardsTest {
        val actions = FakeDashboardCardsActions(
            canModify = false,
            cards = listOf(dashboardCard("pending", position = 0)),
        )
        val vm = DashboardCardsViewModel(actions)
        advanceUntilIdle()

        vm.setVisible("pending", visible = false)
        vm.saveCards()
        vm.resetCards()
        advanceUntilIdle()

        assertTrue(actions.updateCalls.isEmpty())
        assertEquals(UiText.res(R.string.common_readonly_ledger), vm.uiState.value.message)
        assertFalse(vm.uiState.value.canModify)
    }

    private fun dashboardCardsTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    private fun dashboardCard(
        key: String,
        position: Int,
        visible: Boolean = true,
    ): DashboardCard = DashboardCard(
        key = key,
        title = key,
        visible = visible,
        position = position,
    )
}

private class FakeDashboardCardsActions(
    private val canModify: Boolean = true,
    cards: List<DashboardCard>,
) : DashboardCardsActions {
    private var cardsResult = DashboardCards(DashboardSurface.Android, cards)
    val updateCalls = mutableListOf<List<DashboardCardUpdate>>()

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun dashboardCards(surface: DashboardSurface): Result<DashboardCards> =
        Result.success(cardsResult.copy(surface = surface))

    override suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> {
        updateCalls += updates
        cardsResult = DashboardCards(
            surface = surface,
            items = updates.map { update ->
                DashboardCard(
                    key = update.key,
                    title = update.key,
                    visible = update.visible,
                    position = update.position,
                )
            },
        )
        return Result.success(cardsResult)
    }
}
