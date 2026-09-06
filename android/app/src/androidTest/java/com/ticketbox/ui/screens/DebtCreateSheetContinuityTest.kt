package com.ticketbox.ui.screens

import android.view.View
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.window.DialogWindowProvider
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtCreationActions
import com.ticketbox.data.repository.DebtCreationPendingState
import com.ticketbox.data.repository.DebtCreationQueueSnapshot
import com.ticketbox.data.repository.DebtCreationReceipt
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtListViewModel
import java.lang.reflect.Proxy
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real list -> form -> ViewModel -> local-acceptance consumer; the persistence boundary is gated. */
class DebtCreateSheetContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private lateinit var viewModel: DebtListViewModel

    @After
    fun stopViewModel() {
        if (::viewModel.isInitialized) compose.runOnIdle { viewModel.viewModelScope.cancel() }
    }

    @Test
    fun saveIsReachableAndSubmittedFieldsFreezeUntilLocalAcceptance() {
        val creation = SheetCreationGate()
        compose.setContent {
            viewModel = remember { DebtListViewModel(sheetQueries(), creation) }
            TicketboxTheme(skin = AppSkin.Paper) {
                DebtListScreen(
                    viewModel,
                    DebtListScreenActions(onBack = {}, onOpenDebt = {}, onParseBillImage = {}, onOpenSyncStatus = {}),
                )
            }
        }
        compose.waitUntil(5_000) { ::viewModel.isInitialized && viewModel.state.value.homeCurrencyResolved }
        compose.onNodeWithText(context.getString(R.string.debt_list_add)).performClick()
        compose.onAllNodes(hasSetTextAction())[0].performTextInput("小王")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performClick().performTextInput("123.45")
        compose.onNodeWithText(context.getString(R.string.debt_create_save))
            .performScrollTo().assertIsDisplayed().assertIsEnabled()
        capture("debt-create-editing")
        val touchBefore = saveObservation()
        compose.onNode(hasText(context.getString(R.string.debt_create_save)) and hasClickAction()).performTouchInput {
            assertTrue("Save injection visibleSize=$visibleSize; before=[$touchBefore]", width > 0 && height > 0)
            click()
        }
        runCatching { compose.waitUntil(5_000) { viewModel.state.value.isSubmitting } }.getOrElse { error ->
            val observed = viewModel.state.value
            throw AssertionError("Save did not enter submission: canModify=${observed.canModify}, " +
                "currencyReady=${observed.homeCurrencyResolved}, parsing=${observed.isParsingBill}, " +
                "amountValid=${observed.addDraft.parsedAmountCents() != null}, " +
                "labelPresent=${observed.addDraft.counterpartyLabel.isNotBlank()}, " +
                "validation=${observed.addDraft.validationError}, calls=${creation.submitted.size}; " +
                "before=[$touchBefore]; after=[${saveObservation()}]", error)
        }

        compose.onNodeWithText("小王").assertIsNotEnabled()
        compose.onNodeWithText("123.45").assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.debt_create_submitting)).assertIsNotEnabled()
        capture("debt-create-busy")
        creation.accept.complete(Unit)
        compose.waitUntil(5_000) { viewModel.state.value.pendingCreations.isNotEmpty() && !viewModel.state.value.isSubmitting }
        compose.onNodeWithText(context.getString(R.string.debt_create_pending_body)).assertIsDisplayed()
        compose.runOnIdle {
            assertEquals(1, creation.submitted.size)
            assertEquals(12_345L, creation.submitted.single().principalAmountCents)
            assertTrue(viewModel.state.value.debts.isEmpty())
        }
    }

    private fun saveObservation(): String {
        val node = compose.onNodeWithText(context.getString(R.string.debt_create_save)).fetchSemanticsNode()
        val label = compose.onNodeWithText(context.getString(R.string.debt_create_save), useUnmergedTree = true)
            .fetchSemanticsNode()
        val root = requireNotNull(node.root) as ViewRootForTest
        return compose.runOnIdle {
            val view = root.view
            val window = generateSequence(view) { it.parent as? View }
                .filterIsInstance<DialogWindowProvider>().first().window
            "attached=${view.isAttachedToWindow}, focus=${view.hasWindowFocus()}, " +
                "decorFocus=${window.decorView.hasWindowFocus()}, resumed=${root.isLifecycleInResumedState}, " +
                "pendingLayout=${root.hasPendingMeasureOrLayout}, bounds=${node.boundsInRoot}, " +
                "touch=${node.touchBoundsInRoot}, windowBounds=${node.boundsInWindow}, " +
                "buttonId=${node.id}, buttonSize=${node.size}, buttonPosition=${node.positionInRoot}, " +
                "labelId=${label.id}, labelSize=${label.size}, labelPosition=${label.positionInRoot}, " +
                "labelBounds=${label.boundsInRoot}"
        }
    }

    private fun capture(name: String) {
        val bitmap = requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot())
        saveConsumerArtPreview(name, bitmap)
    }
}

private class SheetCreationGate : DebtCreationActions {
    private val access = LedgerAccessContext(
        LogicalSessionBinding("https://sheet.example.test", "ledger", "synthetic-owner", "session", "binding"), true,
    )
    private val pending = MutableStateFlow(DebtCreationQueueSnapshot(access.binding))
    val accept = CompletableDeferred<Unit>()
    val submitted = mutableListOf<DebtDraft>()
    override fun currentAccess() = access
    override fun observeActiveLedgerAccess() = flowOf(access)
    override fun observePendingCreations() = pending
    override fun describePendingCreation(row: OutboxRow): PendingDebtCreation? =
        pending.value.intents.singleOrNull { it.intentId == row.id }
    override suspend fun createDebt(
        expectedBinding: LogicalSessionBinding,
        draft: DebtDraft,
        homeCurrency: CurrencyCode,
    ): Result<DebtCreationReceipt> {
        submitted += draft
        accept.await()
        pending.value = DebtCreationQueueSnapshot(
            expectedBinding, listOf(PendingDebtCreation(1L, DebtCreationPendingState.Waiting, draft, homeCurrency)),
        )
        return Result.success(DebtCreationReceipt(1L, expectedBinding))
    }
}

private fun sheetQueries(): DebtActions {
    val uncalled = Proxy.newProxyInstance(DebtActions::class.java.classLoader, arrayOf(DebtActions::class.java)) { _, method, _ ->
        error("Unexpected sheet fixture call: ${method.name}")
    } as DebtActions
    return object : DebtActions by uncalled {
        override fun canModifyLedger() = true
        override suspend fun listDebts(lens: DebtListLens) = Result.success(DebtListPage(emptyList(), "CNY"))
    }
}
