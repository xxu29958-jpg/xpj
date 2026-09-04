package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import com.ticketbox.data.repository.DashboardCardsActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class DashboardCardsTest {
    @Test
    fun noVisibleCardsDoesNotInventDefaults() {
        assertEquals(emptyList<DashboardCard>(), visibleDashboardCards(emptyList()))
        assertEquals(emptyList<DashboardCard>(), visibleDashboardCards(listOf(
            DashboardCard(DASHBOARD_CARD_MONTHLY_SPEND, "月支出", visible = false, position = 0),
        )))
    }

    @Test
    fun visibilityAndOrderDoNotRemovePrimaryInsightViews() {
        val cards = listOf(
            DashboardCard(DASHBOARD_CARD_GOALS, "目标", visible = true, position = 20),
            DashboardCard(DASHBOARD_CARD_REPORTS, "趋势报表", visible = false, position = 0),
            DashboardCard(DASHBOARD_CARD_PENDING, "待确认", visible = true, position = 10),
        )
        assertEquals(listOf(DASHBOARD_CARD_PENDING, DASHBOARD_CARD_GOALS), visibleDashboardCards(cards).map { it.key })
        assertEquals(listOf(StatsTab.Overview, StatsTab.Trend, StatsTab.Category), PrimaryStatsTabs)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class DashboardLayoutStateTest {
    @Test
    fun draftOrderAndVisibilityPublishOnlyAfterSuccessfulSave() = layoutTest { repo ->
        val vm = com.ticketbox.viewmodel.DashboardLayoutViewModel(repo)
        vm.refresh()
        advanceUntilIdle()
        vm.beginEdit()
        vm.setVisible("monthly_spend", false)
        vm.move("reports", -1)
        assertEquals(listOf("monthly_spend", "reports"), vm.uiState.value.cards!!.map { it.key })

        vm.save()
        advanceUntilIdle()

        assertNull(vm.uiState.value.draft)
        assertEquals(listOf("reports", "monthly_spend"), vm.uiState.value.cards!!.map { it.key })
        assertFalse(vm.uiState.value.cards!!.last().visible)
        assertEquals(listOf(0, 1), repo.writes.single().map { it.position })
        assertEquals(MessageTone.Success, vm.uiState.value.messageTone)
    }

    @Test
    fun failedSaveKeepsCurrentAndDraftForRetry() = layoutTest { repo ->
        val vm = com.ticketbox.viewmodel.DashboardLayoutViewModel(repo)
        vm.refresh()
        advanceUntilIdle()
        vm.beginEdit()
        vm.setVisible("reports", false)
        repo.failSave = true
        vm.save()
        advanceUntilIdle()
        assertEquals(true, vm.uiState.value.cards!!.last().visible)
        assertFalse(vm.uiState.value.draft!!.last().visible)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        repo.failSave = false
        vm.save()
        advanceUntilIdle()
        assertNull(vm.uiState.value.draft)
        assertFalse(vm.uiState.value.cards!!.last().visible)
    }

    @Test
    fun cancelDoesNotWriteAndResetUsesServerDefaults() = layoutTest { repo ->
        val vm = com.ticketbox.viewmodel.DashboardLayoutViewModel(repo)
        vm.refresh()
        advanceUntilIdle()
        vm.beginEdit()
        vm.setVisible("reports", false)
        vm.cancelEdit()
        assertEquals(emptyList(), repo.writes)
        assertEquals(true, vm.uiState.value.cards!!.last().visible)
        vm.beginEdit()
        vm.reset()
        advanceUntilIdle()
        assertEquals(emptyList(), repo.writes.single())
        assertEquals(repo.defaults.items, vm.uiState.value.cards)
    }

    @Test
    fun changedBindingCannotSaveOldDraftIntoAnotherLedger() = layoutTest { repo ->
        val vm = com.ticketbox.viewmodel.DashboardLayoutViewModel(repo)
        vm.refresh()
        advanceUntilIdle()
        vm.beginEdit()
        vm.setVisible("reports", false)
        repo.access = repo.access.copy(binding = repo.access.binding.copy(ledgerId = "other"))
        vm.save()
        advanceUntilIdle()
        assertEquals(emptyList(), repo.writes)
        assertNull(vm.uiState.value.draft)
    }

    @Test
    fun readonlyAndFailedLoadDoNotOfferEditableDefaults() = layoutTest { repo ->
        repo.failLoad = true
        val vm = com.ticketbox.viewmodel.DashboardLayoutViewModel(repo)
        vm.refresh()
        advanceUntilIdle()
        vm.beginEdit()
        assertNull(vm.uiState.value.cards)
        assertNull(vm.uiState.value.draft)
        assertNotNull(vm.uiState.value.loadError)
        repo.failLoad = false
        repo.access = repo.access.copy(canModify = false)
        vm.refresh()
        advanceUntilIdle()
        vm.beginEdit()
        vm.save()
        assertNull(vm.uiState.value.draft)
        assertEquals(emptyList(), repo.writes)
    }

    private fun layoutTest(block: suspend TestScope.(LayoutActions) -> Unit) = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try { block(LayoutActions()) } finally { Dispatchers.resetMain() }
    }
}

private class LayoutActions : DashboardCardsActions {
    var access = LedgerAccessContext(LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "binding"), true)
    val defaults = DashboardCards(DashboardSurface.Android, listOf(
        DashboardCard("monthly_spend", "本月支出", true, 0),
        DashboardCard("reports", "趋势报表", true, 1),
    ))
    var failSave = false
    var failLoad = false
    val writes = mutableListOf<List<DashboardCardUpdate>>()
    override fun canModifyLedger() = access.canModify
    override fun dashboardAccess() = access
    override suspend fun dashboardCards(binding: LogicalSessionBinding, surface: DashboardSurface): Result<DashboardCards> =
        if (failLoad) Result.failure(IllegalStateException("offline")) else Result.success(defaults)

    override suspend fun updateDashboardCards(
        binding: LogicalSessionBinding,
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> {
        assertEquals(access.binding, binding)
        writes += updates
        return if (failSave) Result.failure(IllegalStateException("offline")) else Result.success(
            if (updates.isEmpty()) defaults else DashboardCards(surface, updates.map {
                DashboardCard(it.key, defaults.items.single { card -> card.key == it.key }.title, it.visible, it.position)
            }),
        )
    }
}
