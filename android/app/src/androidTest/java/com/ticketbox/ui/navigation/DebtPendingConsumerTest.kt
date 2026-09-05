package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.repository.DebtCreationPendingState
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Mounts the genuine shared chrome used by both personal lists, with explicitly synthetic intent data. */
class DebtPendingConsumerTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private var recoveryOpened = false

    @Test
    fun payablesShowLocalIntentAndOpenExistingRecovery() {
        show(AppSkin.Paper, ObligationsView.I_OWE, DebtCreationPendingState.Waiting)
        assertPendingVisible(R.string.debt_create_pending_waiting)
        saveConsumerArtPreview("debt-pending-paper", compose.onRoot().captureToImage().asAndroidBitmap())
        compose.onNodeWithText(context.getString(R.string.debt_create_pending_manage)).performClick()
        compose.runOnIdle { assertTrue(recoveryOpened) }
    }

    @Test
    fun receivablesKeepFailedIntentReadableAfterRoleBecomesReadOnly() {
        show(AppSkin.Midnight, ObligationsView.OWED_TO_ME, DebtCreationPendingState.NeedsAttention)
        assertPendingVisible(R.string.debt_create_pending_attention)
        compose.onNodeWithText(context.getString(R.string.debt_list_add)).assertDoesNotExist()
        saveConsumerArtPreview("debt-pending-midnight-viewer", compose.onRoot().captureToImage().asAndroidBitmap())
        compose.onNodeWithText(context.getString(R.string.debt_create_pending_manage)).performClick()
        compose.runOnIdle { assertTrue(recoveryOpened) }
    }

    private fun show(skin: AppSkin, view: ObligationsView, pendingState: DebtCreationPendingState) {
        val intent = PendingDebtCreation(
            intentId = 1L, state = pendingState, homeCurrency = CurrencyCode.CNY,
            draft = DebtDraft(DebtDirections.OWED_TO_ME, "小王", 12_345L, note = "出差垫付车费"),
        )
        val composer = RelationsComposerHandles(
            canModify = skin == AppSkin.Paper, isParsingBill = false, flashMessage = null, error = null,
            pendingCreations = listOf(intent),
            actions = RelationsComposerActions(
                onRetry = {}, onAddDebt = {}, onParseBillImage = {},
                onOpenSyncStatus = { recoveryOpened = true },
            ),
        )
        compose.setContent {
            TicketboxTheme(skin = skin) {
                Surface(Modifier.fillMaxSize()) {
                    androidx.compose.foundation.layout.Column(Modifier.padding(20.dp)) {
                        ObligationsPrimaryChrome(view, onSelectView = {}, composer = composer)
                    }
                }
            }
        }
    }

    private fun assertPendingVisible(statusRes: Int) {
        compose.onNodeWithText("小王").assertIsDisplayed()
        compose.onNodeWithText("出差垫付车费").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.debt_create_pending_body)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(statusRes), substring = true).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.debt_create_added)).assertDoesNotExist()
    }
}
