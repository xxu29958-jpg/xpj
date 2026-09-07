package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.PendingIncomePlanEdit
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/**
 * Pins the irreversible-discard confirm step on 离线同步: 「放弃我的改动」
 * (conflict) and 「放弃」/「移除」 (failed) must NOT fire the VM callback
 * directly — first an AlertDialog, cancel keeps the row, and only the
 * explicit confirm word (确定放弃 / 确定移除) fires the drop.
 */
class SyncStatusScreenConfirmTest {
    private var openedUploads = 0
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun conflictDropAsksForConfirmationBeforeFiring() {
        var dropped: OutboxRow? = null
        val row = outboxRow(status = PendingMutationStatus.Conflict)
        setScreenContent(
            conflicts = listOf(row),
            actions = SyncStatusActions(
        onOpenExpense = {},
                onKeepMine = {},
                onDropMine = { dropped = it },
                onRetry = {},
                onDropFailed = {},
                onClearQuarantined = {},
            ),
        )

        composeRule.onNodeWithText("放弃我的改动").performScrollTo().performClick()
        composeRule.onNodeWithText("放弃我的改动？").assertIsDisplayed()
        composeRule.runOnIdle { assertNull(dropped) }

        composeRule.onNodeWithText("取消").performClick()
        composeRule.runOnIdle { assertNull(dropped) }

        composeRule.onNodeWithText("放弃我的改动").performScrollTo().performClick()
        composeRule.onNodeWithText("确定放弃").performClick()
        composeRule.runOnIdle { assertEquals(row, dropped) }
    }

    @Test
    fun failedDropAsksForConfirmationBeforeFiring() {
        var dropped: OutboxRow? = null
        val row = outboxRow(status = PendingMutationStatus.Failed)
        setScreenContent(
            failed = listOf(row),
            actions = SyncStatusActions(
        onOpenExpense = {},
                onKeepMine = {},
                onDropMine = {},
                onRetry = {},
                onDropFailed = { dropped = it },
                onClearQuarantined = {},
            ),
        )

        composeRule.onNodeWithText("放弃").performScrollTo().performClick()
        composeRule.onNodeWithText("放弃这条改动？").assertIsDisplayed()
        composeRule.runOnIdle { assertNull(dropped) }

        composeRule.onNodeWithText("取消").performClick()
        composeRule.runOnIdle { assertNull(dropped) }

        composeRule.onNodeWithText("放弃").performScrollTo().performClick()
        composeRule.onNodeWithText("确定放弃").performClick()
        composeRule.runOnIdle { assertEquals(row, dropped) }
    }

    @Test
    fun expiredFailedRowUsesRemoveWording() {
        var dropped: OutboxRow? = null
        // The reaper's real terminal marker (ADR-0042 §4.10) — drives both the
        // card's 移除-only rendering and the dialog's remove wording.
        val row = outboxRow(status = PendingMutationStatus.Failed, lastError = "outbox_row_expired")
        setScreenContent(
            failed = listOf(row),
            actions = SyncStatusActions(
        onOpenExpense = {},
                onKeepMine = {},
                onDropMine = {},
                onRetry = {},
                onDropFailed = { dropped = it },
                onClearQuarantined = {},
            ),
        )

        composeRule.onNodeWithText("移除").performScrollTo().performClick()
        composeRule.onNodeWithText("移除这条记录？").assertIsDisplayed()
        composeRule.runOnIdle { assertNull(dropped) }

        composeRule.onNodeWithText("确定移除").performClick()
        composeRule.runOnIdle { assertEquals(row, dropped) }
    }

