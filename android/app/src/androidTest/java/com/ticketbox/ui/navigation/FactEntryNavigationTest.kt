package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
import android.app.Activity
import android.content.Intent
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.contract.ActivityResultContract
import androidx.core.app.ActivityOptionsCompat
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.screens.expense.TAG_TAGS_FIELD
import com.ticketbox.R
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.originalPayloadAdapter
import com.ticketbox.data.repository.originalReceiptAdapter
import com.ticketbox.data.repository.UploadIntentFileStore
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.BackgroundTaskListResponseDto
import com.ticketbox.data.remote.dto.OriginalCommandReceiptDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.CompletableDeferred
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.File

/** The outer and inner controllers, route callbacks and detail factories are all production code. */
class FactEntryNavigationTest {
    @JvmField
    @Rule
    val compose = createComposeRule()
    @JvmField
    @Rule
    val keyboard = RealKeyboard()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context)
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController
    private val launchRequest = mutableStateOf<LaunchIntentRequest?>(null)
    private val handledLaunches = mutableListOf<LaunchIntentRequest>()
    private val sharedImage = File(context.cacheDir, "fact-navigation-share.png")

    @Test fun factReadingAndOriginalKeepTheSameNavigationOwner() {
        prepareFactCapture()
        installMainGraph()
        openFact()
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(300, 3_000)
        saveConsumerArtPreview("fact-overview", requireNotNull(automation.takeScreenshot()))
        compose.onNodeWithText(context.getString(R.string.expense_fact_original_spend)).performScrollTo()
        automation.waitForIdle(300, 3_000)
        saveConsumerArtPreview("fact-money", requireNotNull(automation.takeScreenshot()))
        compose.onNodeWithText(context.getString(R.string.expense_fact_history_entry))
            .performScrollTo().performClick()
        waitForText(context.getString(R.string.expense_fact_history_heading))
        automation.waitForIdle(300, 3_000)
        saveConsumerArtPreview("fact-history", requireNotNull(automation.takeScreenshot()))
        compose.onNodeWithText(context.getString(R.string.expense_fact_title)).performClick()
        waitForText(context.getString(R.string.expense_fact_original_spend))
        compose.onNodeWithText(context.getString(R.string.expense_fact_correct_cta))
            .performScrollTo().performClick()
        waitForText(context.getString(R.string.expense_correction_sheet_title))
    }

    private fun prepareFactCapture() {
        if (InstrumentationRegistry.getArguments().getString("captureRefund") == "true") {
            val longContent = InstrumentationRegistry.getArguments().getString("captureLong") == "true"
            val amount = if (longContent) Long.MAX_VALUE else 12000L
            harness.fixture.network.current = harness.fixture.network.current.copy(
                merchant = if (longContent) "一家名称很长但需要完整识别的家庭采购商店" else "街角小馆",
                amountCents = amount, originalAmountMinor = amount)
            harness.fixture.network.financialSummary = com.ticketbox.data.remote.dto.ExpenseFinancialSummaryDto(
                amount, amount, amount, 2000L, amount - 2000L, amount - 2000L, 0L,
                com.ticketbox.data.remote.dto.ExpenseLineageStatusDto.PartiallyRefunded)
            val confirmed = com.ticketbox.data.remote.dto.ExpenseRevisionDto("history-confirmed", 1, "confirmed", "首次确认",
                emptyList(), after = mapOf("original_currency_code" to "CNY", "original_amount_minor" to amount),
                createdAt = "2026-10-03T04:35:00Z")
            harness.fixture.network.historyOverride = listOf(
                confirmed.copy(publicId = "history-refund", offsetPublicId = "refund-1", changeKind = "created",
                    reason = "退回一份", createdAt = "2026-10-03T06:10:00Z",
                    after = mapOf("kind" to "refund", "original_currency_code" to "CNY", "original_amount_minor" to 2000L,
                        "home_currency_code" to "CNY", "amount_cents" to 2000L, "accounting_date" to "2026-10-03")),
                confirmed.copy(publicId = "history-category", changeKind = "correction", reason = "按原小票核对",
                    changedFields = listOf("category"), before = mapOf("category" to "其他"), after = mapOf("category" to "餐饮"),
                    createdAt = "2026-10-03T05:20:00Z"), confirmed)
        }
    }

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
        val upload = context.getString(R.string.pending_capture_submit, 1)
        waitForText(upload)
        assertTrue(harness.fixture.stored().isEmpty())
        assertTrue(handledLaunches.isEmpty())
        compose.onNodeWithText(upload).performClick()
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

    @Test fun confirmedReceiptCompletesTheEditorAndRefreshesInboxAfterExplicitReturn() {
        harness.fixture.network.current = harness.fixture.network.current.copy(status = "pending", confirmedAt = null)
        installMainGraph()
        compose.runOnIdle { outer.navigate(expenseRoute(42L)) }
        val confirm = context.getString(R.string.expense_edit_confirm_button)
        waitForText(confirm)
        compose.onNodeWithText(confirm).performClick()
        drainAdmittedConfirm()
        waitForText(context.getString(R.string.expense_confirmation_title))
        compose.runOnIdle { assertEquals(EXPENSE_ROUTE, outer.currentBackStackEntry?.destination?.route) }
        compose.onNodeWithText(context.getString(R.string.expense_confirmation_return)).performClick()
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
        InstrumentationRegistry.getArguments().getString("captureImage")?.let {
            harness.fixture.network.originalImageOverride = File(it).readBytes()
        }
        harness.fixture.network.current = harness.fixture.network.current.copy(imagePath = "synthetic/original.png")
        installMainGraph()
        openFact()
        compose.waitUntil(5_000) { harness.fixture.network.originalHealthReads.contains(42L) }
        compose.waitUntil(5_000) { harness.fixture.network.imageReads.size == 1 }
        compose.waitForIdle()
        compose.onNodeWithContentDescription(context.getString(R.string.components_async_image_content_description))
            .performScrollTo().assertIsDisplayed()
        assertEquals(listOf(42L), harness.fixture.network.imageReads)
        assertEquals(null, harness.fixture.network.current.thumbnailPath)
        saveConsumerArtPreview("original-reader", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText(context.getString(R.string.original_verify))
            .performScrollTo().assertIsNotEnabled()
        saveConsumerArtPreview("original-actions", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }

    @Test fun imagelessBillOffersFirstAttachmentWithoutReadingOrChangingAFinancialFact() {
        harness.fixture.network.current = harness.fixture.network.current.copy(imagePath = null, thumbnailPath = null)
        val before = harness.fixture.network.current
        val displayedBytes = InstrumentationRegistry.getArguments().getString("captureImage")?.let { File(it).readBytes() }
            ?: harness.fixture.network.originalImage
        sharedImage.writeBytes(displayedBytes)
        installMainGraph(originalPicker())
        openFact()
        waitForText(context.getString(R.string.original_status_none))
        compose.onNodeWithText(context.getString(R.string.original_title)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.original_attach)).performScrollTo().assertIsEnabled()
        assertTrue(harness.fixture.network.imageReads.isEmpty())
        assertEquals(before, harness.fixture.network.current)
        saveConsumerArtPreview("original-first-attachment", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        harness.fixture.originalStorageAvailable = false
        compose.onNodeWithText(context.getString(R.string.original_attach)).performClick()
        val retry = context.getString(R.string.original_selection_save_retry)
        waitForText(retry)
        InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand("input keyevent 4").close()
        compose.waitForIdle()
        compose.onNodeWithText(retry).performScrollTo().assertIsDisplayed()
        assertTrue(harness.fixture.stored().isEmpty())
        saveConsumerArtPreview("original-selection-retain-failed", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        sharedImage.writeBytes(byteArrayOf(9, 8, 7))
        harness.fixture.originalStorageAvailable = true
        compose.onNodeWithText(retry).performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithText(retry).fetchSemanticsNodes().isEmpty() }
        waitForText(context.getString(R.string.original_selection_submit))
        compose.onNodeWithContentDescription(context.getString(R.string.original_selected_image))
            .performScrollTo().assertIsDisplayed()
        assertTrue(harness.fixture.stored().isEmpty())
        compose.onNodeWithText(context.getString(R.string.original_selection_submit)).performScrollTo().assertIsNotEnabled()
        // Provider contents may change; confirmation must enqueue the bytes actually displayed.
        sharedImage.writeBytes(byteArrayOf(9, 8, 7))
        compose.runOnIdle { assertTrue(outer.popBackStack()); mounted.value = false }
        compose.waitForIdle()
        harness.reopen()
        val binding = requireNotNull(harness.fixture.uploadIntents.currentOriginalBinding())
        assertTrue(runBlocking { harness.screenFactory.repository.loadFactInputs(binding, 42L).getOrThrow().isEmpty() })
        val healthResponse = CompletableDeferred<Unit>()
        harness.fixture.network.beforeOriginalHealthResponse = { healthResponse.await() }
        compose.runOnIdle { mounted.value = true }
        compose.waitForIdle()
        openFact()
        waitForText(context.getString(R.string.original_selection_submit))
        compose.onNodeWithContentDescription(context.getString(R.string.original_selected_image))
            .performScrollTo().assertIsDisplayed()
        assertTrue("Restoring a selection must not read a nonexistent server original while health is pending",
            harness.fixture.network.imageReads.isEmpty())
        healthResponse.complete(Unit)
        waitForText(context.getString(R.string.original_status_none))
        assertTrue("Restoring a selection must not enqueue it", harness.fixture.stored().isEmpty())
        compose.onNodeWithText(context.getString(R.string.original_selection_submit)).performScrollTo().assertIsNotEnabled()
        val review = context.getString(R.string.original_selection_review)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(review) and isEnabled()).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(review).performScrollTo().performClick()
        compose.waitForIdle()
        InstrumentationRegistry.getInstrumentation().uiAutomation.waitForIdle(300, 3_000)
        saveConsumerArtPreview("original-selection-confirm", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText(context.getString(R.string.original_selection_submit)).performScrollTo().assertIsEnabled().performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().size == 1 }
        val row = harness.fixture.stored().single()
        val payload = requireNotNull(originalPayloadAdapter.fromJson(requireNotNull(row["payload"])))
        assertEquals("attach_original", payload.operation)
        assertEquals(42L, payload.expenseId)
        assertEquals(before.rowVersion, payload.expectedRowVersion)
        runBlocking { assertArrayEquals(displayedBytes, UploadIntentFileStore(context).read(requireNotNull(payload.file))) }
        assertEquals(before, harness.fixture.network.current)
        val acceptedAt = "2026-09-20T01:00:00Z"
        harness.fixture.network.current = before.copy(imagePath = "owner/retained-original.png",
            imageHash = requireNotNull(payload.file).sha256, rowVersion = before.rowVersion + 1)
        harness.fixture.network.originalImageOverride = displayedBytes
        val receipt = OriginalCommandReceiptDto(operation = payload.operation, expenseId = payload.expenseId,
            publicId = payload.publicId, rowVersion = before.rowVersion + 1, acceptedAt = acceptedAt,
            sha256 = requireNotNull(payload.file).sha256)
        runBlocking { harness.fixture.outbox.markDone(requireNotNull(row["id"]).toLong(),
            receiptJson = originalReceiptAdapter.toJson(receipt)) }
        waitForText(context.getString(R.string.original_status_verified))
        compose.onAllNodesWithText(context.getString(R.string.original_queued)).assertCountEquals(0)
        val accepted = context.getString(R.string.original_receipt, context.getString(R.string.original_attach), displayTime(acceptedAt))
        compose.onNodeWithText(accepted).performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("original-first-accepted", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        assertEquals(before, harness.fixture.network.current.copy(imagePath = before.imagePath,
            imageHash = before.imageHash, rowVersion = before.rowVersion))
        assertEquals(1, harness.fixture.stored().size)
    }

    @Test fun missingOriginalKeepsTheBillAndReplenishEntry() {
        harness.fixture.network.originalMissing = true
        installMainGraph()
        openFact()
        waitForText(context.getString(R.string.original_replenish))
        compose.onNodeWithText(context.getString(R.string.original_replenish)).performScrollTo().assertIsEnabled()
        assertTrue(harness.fixture.network.imageReads.isEmpty())
        assertEquals("confirmed", harness.fixture.network.current.status)
        saveConsumerArtPreview("original-missing", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
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
            .performClick()
        val waiting = context.getString(R.string.bill_split_submission_waiting)
        waitForText(waiting)
        compose.waitForIdle()
        // The user remains where they submitted; no scroll is used to find the receipt.
        compose.onNodeWithText(waiting).assertIsDisplayed()
        compose.onNodeWithText(start).assertIsNotEnabled()
        assertEquals("create_bill_split_invitation", harness.fixture.stored().single()["type"])
        assertEquals("pending", harness.fixture.stored().single()["status"])
    }

    @Test fun originalReceiptAndExplicitAttachmentBaselineReviewKeepTypedFormValues() {
        val network = harness.fixture.network
        network.current = network.current.copy(status = "pending", confirmedAt = null)
        val before = network.current
        val bytes = InstrumentationRegistry.getArguments().getString("captureImage")?.let { File(it).readBytes() }
            ?: network.originalImage
        sharedImage.writeBytes(bytes)
        installMainGraph(originalPicker())
        waitForText(requireNotNull(before.merchant))
        compose.runOnIdle { outer.navigate(expenseRoute(42L)) }
        val confirm = context.getString(R.string.expense_edit_confirm_button)
        waitForText(confirm)
        compose.onNodeWithTag("expense-edit-more-row").performScrollTo().performClick()
        val tags = "原件任务期间的输入"
        compose.onNodeWithTag(TAG_TAGS_FIELD).performScrollTo().performTextReplacement(tags)
        keyboard.dismissAndWait(compose)
        waitForText(context.getString(R.string.original_status_none))
        compose.onNodeWithText(context.getString(R.string.original_title)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.original_attach)).performScrollTo().performClick()
        val review = context.getString(R.string.original_selection_review)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(review) and isEnabled()).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(review).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.original_selection_submit)).performScrollTo().performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().size == 1 }
        val original = harness.fixture.stored().single()
        val payload = requireNotNull(originalPayloadAdapter.fromJson(requireNotNull(original["payload"])))
        assertEquals(before, network.current)
        runBlocking { assertArrayEquals(bytes, UploadIntentFileStore(context).read(requireNotNull(payload.file))) }
        network.current = before.copy(imagePath = "owner/pending-original.png",
            imageHash = requireNotNull(payload.file).sha256, rowVersion = before.rowVersion + 1,
            updatedAt = "2026-09-20T01:00:00Z")
        network.originalImageOverride = bytes
        val receipt = OriginalCommandReceiptDto(payload.operation, payload.expenseId, payload.publicId,
            network.current.rowVersion, "2026-09-20T01:00:00Z", sha256 = requireNotNull(payload.file).sha256)
        runBlocking { harness.fixture.outbox.markDone(requireNotNull(original["id"]).toLong(),
            receiptJson = originalReceiptAdapter.toJson(receipt)) }
        val baseline = context.getString(R.string.original_edit_baseline)
        waitForText(baseline)
        compose.onNodeWithText(confirm).assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.expense_edit_primary_save_button)).assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.expense_edit_ignore_button)).assertIsNotEnabled()
        compose.onNodeWithTag(TAG_TAGS_FIELD).performScrollTo().assertTextContains(tags)
        assertTrue(network.editCalls.isEmpty())
        compose.onNodeWithTag(TAG_TAGS_FIELD).performClick()
        keyboard.assertActionAboveKeyboard(compose, confirm, "pending-original-keyboard")
        compose.onNodeWithText(confirm).assertIsNotEnabled()
        keyboard.dismissAndWait(compose)
        compose.onNodeWithText(baseline).performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("pending-original-baseline", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        network.failReads = true
        compose.onNodeWithText(context.getString(R.string.original_edit_review)).performScrollTo().performClick()
        val failure = "暂时连不上小票夹，请稍后再试。"
        waitForText(failure)
        compose.onNodeWithText(confirm).assertIsNotEnabled()
        compose.onNodeWithTag(TAG_TAGS_FIELD).performScrollTo().assertTextContains(tags)
        assertTrue(network.editCalls.isEmpty())
        saveConsumerArtPreview("pending-original-review-failure", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        network.failReads = false
        compose.onNodeWithText(context.getString(R.string.original_edit_review)).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithText(baseline).fetchSemanticsNodes().isEmpty() }
        compose.onAllNodesWithText(failure).assertCountEquals(0)
        compose.onNodeWithTag(TAG_TAGS_FIELD).performScrollTo().assertTextContains(tags)
        compose.onNodeWithText(confirm).assertIsEnabled().performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().any { it["type"] == PendingMutationType.PatchExpense.wireValue } }
        val patchRow = harness.fixture.stored().single { it["type"] == PendingMutationType.PatchExpense.wireValue }
        val patch = org.json.JSONObject(requireNotNull(patchRow["payload"]))
        assertEquals(tags, patch.getString("tags"))
        assertEquals((before.rowVersion + 1).toString(), patchRow["expectedRowVersion"])
        drainAdmittedConfirm()
        waitForText(context.getString(R.string.expense_confirmation_title))
        assertEquals(listOf("save", "confirm"), network.editCalls)
        assertEquals("confirmed", network.current.status)
        assertEquals(before.amountCents, network.current.amountCents)
        saveConsumerArtPreview("pending-original-confirmed", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
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
        drainAdmittedConfirm()
        waitForText(context.getString(R.string.expense_confirmation_title))
        compose.onNodeWithText(context.getString(R.string.expense_confirmation_return)).performClick()
        compose.waitUntil(5_000) { harness.shell.expenseEditCompletionRevision == 1 && network.failedPendingReads > 0 }
        compose.waitForIdle()
        compose.onAllNodesWithText(requireNotNull(network.current.merchant)).assertCountEquals(0)
        assertEquals("confirmed", network.current.status)
        assertEquals(1, runBlocking { harness.fixture.expenseDao.getConfirmed("correction-ledger") }.size)
    }

    private fun openFact() {
        compose.runOnIdle { outer.navigate(expenseRoute(42L)) }
        waitForText(context.getString(R.string.expense_fact_original_spend))
        compose.waitForIdle()
    }

    @Test fun externalCaptureKeepsTheUnsubmittedEditorOnTheReturnStack() {
        val network = harness.fixture.network
        network.current = network.current.copy(status = "pending", confirmedAt = null)
        installMainGraph()
        compose.runOnIdle { outer.openExpense(42L) }
        waitForText(context.getString(R.string.expense_edit_confirm_button))
        compose.onNodeWithTag("expense-edit-merchant-row").performScrollTo().performClick()
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
        val settingsGroup = context.getString(R.string.settings_root_sync_directory_title)
        waitForText(settingsGroup)
        compose.onNodeWithText(settingsGroup).performScrollTo().performClick()
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
        val settingsGroup = context.getString(R.string.settings_root_sync_directory_title)
        waitForText(settingsGroup)
        compose.onNodeWithText(settingsGroup).performScrollTo().performClick()
        val entry = context.getString(
            if (BuildConfig.SHOW_ADVANCED_TOOLS) R.string.settings_root_connection_title_advanced
            else R.string.settings_root_connection_title_basic,
        )
        waitForText(entry)
        compose.onNodeWithText(entry).performScrollTo().performClick()
        val checkConnection = context.getString(R.string.settings_server_check_again)
        waitForText(checkConnection)
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasText(checkConnection) and isEnabled()).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(checkConnection).assertIsDisplayed().performClick()

        val nextStep = "请将手机应用与服务端更新到配套版本，再重新检测。"
        waitForText(nextStep)
        compose.onNodeWithText(nextStep).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.settings_server_pending_title)).performScrollTo().performClick()
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
        val settingsGroup = context.getString(R.string.settings_root_sync_directory_title)
        waitForText(settingsGroup)
        compose.onNodeWithText(settingsGroup).performScrollTo().performClick()
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

    @Test fun recurringPendingWorkOpensExistingRecoveryAndKeepsTheOriginalRequest() {
        val binding = requireNotNull(harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding())
        runBlocking {
            harness.fixture.graph.recurringRepository.createAllowingOffline(binding,
                com.ticketbox.data.repository.RecurringItemDraft("原订阅任务", 2400, "2026-11-09", "JPY")).getOrThrow()
            harness.fixture.outbox.markFailed(requireNotNull(harness.fixture.stored().single()["id"]).toLong(),
                "max_attempts_exceeded(10/10): offline")
        }
        val original = harness.fixture.stored().single()
        installMainGraph()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.Recurring) }
        val manage = context.getString(R.string.recurring_pending_manage)
        compose.waitUntil(5_000) {
            runCatching { compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("原订阅任务")) }.isSuccess
        }
        saveConsumerArtPreview("recurring-pending-entry", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText(manage).performScrollTo().performClick()
        val retry = context.getString(R.string.sync_status_failed_button_retry)
        try {
            compose.waitUntil(5_000) {
                runCatching { compose.onNodeWithText(retry).performScrollTo().assertIsDisplayed() }.isSuccess
            }
        } finally {
            saveConsumerArtPreview("recurring-pending-recovery", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        }
        compose.onNodeWithText("原订阅任务").performScrollTo().assertIsDisplayed()
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.ObligationSync), harness.shell.activeDestination)
        assertEquals(original, harness.fixture.stored().single())
        compose.onNodeWithText(retry).performScrollTo().performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().single()["status"] == "pending" }
        val retried = harness.fixture.stored().single()
        for (field in listOf("id", "payload", "idempotency_key")) assertEquals(original[field], retried[field])
        compose.onNodeWithText(context.getString(R.string.sync_status_back)).performScrollTo().performClick()
        compose.waitForIdle()
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.Recurring), harness.shell.activeDestination)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("原订阅任务"))
        compose.onNodeWithText("原订阅任务").assertIsDisplayed()
        assertTrue(harness.fixture.network.calls.isEmpty())
    }

    @Test fun recurringPaymentReturnsToItsOriginalPeriodFiltersAndList() {
        installMainGraph()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.Recurring) }
        val openOccurrence = context.getString(R.string.occurrence_open)
        compose.waitUntil(5_000) {
            runCatching { compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(openOccurrence)) }.isSuccess
        }
        compose.onNodeWithTag("recurring-item-navigation-recurring").assertIsDisplayed()
        compose.onNodeWithText(openOccurrence).performClick()
        val openPayment = context.getString(R.string.occurrence_open_payment)
        waitForText(openPayment)
        compose.onNodeWithTag("occurrence-payment-filter-toggle").performScrollTo().performClick()
        val monthField = hasSetTextAction() and hasText(context.getString(R.string.occurrence_payment_month))
        val queryField = hasSetTextAction() and hasText(context.getString(R.string.occurrence_search))
        compose.onNode(monthField).performTextReplacement("2026-08")
        compose.onNode(queryField).performTextReplacement("家庭午餐")
        compose.onNodeWithTag("occurrence-payment-filter-toggle").performScrollTo().performClick()
        compose.onNodeWithText(openPayment).assertIsDisplayed().performClick()
        assertRealFactAndReturn()
        saveConsumerArtPreview("recurring-return-context", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText(context.getString(R.string.occurrence_subtitle)).assertIsDisplayed()
        compose.onNodeWithTag("occurrence-payment-filter-toggle").performScrollTo()
            .assertTextContains("2026-08", substring = true).assertTextContains("家庭午餐", substring = true).performClick()
        compose.onNode(monthField).assertTextContains("2026-08")
        compose.onNode(queryField).assertTextContains("家庭午餐")
        androidx.test.espresso.Espresso.pressBack()
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(openOccurrence))
        compose.onNodeWithTag("recurring-item-navigation-recurring").assertIsDisplayed()
        compose.onNodeWithText(openOccurrence).assertIsDisplayed()
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.Recurring), harness.shell.activeDestination)
        assertEquals("navigation-recurring", harness.fixture.network.occurrenceReads.single().first)
        assertEquals("current", harness.fixture.network.occurrenceReads.single().second)
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
        waitForText(context.getString(R.string.expense_fact_original_spend))
        compose.onNodeWithTag("expense-fact").assertIsDisplayed()
        waitForText("更正这笔账单")
        compose.onNodeWithText("更正这笔账单").performScrollTo().assertIsDisplayed()
        compose.runOnIdle {
            assertEquals(EXPENSE_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(42L, outer.currentBackStackEntry?.arguments?.getLong(EXPENSE_ID_ARG))
            assertTrue(harness.fixture.network.expenseReads.contains(42L))
            assertTrue(harness.fixture.network.calls.isEmpty())
        }
        compose.onNodeWithContentDescription(context.getString(R.string.expense_edit_primary_back_button))
            .performScrollTo().performClick()
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route) }
    }

    private fun originalPicker(): ActivityResultRegistryOwner {
        val registry = object : ActivityResultRegistry() {
            override fun <I, O> onLaunch(requestCode: Int, contract: ActivityResultContract<I, O>, input: I,
                options: ActivityOptionsCompat?) {
                dispatchResult(requestCode, Activity.RESULT_OK, Intent().setData(Uri.fromFile(sharedImage)))
            }
        }
        return object : ActivityResultRegistryOwner { override val activityResultRegistry = registry }
    }

    private fun drainAdmittedConfirm() {
        compose.waitUntil(5_000) {
            harness.fixture.stored().any { it["type"] == PendingMutationType.ConfirmExpense.wireValue }
        }
        runBlocking { harness.fixture.drainExpenseLifecycle() }
    }

    private fun waitForText(text: String) {
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun installMainGraph(picker: ActivityResultRegistryOwner? = null) {
        compose.setContent {
            if (mounted.value) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models,
                    LocalActivityResultRegistryOwner provides (picker ?: requireNotNull(LocalActivityResultRegistryOwner.current))) {
                    TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
                        AppSkin.Midnight else AppSkin.Paper) {
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
