package com.ticketbox.ui.screens

import androidx.compose.foundation.text.BasicText
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.screens.recurring.RecurringEditField
import com.ticketbox.ui.screens.recurring.RecurringEditorTarget
import com.ticketbox.ui.screens.recurring.RecurringRebaseUi
import com.ticketbox.ui.screens.recurring.RecurringSubmitUi
import com.ticketbox.ui.screens.recurring.rememberRecurringEditorHostState
import org.junit.Rule
import org.junit.Test

class RecurringEditorRestorationTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun targetDraftOccBaselineAndAttemptRestoreAsOneEditorSession() {
        val restorationTester = StateRestorationTester(composeRule)
        lateinit var openAndEdit: () -> Unit
        restorationTester.setContent {
            val host = rememberRecurringEditorHostState(
                editorEpoch = 7L,
                runtimeId = "runtime-a",
            )
            openAndEdit = {
                host.openEdit(item(), CurrencyCode.CNY)
                checkNotNull(host.editor).session.apply {
                    merchant = "我的房租"
                    amountText = "3100.00"
                    dateIso = "2026-09-15"
                    dateTouched = true
                    showDatePicker = true
                    submitUi = RecurringSubmitUi(
                        attemptId = 42L,
                        awaiting = true,
                        error = "网络错误",
                    )
                    rebaseUi = RecurringRebaseUi(42L, setOf(RecurringEditField.Amount))
                }
            }
            val editor = host.editor
            val target = editor?.target as? RecurringEditorTarget.Edit
            val session = editor?.session
            BasicText(
                text = listOf(
                    target?.publicId,
                    session?.editing?.rowVersion,
                    session?.merchant,
                    session?.amountText,
                    session?.dateIso,
                    session?.dateTouched,
                    session?.showDatePicker,
                    session?.submitUi?.attemptId,
                    session?.submitUi?.awaiting,
                    session?.submitUi?.error,
                    session?.rebaseUi?.attemptId,
                    session?.rebaseUi?.overlappingFields?.singleOrNull()?.name,
                ).joinToString("|"),
                modifier = Modifier.testTag(EDITOR_STATE_TAG),
            )
        }

        composeRule.runOnIdle(openAndEdit)
        val expected = "rec-restore|7|我的房租|3100.00|2026-09-15|true|true|42|true|网络错误|42|Amount"
        composeRule.onNodeWithTag(EDITOR_STATE_TAG).assertTextEquals(expected)

        restorationTester.emulateSavedInstanceStateRestore()

        composeRule.onNodeWithTag(EDITOR_STATE_TAG).assertTextEquals(expected)
    }

    @Test
    fun runtimeMismatchDropsRestoredEditorSession() {
        val restorationTester = StateRestorationTester(composeRule)
        var runtimeId = "runtime-a"
        lateinit var openAndEdit: () -> Unit
        restorationTester.setContent {
            val host = rememberRecurringEditorHostState(
                editorEpoch = 7L,
                runtimeId = runtimeId,
            )
            openAndEdit = {
                host.openEdit(item(), CurrencyCode.CNY)
                checkNotNull(host.editor).session.apply {
                    merchant = "我的房租"
                    submitUi = RecurringSubmitUi(attemptId = 42L, awaiting = true)
                }
            }
            BasicText(
                text = host.editor?.session?.merchant ?: "no-editor",
                modifier = Modifier.testTag(EDITOR_STATE_TAG),
            )
        }

        composeRule.runOnIdle(openAndEdit)
        composeRule.onNodeWithTag(EDITOR_STATE_TAG).assertTextEquals("我的房租")

        // 新进程拿到新 runtime id：带在途 attempt 的旧会话整体丢弃。
        runtimeId = "runtime-b"
        restorationTester.emulateSavedInstanceStateRestore()

        composeRule.onNodeWithTag(EDITOR_STATE_TAG).assertTextEquals("no-editor")
    }

    @Test
    fun editorEpochMismatchDropsRestoredEditorSession() {
        val restorationTester = StateRestorationTester(composeRule)
        var editorEpoch = 7L
        lateinit var openAndEdit: () -> Unit
        restorationTester.setContent {
            val host = rememberRecurringEditorHostState(
                editorEpoch = editorEpoch,
                runtimeId = "runtime-a",
            )
            openAndEdit = {
                host.openEdit(item(), CurrencyCode.CNY)
                checkNotNull(host.editor).session.merchant = "账本 A 的房租"
            }
            BasicText(
                text = host.editor?.session?.merchant ?: "no-editor",
                modifier = Modifier.testTag(EDITOR_STATE_TAG),
            )
        }

        composeRule.runOnIdle(openAndEdit)
        composeRule.onNodeWithTag(EDITOR_STATE_TAG).assertTextEquals("账本 A 的房租")

        // 同一 VM runtime 切换逻辑账本后，旧账本的 editor 不能在恢复时复活。
        editorEpoch = 8L
        restorationTester.emulateSavedInstanceStateRestore()

        composeRule.onNodeWithTag(EDITOR_STATE_TAG).assertTextEquals("no-editor")
    }

    private fun item(): RecurringItem = RecurringItem(
        publicId = "rec-restore",
        ledgerId = "ledger-plan",
        merchant = "房租",
        merchantKey = "房租",
        frequency = "monthly",
        baselineAmountCents = 3000_00,
        lastAmountCents = 3000_00,
        occurrenceCount = 3,
        lastSeenAt = "2026-08-01T00:00:00Z",
        nextExpectedDate = "2026-09-01",
        status = "active",
        confidence = "high",
        source = "manual",
        anomalyStatus = "normal",
        currentMonthAmountCents = 3000_00,
        historicalAverageAmountCents = 3000_00,
        amountDeltaPercent = 0,
        createdAt = "2026-06-01T00:00:00Z",
        updatedAt = "2026-08-01T00:00:00Z",
        rowVersion = 7L,
        pausedAt = null,
        archivedAt = null,
    )

    private companion object {
        const val EDITOR_STATE_TAG = "recurring-editor-state"
    }
}