    @Test
    fun unsupportedIncomeKeepsItsExplanationAndDropWithoutRetry() {
        val row = outboxRow(status = PendingMutationStatus.Failed).copy(
            type = PendingMutationType.UpdateIncomePlan, targetId = "income_plan:old",
        )
        setScreenContent(failed = listOf(row), incomeEdits = mapOf(row.id to PendingIncomePlanEdit(row, null)),
            actions = SyncStatusActions(onOpenExpense = {}, onKeepMine = {}, onDropMine = {}, onRetry = { error("Unsupported retry") },
                onDropFailed = {}, onClearQuarantined = {}))
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        composeRule.onNodeWithText(context.getString(com.ticketbox.R.string.income_plan_edit_unsupported)).assertIsDisplayed()
        composeRule.onNodeWithText("重试").assertDoesNotExist()
        composeRule.onNodeWithText("放弃").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun quarantinedRowsRequireExplicitConfirmationBeforeClearing() {
        var clearCount = 0
        setScreenContent(
            quarantinedCount = 2,
            actions = SyncStatusActions(
        onOpenExpense = {},
                onKeepMine = {},
                onDropMine = {},
                onRetry = {},
                onDropFailed = {},
                onClearQuarantined = { clearCount += 1 },
            ),
        )

        composeRule.onNodeWithText("移除隔离数据").performScrollTo().performClick()
        composeRule.onNodeWithText("移除全部隔离操作？").assertIsDisplayed()
        composeRule.runOnIdle { assertEquals(0, clearCount) }

        composeRule.onNodeWithText("取消").performClick()
        composeRule.runOnIdle { assertEquals(0, clearCount) }

        composeRule.onNodeWithText("移除隔离数据").performScrollTo().performClick()
        composeRule.onNodeWithText("确认移除").performClick()
        composeRule.runOnIdle { assertEquals(1, clearCount) }
    }

    @Test
    fun protocolRefusalExplainsTheUpgradeAndKeepsOriginalRetry() {
        var retried: OutboxRow? = null
        val original = outboxRow(PendingMutationStatus.Failed, lastError = "runtime_version_mismatch")
        setScreenContent(failed = listOf(original), actions = SyncStatusActions(
        onOpenExpense = {},
            onKeepMine = {}, onDropMine = {}, onRetry = { retried = it }, onDropFailed = {}, onClearQuarantined = {},
        ))
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        composeRule.onNodeWithText(context.getString(com.ticketbox.R.string.sync_status_error_protocol_mismatch))
            .performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("重试").performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(original, retried) }
    }

    @Test
    fun failedUploadOpensItsOriginalInboxGroupInsteadOfUsingGenericRetry() {
        val original = outboxRow(PendingMutationStatus.Failed, "upload_payload_unsupported")
            .copy(type = PendingMutationType.UploadScreenshot, targetId = "upload_batch:original")
        setScreenContent(failed = listOf(original), actions = SyncStatusActions(
            onOpenExpense = {}, onKeepMine = {}, onDropMine = {},
            onRetry = { error("An upload must use the original group's recovery") },
            onDropFailed = {}, onClearQuarantined = {},
        ))
        composeRule.onNodeWithText("重试").assertDoesNotExist()
        composeRule.onNodeWithText("查看待上传截图").performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(1, openedUploads) }
    }

    private fun setScreenContent(
        conflicts: List<OutboxRow> = emptyList(),
        failed: List<OutboxRow> = emptyList(),
        quarantinedCount: Int = 0,
        incomeEdits: Map<Long, PendingIncomePlanEdit> = emptyMap(),
        actions: SyncStatusActions,
    ) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                SyncStatusScreenContent(
                    state = OutboxStatusUiState(
                        incomeEdits = incomeEdits,
                        status = OutboxStatus(
                            queueDepth = 0,
                            conflicts = conflicts,
                            failed = failed,
                            quarantinedCount = quarantinedCount,
                        ),
                    ),
                    actions = actions,
                    onBack = {},
                    onOpenInbox = { openedUploads += 1 },
                )
            }
        }
    }

    private fun outboxRow(
        status: PendingMutationStatus,
        lastError: String? = null,
    ): OutboxRow = OutboxRow(
        id = 11L,
        serverUrl = "https://qa.invalid",
        ledgerId = "ledger-1",
        type = PendingMutationType.PatchExpense,
        targetId = "expense:7",
        payloadJson = "{}",
        expectedRowVersion = 1L,
        status = status,
        retryCount = 0,
        lastError = lastError,
        createdAt = "2026-06-01T00:00:00Z",
        attemptedAt = null,
        completedAt = null,
    )
}
