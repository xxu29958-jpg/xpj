package com.ticketbox.viewmodel

import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.domain.model.CurrencyCode
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
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * 收入编辑窄回归（原月份与绑定先保存本机；归档收编辑器内）：
 * openEdit 捕获打开时的 binding + rowVersion 作 baseline；成功才关编辑器（succeeded
 * ack，与主 VM addSucceeded 同一约定）；失败留草稿；切账本后编辑会话随状态重置失权，
 * 不写向新账本。伴随 VM 与列表 VM 分离（同 DebtRepaymentHistoryViewModel 先例）。
 * 共享夹具见 IncomePlanEditViewModelFixtures；busy/币种守卫见 IncomePlanEditViewModelGuardsTest。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanEditViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun openEditUsesConfirmedMonthAndCapturesBaseline() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0))
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()

        viewModel.openEdit(plan, "2026-09")

        val session = viewModel.state.value.session
        assertNotNull(session)
        assertEquals("p1", session.publicId)
        assertEquals(7L, session.baselineRowVersion)
        assertEquals(editAccess().binding, session.binding)
        assertEquals(plan.label, session.draft.label)
        assertEquals("2026-09", session.draft.intentMonth)
        assertEquals("2026-09", session.draft.incomeMonthInput)
        assertEquals("123.00", session.draft.amountYuanInput)
        assertEquals(plan.payDay.toString(), session.draft.payDayInput)
        assertEquals(plan.frequency, session.draft.frequency)
        assertEquals(CurrencyCode.CNY, session.draft.homeCurrency)
        assertFalse(viewModel.state.value.succeeded)
    }

    @Test
    fun viewerCannotOpenEditor() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300)
        val repo = FakeIncomePlanEditRepository(
            active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0),
            canModify = false,
        )
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()

        viewModel.openEdit(plan, "2026-09")

        assertNull(viewModel.state.value.session)
    }

    @Test
    fun acceptedEditRetainsTheDisplayedMonthAcrossRollover() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0))
        var dataChanged = 0
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions(),
            onDataChanged = { dataChanged += 1 })
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")
        viewModel.updateDraftField(IncomePlanDraftField.Label, "新工资")
        assertEquals("2026-09", viewModel.state.value.session?.draft?.intentMonth)
        repo.active = repo.active.copy(month = "2026-10")

        viewModel.submit()
        advanceUntilIdle()

        val call = repo.updateCalls.single()
        assertEquals(editAccess().binding, call.binding)
        assertEquals("p1", call.publicId)
        assertEquals(7L, call.patch.expectedRowVersion)
        assertEquals("新工资", call.patch.label)
        assertEquals(12_300L, call.patch.amountCents)
        assertEquals(10, call.patch.payDay)
        assertEquals("2026-09", call.patch.intentMonth)
        assertEquals(plan, call.baseline)
        assertEquals(CurrencyCode.CNY, call.currency)
        assertEquals(com.ticketbox.domain.model.UiText.res(com.ticketbox.R.string.income_plan_edit_saved_locally),
            viewModel.state.value.flashMessage)
        assertTrue(viewModel.state.value.succeeded)
        assertFalse(viewModel.state.value.isSubmitting)
        assertEquals(1, dataChanged)
    }

    @Test
    fun submitFailureKeepsDraftAndEditorOpen() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0))
        repo.updateResult = Result.failure(RuntimeException("boom"))
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")
        viewModel.updateDraftField(IncomePlanDraftField.Label, "新工资")

        viewModel.submit()
        advanceUntilIdle()

        val session = viewModel.state.value.session
        assertNotNull(session)
        assertEquals("新工资", session.draft.label)
        assertNotNull(session.draft.validationError)
        assertFalse(viewModel.state.value.succeeded)
        assertFalse(viewModel.state.value.isSubmitting)
    }

    @Test
    fun invalidDraftNeverReachesRepository() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0))
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")
        viewModel.updateDraftField(IncomePlanDraftField.Label, "   ")

        viewModel.submit()
        advanceUntilIdle()

        assertTrue(repo.updateCalls.isEmpty())
        assertNotNull(viewModel.state.value.session?.draft?.validationError)
    }

    @Test
    fun ledgerSwitchClosesEditorAndLosesWriteAuthority() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0))
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")

        repo.activeAccessFlow.value = editAccess(ledgerId = "family", ownerKey = "family-owner")
        advanceUntilIdle()

        assertNull(viewModel.state.value.session)
        viewModel.submit()
        advanceUntilIdle()
        assertTrue(repo.updateCalls.isEmpty())
    }

    @Test
    fun archiveFromEditSuccessClosesSession() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0))
        var dataChanged = 0
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions(), onDataChanged = { dataChanged += 1 })
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")

        viewModel.archiveFromEdit()
        advanceUntilIdle()

        val call = repo.archiveCalls.single()
        assertEquals(editAccess().binding, call.binding)
        assertEquals("p1", call.publicId)
        assertEquals(7L, call.rowVersion)
        assertNull(viewModel.state.value.session)
        assertTrue(viewModel.state.value.succeeded)
        assertEquals(1, dataChanged)
    }

    @Test
    fun archiveFromEditFailureKeepsDraft() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300, rowVersion = 7L)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0))
        repo.archiveResult = Result.failure(RuntimeException("boom"))
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")

        viewModel.archiveFromEdit()
        advanceUntilIdle()

        val session = viewModel.state.value.session
        assertNotNull(session)
        assertNotNull(session.draft.validationError)
        assertFalse(viewModel.state.value.isSubmitting)
    }

    @Test
    fun dismissClearsSession() = runTest(dispatcher) {
        val plan = editPlan("p1", 12_300)
        val repo = FakeIncomePlanEditRepository(active = IncomePlanListing(listOf(plan), 12_300, month = "2026-09", scheduledAmountCents = 0, effectivePlanCount = 0))
        val viewModel = IncomePlanEditViewModel(repo, CapabilityDebtActions())
        advanceUntilIdle()
        viewModel.openEdit(plan, "2026-09")

        viewModel.dismiss()

        assertNull(viewModel.state.value.session)
        assertFalse(viewModel.state.value.succeeded)
        assertFalse(viewModel.state.value.isSubmitting)
    }
}
