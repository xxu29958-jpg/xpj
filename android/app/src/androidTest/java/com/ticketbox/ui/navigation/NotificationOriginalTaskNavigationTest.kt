package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import com.ticketbox.ui.assertEditableTextEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.notification.NotificationDestination
import com.ticketbox.notification.NotificationTask
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Production launch effect, nested navigation and repositories; only the remote transport is controlled. */
class NotificationOriginalTaskNavigationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val transport = BudgetNavigationTransport("2026-09", "2026-07")
    private val harness = FactEntryNavigationHarness(context, transport::wrap)
    private val mounted = mutableStateOf(true)
    private val request = mutableStateOf<LaunchIntentRequest?>(null)
    private lateinit var outer: NavHostController
    private val binding get() = requireNotNull(harness.screenFactory.repository.captureDeferredLedgerBinding())

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun coldAndHotRemindersOpenTheirOwnMonthsAndBackKeepsTheUnsubmittedAmount() {
        request.value = LaunchIntentRequest.OpenNotification(NotificationTask(binding, NotificationDestination.Budget("2026-07")))
        show()
        waitForMonth("2026-07")
        compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("budget_total_amount")))
            .performScrollTo().performTextReplacement("321.09")

        compose.runOnIdle {
            request.value = LaunchIntentRequest.OpenNotification(NotificationTask(binding, NotificationDestination.Budget("2026-08")))
        }
        waitForMonth("2026-08")
        assertEquals(listOf("2026-07", "2026-08"), transport.budgetReads.toList())
        compose.onNodeWithContentDescription(context.getString(R.string.budget_back_to_stats)).performClick()
        waitForMonth("2026-07")
        compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("budget_total_amount")))
            .performScrollTo().assertEditableTextEquals("321.09")
        assertEquals("A notification may not turn raw form input into a queued command", 0,
            kotlinx.coroutines.runBlocking { harness.fixture.stored().size })
    }

    @Test fun restoredReminderCannotReadTheCurrentOwnersSameMonth() {
        val original = NotificationTask(binding.copy(ownerKey = "original-other-account"), NotificationDestination.Budget("2026-07"))
        request.value = LaunchIntentRequest.OpenNotification(original)
        val restoration = show()
        val blocked = context.getString(R.string.notification_original_binding_required)
        waitForText(blocked)
        assertEquals(emptyList<String>(), transport.budgetReads.toList())
        restoration.emulateSavedInstanceStateRestore()
        waitForText(blocked)
        compose.onNodeWithText(blocked).assertIsDisplayed()
        assertEquals(emptyList<String>(), transport.budgetReads.toList())
    }

    @Test fun backupReminderOpensTheActualPublishedRecordAndItsNextStep() {
        request.value = LaunchIntentRequest.OpenNotification(NotificationTask(binding, NotificationDestination.Backup))
        show()
        waitForText(context.getString(R.string.settings_backup_never))
        compose.onNodeWithText(context.getString(R.string.settings_backup_title)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.settings_backup_next_step)).assertIsDisplayed()
        assertTrue(transport.backupReads > 0)
        assertEquals(0, kotlinx.coroutines.runBlocking { harness.fixture.stored().size })
    }

    private fun show(): StateRestorationTester {
        val restoration = StateRestorationTester(compose)
        restoration.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    outer = rememberNavController()
                    LaunchRequestEffect(request.value, harness.shell, outer, { handled ->
                        if (request.value == handled) request.value = null
                    })
                    MainNavGraph(MainNavigationRuntime(outer, harness.shell, harness.screenFactory),
                        remember { SnackbarHostState() },
                        SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY, {}, {}),
                        onBindingCleared = { error("Notification must never switch identity") })
                }
            }
        }
        compose.waitForIdle()
        return restoration
    }

    private fun waitForMonth(month: String) {
        waitForText(context.getString(R.string.budget_header_subtitle, month))
        compose.waitUntil(5_000) { transport.budgetReads.contains(month) }
    }

    private fun waitForText(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }
    }
}
