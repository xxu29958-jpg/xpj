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
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
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
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.ui.screens.expense.ItemsEditorSheet
import com.ticketbox.ui.screens.expense.ItemsEditorSheetActions
import com.ticketbox.ui.screens.expense.ItemsEditorSheetState
import com.ticketbox.ui.screens.pending.PendingReviewSheetHost
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostState
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostActions
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.EditableItem
import com.ticketbox.viewmodel.LedgerUiState
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
        var originalInput by mutableStateOf(com.ticketbox.viewmodel.PendingReviewValues())
        val failure = "刚才没有保存，请保留原输入再试。"
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Midnight) {
                PendingReviewSheetHost(
                    state = PendingReviewSheetHostState(com.ticketbox.viewmodel.PendingSheet.QuickMerchant(pendingExpense()),
                        emptyList(), if (saving) setOf(1L) else emptySet(), 0, 0, 0, false, 0, 0, 31, failure,
                        inputValues = originalInput, inputSaved = originalInput.value != null),
                    actions = PendingReviewSheetHostActions(onSaveQuickCategory = { _, _ -> },
                        onSaveQuickMerchant = { _, value -> sent += value; saving = true },
                        onSaveAmountDraft = { _, _ -> }, onSaveAmountAndConfirm = { _, _ -> },
                        onSkipReviewField = {}, onKeepBoth = {}, onIgnoreCurrent = {}, onConfirmReady = {},
                        onDismiss = {}, onReviewInputChange = { originalInput = it }),
                )
            }
        }
        compose.onNode(hasSetTextAction()).performTouchInput { click() }
            .performTextReplacement("  小满便利店  ")
        val save = text(R.string.pending_quick_merchant_save_button)
        keyboard.assertActionAboveKeyboard(compose, save, "quick-merchant-keyboard-retry")
        compose.onNode(hasSetTextAction()).assertIsDisplayed()
        compose.onNodeWithText(failure).assertIsDisplayed()
        compose.onNodeWithText(save).performTouchInput { click() }
        compose.runOnIdle { assertEquals(listOf("小满便利店"), sent) }
        compose.onNodeWithText("  小满便利店  ").assertIsNotEnabled()
        compose.onNodeWithText(text(R.string.expense_fact_input_close)).assertIsNotEnabled()
    }

    @Test fun nestedItemEditingKeepsSaveVisibleAndPreservesUntouchedRows() {
        val original = List(8) { index -> EditableItem(name = "项目${index + 1}", amountText = "1.00",
            rawText = "原始明细${index + 1}", baselineAmountCents = 100L, sourcePublicId = "item-$index") }
        var drafts by mutableStateOf(original)
        var saving by mutableStateOf(false)
        val saved = mutableListOf<List<EditableItem>>()
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                ItemsEditorSheet(
                    state = ItemsEditorSheetState(drafts, 800L, saving = saving),
                    actions = ItemsEditorSheetActions(
                        onUpdate = { index, name, amount, kind -> drafts = drafts.mapIndexed { position, item ->
                            if (position == index) item.copy(name = name ?: item.name,
                                amountText = amount ?: item.amountText, kind = kind ?: item.kind) else item
                        } },
                        onAddRow = { error("The save action must not add an item") },
                        onRemoveRow = { error("The save action must not remove an item") },
                        onSave = { saved += drafts.toList(); saving = true },
                        onDismiss = {},
                    ),
                )
            }
        }
        compose.onNodeWithText("项目1").performScrollTo().performTouchInput { click() }
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTouchInput { click() }
            .performTextReplacement("修正品名")
        val save = text(R.string.expense_edit_items_save_button)
        keyboard.assertActionAboveKeyboard(compose, save, "items-keyboard-nested-list")
        compose.onNodeWithText(save).performTouchInput { click() }
        compose.runOnIdle { assertEquals(listOf(original.toMutableList().apply {
            this[0] = this[0].copy(name = "修正品名")
        }.toList()), saved) }
        compose.onNodeWithText(text(R.string.expense_edit_items_saving_button)).assertIsNotEnabled()
        compose.onNodeWithTag("expense-item-amount-0").assertIsNotEnabled()
    }

    @Test fun bulkCategoryAndTagCommandsKeepTheirReasonAndReplacementConfirmation() {
        val categories = mutableListOf<Pair<String, String>>()
        val tags = mutableListOf<Pair<String, String>>()
        val receipt = (ledgerHeaderConfirmedRow() as ConfirmedStreamItem.ExpenseRow).root.copy(tags = "出差")
        val expenses = listOf(receipt,
            receipt.copy(id = 2, merchant = "出差车票", originalCurrencyCodeRaw = "KWD", originalAmountMinor = 12345L))
        var state by mutableStateOf(LedgerUiState(
            items = expenses.map { (ledgerHeaderConfirmedRow() as ConfirmedStreamItem.ExpenseRow).copy(root = it) },
            selectedIds = setOf(1L, 2L), selectedExpenses = expenses, selectedHaveTags = true,
            categories = listOf("餐饮", "交通"), selectionMode = true,
        ))
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                LedgerScreen(state = state, actions = LedgerScreenActions(
                    onApplyBatchCategory = { category, reason -> categories += category to reason },
                    onApplyBatchTags = { value, reason -> tags += value to reason },
                ))
            }
        }
        compose.onNodeWithText(text(R.string.ledger_selection_edit)).performTouchInput { click() }
        compose.onNodeWithText("12.345", substring = true).assertExists()
        compose.waitForIdle()
        InstrumentationRegistry.getInstrumentation().uiAutomation.waitForIdle(500, 5_000)
        com.ticketbox.ui.saveConsumerArtPreview("ledger-bulk-preview-paper",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNode(hasSetTextAction() and hasText(text(R.string.expense_edit_category_field_label)))
            .performScrollTo().performTextInput("交通")
        compose.onNode(hasSetTextAction() and hasText(text(R.string.ledger_bulk_reason_label)))
            .performScrollTo().performTouchInput { click() }.performTextInput("补记通勤用途")
        val categoryAction = context.getString(R.string.ledger_bulk_apply_category, 2)
        keyboard.assertActionAboveKeyboard(compose, categoryAction, "bulk-category-keyboard")
        compose.onNodeWithText(categoryAction).performTouchInput { click() }
        compose.runOnIdle {
            assertEquals(listOf("交通" to "补记通勤用途"), categories)
            assertTrue(tags.isEmpty())
            state = state.copy(message = UiText.raw("连接失败，请重试"), messageTone = MessageTone.Danger, readOnly = true)
        }
        compose.onNode(hasText("连接失败，请重试") and hasAnyAncestor(isDialog())).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(categoryAction).assertIsNotEnabled()
        compose.onNodeWithText(text(R.string.ledger_bulk_reason_label))
            .assertTextContains("补记通勤用途").assertIsNotEnabled()
        compose.runOnIdle { state = state.copy(readOnly = false, message = null) }
        compose.onNode(hasSetTextAction() and hasText(text(R.string.expense_edit_category_field_label)))
            .assertTextContains("交通")
        compose.onNodeWithText(text(R.string.ledger_bulk_replace_tags_title)).performScrollTo().performTouchInput { click() }
        compose.onNode(hasSetTextAction() and hasText(text(R.string.ledger_bulk_tags_label)))
            .performScrollTo().performTouchInput { click() }.performTextInput("通勤")
        val tagsAction = context.getString(R.string.ledger_bulk_apply_tags, 2)
        keyboard.assertActionAboveKeyboard(compose, tagsAction, "bulk-tags-keyboard")
        compose.onNodeWithText(tagsAction).performTouchInput { click() }
        compose.onNodeWithText(text(R.string.ledger_bulk_tags_confirm_message)).assertIsDisplayed()
        compose.runOnIdle { assertTrue(tags.isEmpty()) }
        compose.onNodeWithText(text(R.string.ledger_bulk_tags_confirm_replace)).performTouchInput { click() }
        compose.runOnIdle {
            assertEquals(listOf("通勤" to "补记通勤用途"), tags)
            assertEquals(1, categories.size)
        }
        compose.onNodeWithText(text(R.string.ledger_bulk_keep_selection)).performTouchInput { click() }
        compose.onNodeWithText(context.getString(R.string.ledger_bulk_title, 2)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.ledger_selection_count, 2)).assertIsDisplayed()
    }

    private fun field(index: Int, value: String) {
        compose.onAllNodes(hasSetTextAction())[index]
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
