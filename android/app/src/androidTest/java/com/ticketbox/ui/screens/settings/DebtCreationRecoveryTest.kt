package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.remember
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.ui.navigation.DataQualityConnectedHarness
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** Real create producer -> Room -> recovery ViewModel/screen -> guarded Room action. */
class DebtCreationRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private lateinit var harness: DataQualityConnectedHarness
    private lateinit var viewModel: OutboxStatusViewModel

    @After
    fun closeFixture() {
        if (::viewModel.isInitialized) compose.runOnIdle { viewModel.viewModelScope.cancel() }
        if (::harness.isInitialized) harness.close()
    }

    @Test
    fun originalContextIdentifiesTheDebtWhoseSameIntentIsRetried() {
        val originals = showTwoFailedDebts()
        compose.onNode(hasText("小王") and hasText("123.45", substring = true)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("出差垫付车费").assertIsDisplayed()
        capture("debt-recovery-records")

        actionFor("小王", "重试").performScrollTo().performClick()
        compose.waitUntil(5_000) { viewModel.uiState.value.status.failed.size == 1 }

        val rows = runBlocking {
            withTimeout(5_000) {
                harness.screenFactory.outboxRepository.observeActiveByTypes(setOf(PendingMutationType.CreateDebt))
                    .first { it.any { row -> row.id == originals.first.id && row.status == PendingMutationStatus.Pending } }
            }
        }
        val retried = rows.single { it.id == originals.first.id }
        assertEquals(originals.first.idempotencyKey, retried.idempotencyKey)
        assertEquals(originals.first.payloadJson, retried.payloadJson)
        assertEquals(originals.first.ownerKey, retried.ownerKey)
        assertEquals(listOf(originals.second.id), viewModel.uiState.value.status.failed.map { it.id })
        compose.onNode(hasText("小李") and hasText("86.00", substring = true)).performScrollTo().assertIsDisplayed()
    }

    @Test
    fun discardNamesTheSelectedDebtAndCancelPreservesBothOriginals() {
        val originals = showTwoFailedDebts()
        compose.onNodeWithText("小李").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("家庭采购垫付").assertIsDisplayed()
        actionFor("小李", "放弃").performScrollTo().performClick()

        dialogText("小李").assertIsDisplayed()
        dialogText("家庭采购垫付").assertIsDisplayed()
        compose.onNode(hasText("86.00", substring = true) and hasAnyAncestor(isDialog())).assertIsDisplayed()
        compose.onNode(hasText("不会撤销", substring = true) and hasAnyAncestor(isDialog())).assertIsDisplayed()
        capture("debt-recovery-discard")
        compose.onNodeWithText("取消").performClick()
        compose.runOnIdle {
            assertEquals(setOf(originals.first, originals.second), viewModel.uiState.value.status.failed.toSet())
        }

        actionFor("小李", "放弃").performScrollTo().performClick()
        dialogText("小李").assertIsDisplayed()
        compose.onNodeWithText("确定放弃").performClick()
        compose.waitUntil(5_000) { viewModel.uiState.value.status.failed.size == 1 }
        assertEquals(listOf(originals.first), viewModel.uiState.value.status.failed)
    }

    private fun showTwoFailedDebts(): Pair<OutboxRow, OutboxRow> {
        harness = DataQualityConnectedHarness()
        val factory = harness.screenFactory
        val originals = runBlocking {
            val creation = factory.debtCreationRepository
            val binding = requireNotNull(creation.currentAccess()).binding
            val first = creation.createDebt(binding, draft("小王", 12_345L, "出差垫付车费"), CurrencyCode.CNY).getOrThrow()
            val second = creation.createDebt(binding, draft("小李", 8_600L, "家庭采购垫付"), CurrencyCode.CNY).getOrThrow()
            factory.outboxRepository.markFailed(first.intentId, "debt_create_response_unverified")
            factory.outboxRepository.markFailed(second.intentId, "debt_create_response_unverified")
            val failed = withTimeout(5_000) { factory.outboxRepository.observeStatus().first { it.failed.size == 2 }.failed }
            failed.single { it.id == first.intentId } to failed.single { it.id == second.intentId }
        }
        compose.setContent {
            viewModel = remember {
                outboxStatusViewModelFactory(factory.outboxRepository, factory.repository)
                    .create(OutboxStatusViewModel::class.java)
            }
            TicketboxTheme(skin = AppSkin.Default) {
                SyncStatusScreen(viewModel, onBack = {})
            }
        }
        compose.waitUntil(5_000) { ::viewModel.isInitialized && viewModel.uiState.value.status.failed.size == 2 }
        return originals
    }

    private fun draft(label: String, amount: Long, note: String) = DebtDraft(
        direction = DebtDirections.OWED_TO_ME,
        counterpartyLabel = label,
        principalAmountCents = amount,
        note = note,
    )

    private fun actionFor(label: String, action: String): SemanticsNodeInteraction =
        compose.onNode(hasText(action) and hasAnyAncestor(hasText(label)))

    private fun dialogText(text: String): SemanticsNodeInteraction =
        compose.onNode(hasText(text) and hasAnyAncestor(isDialog()))

    private fun capture(name: String) {
        val bitmap = requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot())
        saveConsumerArtPreview(name, bitmap)
    }
}
