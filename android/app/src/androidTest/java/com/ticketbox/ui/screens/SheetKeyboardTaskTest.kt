package com.ticketbox.ui.screens

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.ui.screens.expense.ItemsEditorSheet
import com.ticketbox.ui.screens.expense.ItemsEditorSheetActions
import com.ticketbox.ui.screens.expense.ItemsEditorSheetState
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheet
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheetActions
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheetState
import com.ticketbox.ui.screens.pending.sheets.QuickMerchantSheetContent
import com.ticketbox.ui.screens.pending.sheets.ReviewSheetChrome
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.EditableItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Actual short, nested-list and multi-command consumers of the shared sheet. */
@OptIn(ExperimentalMaterial3Api::class)
class SheetKeyboardTaskTest {
    @get:Rule val compose = createComposeRule()
    @get:Rule val keyboard = RealKeyboard()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun merchantRetryKeepsItsInputAndOriginalSaveCommandAboveTheKeyboard() {
        val sent = mutableListOf<String>()
        var saving by mutableStateOf(false)
        val failure = "刚才没有保存，请保留原输入再试。"
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Midnight) {
                ModalBottomSheet(onDismissRequest = {},
                    sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
                    QuickMerchantSheetContent(
                        expense = pendingExpense(),
                        chrome = ReviewSheetChrome(saving, 31, failure, onSkip = {}),
                        onSave = { sent += it; saving = true },
                        onDismiss = {},
                    )
                }
            }
        }
        compose.onNode(hasSetTextAction()).performTouchInput { click() }
            .performTextReplacement("  小满便利店  ")
        val save = text(R.string.pending_quick_merchant_save_button)
        keyboard.assertActionAboveKeyboard(compose, save, "quick-merchant-keyboard-retry")
        compose.onNodeWithText(failure).assertIsDisplayed()
        compose.onNodeWithText(save).performTouchInput { click() }
        compose.runOnIdle { assertEquals(listOf("小满便利店"), sent) }
        compose.onNodeWithText("  小满便利店  ").assertIsNotEnabled()
        compose.onNodeWithText(text(R.string.common_cancel)).assertIsNotEnabled()
    }

    @Test fun nestedItemEditingKeepsSaveVisibleAndPreservesUntouchedRows() {
        val original = List(8) { index -> EditableItem(name = "项目${index + 1}", amountText = "1.00",
            rawText = "原始明细${index + 1}", baselineAmountCents = 100L, sourcePublicId = "item-$index") }
        var drafts by mutableStateOf(original)
        val saved = mutableListOf<List<EditableItem>>()
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                ItemsEditorSheet(
                    state = ItemsEditorSheetState(drafts, 800L, saving = false),
                    actions = ItemsEditorSheetActions(
                        onUpdate = { index, name, amount, kind -> drafts = drafts.mapIndexed { position, item ->
                            if (position == index) item.copy(name = name ?: item.name,
                                amountText = amount ?: item.amountText, kind = kind ?: item.kind) else item
                        } },
                        onAddRow = { error("The save action must not add an item") },
                        onRemoveRow = { error("The save action must not remove an item") },
                        onSave = { saved += drafts.toList() },
                        onDismiss = {},
                    ),
                )
            }
        }
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTouchInput { click() }
            .performTextReplacement("修正品名")
        val save = text(R.string.expense_edit_items_save_button)
        keyboard.assertActionAboveKeyboard(compose, save, "items-keyboard-nested-list")
        compose.onNodeWithText(save).performTouchInput { click() }
        compose.runOnIdle { assertEquals(listOf(original.toMutableList().apply {
            this[0] = this[0].copy(name = "修正品名")
        }.toList()), saved) }
    }

    @Test fun bulkCategoryAndTagCommandsKeepTheirReasonAndReplacementConfirmation() {
        val categories = mutableListOf<Pair<String, String>>()
        val tags = mutableListOf<Pair<String, String>>()
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                ModalBottomSheet(onDismissRequest = {}) {
                    LedgerBulkEditSheet(
                        state = LedgerBulkEditSheetState(31, true, listOf("餐饮", "交通"), false),
                        actions = LedgerBulkEditSheetActions(
                            onApplyCategory = { category, reason -> categories += category to reason },
                            onApplyTags = { value, reason -> tags += value to reason },
                        ),
                    )
                }
            }
        }
        field(R.string.ledger_bulk_reason_label, "补记通勤用途")
        field(R.string.expense_edit_category_field_label, "交通")
        val categoryAction = context.getString(R.string.ledger_bulk_apply_category, 31)
        keyboard.assertActionAboveKeyboard(compose, categoryAction, "bulk-category-keyboard")
        compose.onNodeWithText(categoryAction).performTouchInput { click() }
        compose.runOnIdle {
            assertEquals(listOf("交通" to "补记通勤用途"), categories)
            assertTrue(tags.isEmpty())
        }
        compose.onNode(isToggleable()).performScrollTo().performTouchInput { click() }
        field(R.string.ledger_bulk_tags_label, "通勤")
        val tagsAction = context.getString(R.string.ledger_bulk_apply_tags, 31)
        keyboard.assertActionAboveKeyboard(compose, tagsAction, "bulk-tags-keyboard")
        compose.onNodeWithText(tagsAction).performTouchInput { click() }
        compose.onNodeWithText(text(R.string.ledger_bulk_tags_confirm_message)).assertIsDisplayed()
        compose.runOnIdle { assertTrue(tags.isEmpty()) }
        compose.onNodeWithText(text(R.string.ledger_bulk_tags_confirm_replace)).performTouchInput { click() }
        compose.runOnIdle {
            assertEquals(listOf("通勤" to "补记通勤用途"), tags)
            assertEquals(1, categories.size)
        }
    }

    private fun field(label: Int, value: String) {
        compose.onNode(hasSetTextAction() and hasText(text(label)))
            .performScrollTo().performTouchInput { click() }.performTextInput(value)
    }

    private fun text(resource: Int): String = context.getString(resource)

    private fun pendingExpense() = Expense(
        id = 1L, publicId = "keyboard-merchant", amountCents = 1280L, merchant = null,
        category = "餐饮", note = null, source = ExpenseSourceValues.ANDROID_SCREENSHOT, imagePath = null,
        thumbnailPath = null, imageHash = null, rawText = null, confidence = null,
        duplicateStatus = "", duplicateOfId = null, duplicateReason = null, tags = null,
        valueScore = null, regretScore = null, status = "pending", expenseTime = null,
        createdAt = "2026-10-01T01:00:00Z", updatedAt = "2026-10-01T01:00:00Z",
        rowVersion = 1L, confirmedAt = null, rejectedAt = null,
    )
}
