package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.BuildConfig
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.BackgroundTaskListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.File

/** The outer and inner controllers, route callbacks and detail factories are all production code. */
class FactEntryNavigationTest {
    @JvmField
    @Rule
    val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context)
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController
    private val launchRequest = mutableStateOf<LaunchIntentRequest?>(null)
    private val handledLaunches = mutableListOf<LaunchIntentRequest>()
    private val sharedImage = File(context.cacheDir, "fact-navigation-share.png")

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
        sharedImage.delete()
    }

    @Test fun reviewShortcutLeavesTheFactAndReachesInbox() {
        installMainGraph()
        openFact()
        val request = LaunchIntentRequest.Navigate(ShortcutTarget.ReviewPending)
        compose.runOnIdle { launchRequest.value = request }
        compose.waitForIdle()
        compose.runOnIdle {
            assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(MainProductDestination.Domain(PrimaryDomain.Inbox), harness.shell.activeDestination)
            assertEquals(listOf(request), handledLaunches)
        }
    }

    @Test fun shareFromFactReachesDurableAcceptanceBeforeAcknowledgingTheOriginalSelection() {
        sharedImage.writeBytes(harness.fixture.network.originalImage)
        installMainGraph()
        openFact()
        val request = LaunchIntentRequest.ShareImages("ad4ef4c7-93fb-4cb2-97b4-6b318a6c1b08",
            listOf(Uri.fromFile(sharedImage).toString()), "UTC")
        compose.runOnIdle { launchRequest.value = request }
        compose.waitUntil(5_000) { handledLaunches.contains(request) }
        compose.runOnIdle {
            assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(listOf(request), handledLaunches)
            assertTrue(!harness.shell.launchAction.containsUpload(request.batchId))
        }
        val rows = harness.fixture.stored()
        assertEquals(1, rows.size)
        assertEquals("pending", rows.single()["status"])
        assertTrue(requireNotNull(rows.single()["payload"]).contains(request.batchId))
    }

    @Test fun confirmCompletesTheEditorAndRefreshesInboxInsteadOfBecomingAnUnfinishedFactRoute() {
        harness.fixture.network.current = harness.fixture.network.current.copy(status = "pending", confirmedAt = null)
        installMainGraph()
        compose.runOnIdle { outer.navigate(expenseRoute(42L)) }
        val confirm = context.getString(R.string.expense_edit_confirm_button)
        waitForText(confirm)
        compose.onNodeWithText(confirm).performClick()
        compose.waitUntil(5_000) { harness.shell.expenseEditCompletionRevision == 1 }
        compose.waitForIdle()
        compose.runOnIdle {
            assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(1, harness.shell.expenseEditCompletionRevision)
            assertEquals("confirmed", harness.fixture.network.current.status)
            assertEquals(listOf("save", "confirm"), harness.fixture.network.editCalls)
        }
    }

    @Test fun factWithoutThumbnailStillOpensItsProtectedOriginal() {
        harness.fixture.network.current = harness.fixture.network.current.copy(imagePath = "synthetic/original.png")
        installMainGraph()
        openFact()
        val original = context.getString(R.string.expense_fact_image_view_full)
        waitForText(original)
        compose.onNodeWithText(original).performScrollTo().performClick()
        compose.waitUntil(5_000) { harness.fixture.network.imageReads.size == 1 }
        compose.waitForIdle()
        compose.onNodeWithContentDescription(context.getString(R.string.components_async_image_content_description))
            .performScrollTo().assertIsDisplayed()
        assertEquals(listOf(42L), harness.fixture.network.imageReads)
    }

    @Test fun splitSaveShowsTheOriginalAtItsActionWithoutScrollingBackToThePageTop() {
        harness.fixture.network.splitMembers = listOf(com.ticketbox.data.remote.dto.LedgerMemberDto(
            memberId = 22, accountId = 22, accountPublicId = "split-peer", accountName = "接收家人",
            role = "member", createdAt = null, disabledAt = null, isSelf = false))
        installMainGraph()
        openFact()
        val start = context.getString(R.string.expense_edit_bill_split_start_button)
        waitForText(start)
        compose.onNodeWithText(start).performScrollTo().performClick()
        waitForText("接收家人")
        compose.onNodeWithText("接收家人").performClick()
        compose.onNode(hasSetTextAction()).performTextReplacement("4")
        compose.onNodeWithText(context.getString(R.string.expense_edit_bill_split_sheet_send_button))
            .performScrollTo().performClick()
        val waiting = context.getString(R.string.bill_split_submission_waiting)
        waitForText(waiting)
        compose.waitForIdle()
        // The user remains where they submitted; no scroll is used to find the receipt.
        compose.onNodeWithText(waiting).assertIsDisplayed()
        compose.onNodeWithText(start).assertIsNotEnabled()
        assertEquals("create_bill_split_invitation", harness.fixture.stored().single()["type"])
        assertEquals("pending", harness.fixture.stored().single()["status"])
    }

    @Test fun confirmedReceiptDoesNotReturnToPendingWhenTheRefreshFails() {
        val network = harness.fixture.network
        network.current = network.current.copy(status = "pending", confirmedAt = null)
        network.stopPendingReadsAfterConfirm = true
        installMainGraph()
        waitForText(requireNotNull(network.current.merchant))
        compose.runOnIdle { outer.navigate(expenseRoute(42L)) }
        val confirm = context.getString(R.string.expense_edit_confirm_button)
        waitForText(confirm)
        compose.onNodeWithText(confirm).performClick()
        compose.waitUntil(5_000) { harness.shell.expenseEditCompletionRevision == 1 && network.failedPendingReads > 0 }
        compose.waitForIdle()
        compose.onAllNodesWithText(requireNotNull(network.current.merchant)).assertCountEquals(0)
        assertEquals("confirmed", network.current.status)
        assertEquals(1, runBlocking { harness.fixture.expenseDao.getConfirmed("correction-ledger") }.size)
    }

    private fun openFact() {
        compose.runOnIdle { outer.navigate(expenseRoute(42L)) }
        waitForText(context.getString(R.string.expense_fact_title))
        compose.waitForIdle()
    }

    @Test fun externalCaptureKeepsTheUnsubmittedEditorOnTheReturnStack() {
        val network = harness.fixture.network
        network.current = network.current.copy(status = "pending", confirmedAt = null)
        installMainGraph()
        compose.runOnIdle { outer.openExpense(42L) }
        waitForText(context.getString(R.string.expense_edit_confirm_button))
        compose.onNode(hasSetTextAction() and hasText(requireNotNull(network.current.merchant)))
            .performTextReplacement("未提交的商家")
        compose.runOnIdle { launchRequest.value = LaunchIntentRequest.Navigate(ShortcutTarget.ReviewPending) }
        compose.waitForIdle()
        compose.runOnIdle {
            assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(EXPENSE_ROUTE, outer.previousBackStackEntry?.destination?.route)
            outer.popBackStack()
        }
        waitForText("未提交的商家")
        compose.onNode(hasSetTextAction() and hasText("未提交的商家")).assertExists()
        assertTrue(network.editCalls.isEmpty())
        assertEquals("家庭午餐", network.current.merchant)
    }

    @Test fun workspaceRecoveryOpensTheRealFactAndReturnsToItsOriginalSubmission() {
        val original = runBlocking { harness.saveFailedCorrection() }
        installMainGraph()
        compose.runOnIdle { harness.shell.openAccount() }
        val entry = context.getString(R.string.settings_root_entry_offline_sync_title)
        waitForText(entry)
        compose.onNodeWithText(entry)
            .performScrollTo().performClick()
        openRecoveryFactAndReturn()
        assertEquals(original, harness.fixture.stored().single())
        assertEquals(MainProductDestination.Workspace, harness.shell.activeDestination)
    }

    @Test fun incompatibleConnectionLeadsToTheExistingIntentWithoutSettlingOrReplayingIt() {
        val original = runBlocking { harness.saveFailedCorrection() }
        val binding = harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding()
        harness.fixture.network.diagnosticApiVersion = "different-protocol"
        installMainGraph()
        compose.runOnIdle { harness.shell.openAccount() }
        val entry = context.getString(
            if (BuildConfig.SHOW_ADVANCED_TOOLS) R.string.settings_root_connection_title_advanced
            else R.string.settings_root_connection_title_basic,
        )
        waitForText(entry)
        compose.onNodeWithText(entry).performScrollTo().performClick()
        waitForText("检查连接")
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasText("检查连接") and isEnabled()).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText("检查连接").performScrollTo().performClick()

        val nextStep = "请将手机应用与服务端更新到配套版本，再重新检测。"
        waitForText(nextStep)
        compose.onNodeWithText(nextStep).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("查看未发送的操作").performScrollTo().performClick()
        openRecoveryFactAndReturn()

        assertEquals(listOf("auth", "compatibility"), harness.fixture.network.diagnosticReads)
        assertEquals(binding, harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding())
        assertEquals(original, harness.fixture.stored().single())
        assertTrue(harness.fixture.network.calls.isEmpty())
    }

    @Test fun failedRecognitionTaskOpensItsOriginalBillThroughTheRealWorkspace() {
        val network = harness.fixture.network
        network.current = network.current.copy(status = "pending", confirmedAt = null)
        network.backgroundTasks = requireNotNull(Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
            .adapter(BackgroundTaskListResponseDto::class.java).fromJson("""
                {"items":[{"public_id":"original-recognition","task_type":"expense_enrichment",
                "status":"failed","source_expense_id":42,"error_code":"RuntimeError",
                "error_message":"recognition unavailable","created_at":"2026-09-07T00:00:00Z"}]}
            """.trimIndent()))
        installMainGraph()
        compose.runOnIdle { harness.shell.openAccount() }
        val entry = context.getString(R.string.settings_root_entry_background_tasks_title)
        waitForText(entry)
        compose.onNodeWithText(entry).performScrollTo().performClick()
        waitForText("打开原账单")
        compose.onNodeWithText("打开原账单").performScrollTo().performClick()
        waitForText(context.getString(R.string.expense_edit_confirm_button))
        compose.runOnIdle {
            assertEquals(EXPENSE_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(42L, outer.currentBackStackEntry?.arguments?.getLong(EXPENSE_ID_ARG))
            assertTrue(network.editCalls.isEmpty())
            outer.popBackStack()
        }
        waitForText("打开原账单")
        assertEquals(MainProductDestination.Workspace, harness.shell.activeDestination)
    }

    @Test fun obligationRecoveryOpensTheRealFactAndReturnsToItsOriginalSubmission() {
        val original = runBlocking { harness.saveFailedCorrection() }
        installMainGraph()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.ObligationSync) }
        openRecoveryFactAndReturn()
        assertEquals(original, harness.fixture.stored().single())
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.ObligationSync), harness.shell.activeDestination)
    }

    @Test fun recurringPaymentOpensItsExactFactAndReturnsToItsRefreshedPeriod() {
        installMainGraph()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.Recurring) }
        waitForText(context.getString(R.string.recurring_hero_meta, 1))
        val openOccurrence = context.getString(R.string.occurrence_open)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(openOccurrence))
        compose.onNodeWithText("家庭固定支出").assertIsDisplayed()
        compose.onNodeWithText(openOccurrence).performClick()
        val openPayment = context.getString(R.string.occurrence_open_payment)
        waitForText(openPayment)
        compose.onNodeWithText(openPayment).performScrollTo().performClick()
        assertRealFactAndReturn()
        waitForText(openPayment)
        compose.onNodeWithTag("occurrence-period").assertExists()
        compose.waitUntil(5_000) { harness.fixture.network.occurrenceReads.size > 1 }
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.Recurring), harness.shell.activeDestination)
        assertEquals("navigation-recurring", harness.fixture.network.occurrenceReads.last().first)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    private fun openRecoveryFactAndReturn() {
        val original = harness.fixture.stored().single()
        val binding = requireNotNull(harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding())
        waitForText("原因：导航核对原提交")
        compose.onNodeWithText("原因：导航核对原提交").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("刷新并核对当前事实").performScrollTo().performClick()
        assertRealFactAndReturn()
        assertEquals(original, harness.fixture.stored().single())
        assertEquals(binding, harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding())
        assertTrue(harness.fixture.network.calls.isEmpty())
        waitForText(context.getString(R.string.sync_status_page_subtitle))
        compose.onNodeWithText(context.getString(R.string.sync_status_page_subtitle)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_page_title)).performScrollTo().assertIsDisplayed()
        waitForText("原因：导航核对原提交")
        compose.onNodeWithText("原因：导航核对原提交").performScrollTo().assertIsDisplayed()
    }

    private fun assertRealFactAndReturn() {
        waitForText(context.getString(R.string.expense_fact_title))
        compose.onNodeWithText(context.getString(R.string.expense_fact_title)).assertIsDisplayed()
        waitForText("更正这笔账单")
        compose.onNodeWithText("更正这笔账单").performScrollTo().assertIsDisplayed()
        compose.runOnIdle {
            assertEquals(EXPENSE_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(42L, outer.currentBackStackEntry?.arguments?.getLong(EXPENSE_ID_ARG))
            assertTrue(harness.fixture.network.expenseReads.contains(42L))
            assertTrue(harness.fixture.network.calls.isEmpty())
        }
        // ExpenseFactScreen supplies backText="" to the production AppBackButton's semantics.
        compose.onNode(hasContentDescription("") and hasClickAction()).performScrollTo().performClick()
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route) }
    }

    private fun waitForText(text: String) {
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun installMainGraph() {
        compose.setContent {
            if (mounted.value) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                    TicketboxTheme(skin = AppSkin.Paper) {
                        val controller = rememberNavController()
                        outer = controller
                        LaunchRequestEffect(launchRequest.value, harness.shell, controller) { handledLaunches += it }
                        MainNavGraph(
                            MainNavigationRuntime(controller, harness.shell, harness.screenFactory),
                            remember { SnackbarHostState() },
                            SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                                onThemeModeChange = { error("Navigation must not change appearance") },
                                onCurrencyChange = { error("Navigation must not change currency") }),
                            onBindingCleared = { error("Navigation must preserve its binding") },
                        )
                    }
                }
            }
        }
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route) }
    }
}
