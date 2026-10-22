package com.ticketbox.ui.screens

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.repository.toRequest
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.ExpenseItem
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplit
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.viewmodel.EditableItem
import com.ticketbox.viewmodel.EditableSplit
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.ui.screens.expense.ItemsEditorSheetActions
import com.ticketbox.ui.screens.expense.SplitsEditorSheetActions
import com.ticketbox.ui.screens.expense.TAG_SPLITS_DETAIL_ROW
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.expense.TAG_ITEMS_DETAIL_ROW
import com.ticketbox.ui.screens.expense.TAG_TAGS_FIELD
import com.ticketbox.ui.screens.expense.TAG_TIME_ROW
import com.ticketbox.ui.screens.expense.TAG_VALUE_SCORE_FIELD
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.ExpenseEditUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test

class ExpenseEditScreenContractTest {
    @get:Rule
    val composeRule = createComposeRule()

    private val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
        AppSkin.Midnight else AppSkin.Default

    @Test
    fun localSubtasksKeepMainInputAndShowFailuresAtTheirOwnAction() {
        val item = ExpenseItem("item-a", 0, name = "家庭日用品与一段需要完整阅读的商品名称", quantityText = "2",
            unitPriceCents = 5000, amountCents = 10000, category = "日用品", rawText = null,
            confidence = null, isOcrDraft = false, createdAt = "2026-10-01", updatedAt = "2026-10-01")
        val split = ExpenseSplit("split-a", 0, 1, "家人甲的日常份额", "member", 6860,
            "这份备注应随原明细保留", null, "2026-10-01", "2026-10-01")
        val state = androidx.compose.runtime.mutableStateOf(ExpenseEditUiState(
            expenseItems = ExpenseItems(1, 10000, 10000, 0, "matched", listOf(item)),
            expenseSplits = ExpenseSplits(1, 12860, 6860, -6000, listOf(split)),
            itemsLoadState = ExpenseDetailDataLoadState.Loaded, splitsLoadState = ExpenseDetailDataLoadState.Loaded,
            itemDrafts = listOf(EditableItem(name = item.name, amountText = "100.00")),
            splitDrafts = listOf(EditableSplit(1, split.accountName, true, "68.60", note = split.note)),
        ))
        var itemSaves = 0
        var splitSaves = 0
        var confirms = 0
        var mainDraft: ExpenseDraft? = null
        composeRule.setContent {
            TicketboxTheme(skin = skin) {
                ExpenseEditScreen(expenseEditScreenState(editState = state.value), ExpenseEditScreenActions(
                    primary = ExpenseEditPrimaryActions(onSave = { mainDraft = it }, onConfirm = { confirms++ }),
                    itemization = ExpenseEditItemizationActions(onEditItems = { state.value = state.value.copy(itemEditorOpen = true) },
                        editor = ItemsEditorSheetActions(
                            onUpdate = { index, name, amount, kind -> state.value = state.value.copy(itemDrafts = state.value.itemDrafts.mapIndexed { pos, row ->
                                if (pos == index) row.copy(name = name ?: row.name, amountText = amount ?: row.amountText, kind = kind ?: row.kind) else row
                            }) }, onAddRow = {}, onRemoveRow = {},
                            onSave = { itemSaves++; state.value = if (itemSaves == 1) state.value.copy(
                                itemsMessage = UiText.raw("保存未完成，原输入仍保留"), itemsMessageTone = MessageTone.Danger)
                                else state.value.copy(itemEditorOpen = false, itemsMessage = null) },
                            onDismiss = { state.value = state.value.copy(itemEditorOpen = false) },
                        )),
                    splitEditing = ExpenseEditSplitEditingActions(onEditSplits = { state.value = state.value.copy(splitEditorOpen = true) },
                        editor = SplitsEditorSheetActions({ _, _ -> }, { _, text -> state.value = state.value.copy(
                            splitDrafts = state.value.splitDrafts.map { it.copy(amountText = text) }) }, {},
                            { splitSaves++; state.value = state.value.copy(splitEditorOpen = false) },
                            { state.value = state.value.copy(splitEditorOpen = false) })),
                ))
            }
        }
        composeRule.onNodeWithTag("expense-edit-more-row").performScrollTo().performClick()
        composeRule.onNodeWithTag(TAG_TAGS_FIELD).performScrollTo().performTextReplacement("继续核对的原输入")
        closeSoftKeyboard()
        composeRule.onNodeWithTag(TAG_ITEMS_DETAIL_ROW).performScrollTo().performClick()
        composeRule.onNodeWithText("编辑明细").performScrollTo().performClick()
        capture("review-item-reading")
        composeRule.onNodeWithTag("expense-item-editor-0").performScrollTo().performClick()
        composeRule.onNodeWithTag("expense-item-amount-0").performScrollTo().performTextReplacement("000101.00")
        closeSoftKeyboard()
        composeRule.onNodeWithText("保存明细并返回").performClick()
        composeRule.onNode(hasText("保存未完成，原输入仍保留") and hasAnyAncestor(isDialog())).assertIsDisplayed()
        capture("review-item-error")
        composeRule.onNodeWithText("返回，保留输入").performClick()
        composeRule.onNodeWithText("编辑明细").performScrollTo().performClick()
        composeRule.onNodeWithTag("expense-item-editor-0").performScrollTo().performClick()
        composeRule.onNodeWithTag("expense-item-amount-0").performScrollTo().assertIsDisplayed()
        composeRule.runOnIdle { assertEquals("000101.00", state.value.itemDrafts.single().amountText) }
        composeRule.onNodeWithText("保存明细并返回").performClick()
        composeRule.onNodeWithTag(TAG_SPLITS_DETAIL_ROW).performScrollTo().performClick()
        composeRule.onNodeWithText("编辑拆账").performScrollTo().performClick()
        capture("review-split-reading")
        composeRule.onNodeWithTag("expense-split-editor-1").performScrollTo().performClick()
        composeRule.onNodeWithTag("expense-split-amount-1").performScrollTo().performTextReplacement("00068.60")
        closeSoftKeyboard()
        composeRule.onNodeWithText("保存拆账并返回").performClick()
        composeRule.onNodeWithText("保存").performClick()
        composeRule.runOnIdle {
            assertEquals("继续核对的原输入", mainDraft?.tags)
            assertEquals("00068.60", state.value.splitDrafts.single().amountText)
            assertEquals(2, itemSaves)
            assertEquals(1, splitSaves)
            assertEquals(0, confirms)
        }
    }

    @Test
    fun cachedReceiptKeepsTheReadOnlyOriginalImageAction() {
        var originalRequests = 0
        composeRule.setContent {
            TicketboxTheme(skin = skin) {
                ExpenseEditScreen(
                    screenState = expenseEditScreenState(
                        expense = expense().copy(
                            hasImage = true,
                            duplicateStatus = "suspected",
                            duplicateReason = "原件完全一致；交易信息不足，需对照原件核实",
                        ),
                        editState = ExpenseEditUiState(readOnly = true),
                    ),
                    actions = ExpenseEditScreenActions(
                        media = ExpenseEditMediaActions(onLoadFullImage = { originalRequests += 1 }),
                    ),
                )
            }
        }

        composeRule.onNodeWithText("交易信息不足", substring = true)
            .performScrollTo().assertIsDisplayed()
        capture("review-duplicate-evidence-readonly")
        composeRule.onNodeWithText("看原图").performScrollTo().assertIsEnabled().performClick()
        composeRule.runOnIdle { assertEquals(1, originalRequests) }
    }

    @Test
    fun evidenceChoicesKeepEditedAmountAndOtherDuplicateCandidatesUntilExplicitSave() {
        var saved: ExpenseDraft? = null
        var opened: Long? = null
        var kept = 0
        val day = com.ticketbox.domain.model.RecognitionTimeCandidate("day", "交易日期", "原件只有日期。",
            "交易日期：2025-12-31", "2025-12-31", "date_only", "Asia/Shanghai", null, true)
        val recorded = expense().copy(expenseTime = null, originalAmountMinor = 1234L,
            accountingTime = com.ticketbox.domain.model.ExpenseAccountingTime("unknown", calendarRevision = 1L),
            recognitionTime = com.ticketbox.domain.model.RecognitionTime("fact", "receipt-fields-v2", "needs_review", listOf(day)),
            recognitionNotes = listOf("原件金额存在冲突，请核对现有草稿。"),
            duplicateStatus = "suspected", duplicateOfId = 2L, duplicateCandidateIds = listOf(2L, 3L),
            duplicateReason = "原件完全一致；交易信息不足，需对照原件核实")
        composeRule.setContent {
            TicketboxTheme(skin = skin) {
                ExpenseEditScreen(expenseEditScreenState(expense = recorded), ExpenseEditScreenActions(
                    primary = ExpenseEditPrimaryActions(onSave = { saved = it }),
                    related = ExpenseEditRelatedActions(onKeepDuplicate = { kept++ }, onOpenDuplicateReference = { opened = it }),
                ))
            }
        }
        composeRule.onNodeWithText("原件金额存在冲突，请核对现有草稿。").performScrollTo().assertIsDisplayed()
        composeRule.onNode(hasSetTextAction() and hasText("12.34")).performScrollTo().performTextReplacement("22.00")
        closeSoftKeyboard()
        composeRule.onNodeWithText("查看其他候选 #3").performScrollTo().performClick()
        composeRule.onNodeWithTag("expense-edit-time-section").performScrollTo().performClick()
        composeRule.onNodeWithText("将此时间填入草稿").performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(3L, opened); assertEquals(null, saved); assertEquals(0, kept) }
        capture("review-recognized-date-explicit-choice")
        composeRule.onNodeWithText("保存").performClick()
        composeRule.runOnIdle {
            assertEquals(2200L, saved?.originalAmountMinor)
            assertEquals("date_only", saved?.timeInput?.precision)
            assertEquals("2025-12-31", saved?.timeInput?.userLocalDate)
            assertEquals(null, saved?.expenseTime)
        }
        composeRule.onNodeWithText("与参考账单不是重复，保留两笔").performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(1, kept) }
        composeRule.onNodeWithText("查看其他候选 #3").assertExists()
    }

    @Test
    fun expenseTimeAndMoreSectionClicksStayStableAndSubmitDraft() {
        var retryCount = 0
        var savedDraft: ExpenseDraft? = null
        val recorded = expense().copy(
            amountCents = 12_345L, homeAmountCents = 12_345L,
            homeCurrency = CurrencyCode.KWD, originalCurrency = CurrencyCode.KWD,
            originalCurrencyCode = CurrencyCode.KWD, originalAmountMinor = 12_345L,
            categorySuggestion = com.ticketbox.domain.model.ExpenseCategorySuggestion("日用品", 3),
        )

        composeRule.setContent {
            TicketboxTheme(skin = skin) {
                ExpenseEditScreen(
                    screenState = expenseEditScreenState(
                        expense = recorded,
                        editState = ExpenseEditUiState(
                            categories = listOf("餐饮", "交通", "其他"),
                        ),
                    ),
                    actions = ExpenseEditScreenActions(
                        primary = ExpenseEditPrimaryActions(
                            onSave = { savedDraft = it },
                        ),
                        media = ExpenseEditMediaActions(
                            onRetryOcr = { retryCount += 1 },
                        ),
                    ),
                )
            }
        }

        composeRule.onNode(hasSetTextAction() and hasText("12.345")).assertIsDisplayed()
        composeRule.onNodeWithTag("expense-use-category-suggestion").performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(null, savedDraft) } // Filling advice alone cannot publish.
        capture("review-learning-category-filled")
        composeRule.onNodeWithTag("expense-edit-more-row").performScrollTo().performClick()
        composeRule.onNode(hasSetTextAction() and hasText(recorded.note!!))
            .performScrollTo().performTextReplacement("仅改备注")
        closeSoftKeyboard()
        composeRule.onNodeWithText("保存").performClick()
        composeRule.runOnIdle {
            val request = requireNotNull(savedDraft).toRequest(recorded)
            assertEquals("仅改备注", request.note)
            assertEquals("日用品", request.category)
            assertEquals(null, request.originalAmount)
            assertEquals(recorded.rowVersion, request.expectedRowVersion)
        }
        composeRule.onNode(hasSetTextAction() and hasText("12.345"))
            .performScrollTo().performTextReplacement("12.346")
        closeSoftKeyboard()
        capture("review-kwd-edited-amount")
        composeRule.onNodeWithTag("expense-edit-time-section").performScrollTo().performClick()
        // 日期 picker 的主路径是点时间行本身；「选时间」仍是行内安静动作。
        composeRule.onNodeWithTag(TAG_TIME_ROW).performScrollTo().performClick()
        composeRule.onNodeWithText("选择日期").assertIsDisplayed()
        composeRule.onNodeWithText("取消").performClick()

        composeRule.onNodeWithText("选时间").performScrollTo().performClick()
        composeRule.onNodeWithText("选择时间").assertIsDisplayed()
        composeRule.onNodeWithText("取消").performClick()

        // Locate the 「更多记录」inputs by stable testTag, not the Material3 label/value text node
        // (which isn't reliably exposed in the semantics tree — was the flaky "标签" lookup).
        composeRule.onNodeWithTag(TAG_TAGS_FIELD).performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithTag(TAG_TAGS_FIELD).performTextReplacement("家庭")
        composeRule.onNodeWithTag(TAG_VALUE_SCORE_FIELD).performScrollTo()
        composeRule.onNodeWithText("查看识别原文").performScrollTo().performClick()
        composeRule.onNodeWithText("重新识别").performScrollTo().performClick()
        // 「保存」现在浮在底部操作栏（不在滚动流里），无需 performScrollTo——
        // 永远一拇指可达正是批 9 的目标。
        composeRule.onNodeWithText("保存").performClick()

        composeRule.runOnIdle {
            assertEquals(1, retryCount)
            assertNotNull(savedDraft)
            val draft = savedDraft!!
            assertEquals("家庭", draft.tags)
            assertEquals(3, draft.valueScore)
            assertEquals(1, draft.regretScore)
            assertEquals("2026-05-12T10:15:00Z", draft.expenseTime)
            assertEquals(12_346L, draft.originalAmountMinor)
            val request = draft.toRequest(recorded)
            assertEquals("12.346", request.originalAmount)
            assertEquals(recorded.rowVersion, request.expectedRowVersion)
        }
    }

    @Test
    fun pendingActionBarShowsConfirmRejectWithoutScrolling() {
        val amount = InstrumentationRegistry.getArguments().getString("captureAmountMinor")?.toLong() ?: 12860L
        val preview = InstrumentationRegistry.getArguments().getString("captureOriginalPath")?.let {
            ProtectedImage(java.io.File(it).readBytes(), "image/jpeg")
        }
        composeRule.setContent {
            TicketboxTheme(skin = skin) {
                ExpenseEditScreen(
                    screenState = expenseEditScreenState(
                        expense = expense().copy(amountCents = amount, originalAmountMinor = amount,
                            merchant = "便利店", category = "日用品", hasImage = preview != null),
                        editState = ExpenseEditUiState(thumbnail = preview),
                        actionAvailability = ExpenseEditActionAvailability(
                            allowConfirm = true,
                            allowReject = true,
                        ),
                    ),
                    actions = ExpenseEditScreenActions(),
                )
            }
        }

        // pending 态：确认入账 / 保存 / 忽略 都在浮动栏里，开屏即可见。
        composeRule.onNodeWithText("确认入账").assertIsDisplayed()
        composeRule.onNodeWithText("保存").assertIsDisplayed()
        composeRule.onNodeWithText("忽略").assertIsDisplayed()
        capture("review-header")
        composeRule.onNodeWithText(com.ticketbox.ui.components.formatAmountInput(amount,
            com.ticketbox.domain.model.CurrencyCode.Default))
            .performScrollTo().assertIsDisplayed()
        capture("review-amount")
        composeRule.onNodeWithTag(TAG_ITEMS_DETAIL_ROW).performScrollTo().assertIsDisplayed()
        capture("review-details")
    }

    @Test
    fun confirmedExpenseActionBarHidesConfirmAndReject() {
        composeRule.setContent {
            TicketboxTheme(skin = skin) {
                ExpenseEditScreen(
                    screenState = expenseEditScreenState(
                        expense = expense().copy(status = "confirmed"),
                        actionAvailability = ExpenseEditActionAvailability(
                            allowConfirm = false,
                            allowReject = false,
                        ),
                    ),
                    actions = ExpenseEditScreenActions(),
                )
            }
        }

        // 已入账：只剩保存 + 返回，确认/忽略收起（语义对齐 ExpenseEditRoute）。
        composeRule.onNodeWithText("保存").assertIsDisplayed()
        composeRule.onNode(hasText("返回") and !hasContentDescription("返回")).assertIsDisplayed()
        composeRule.onNodeWithText("确认入账").assertDoesNotExist()
        composeRule.onNodeWithText("忽略").assertDoesNotExist()
    }

    @Test
    fun billSplitSourceRendersHumanLabelNotRawToken() {
        composeRule.setContent {
            TicketboxTheme(skin = skin) {
                ExpenseEditScreen(
                    screenState = expenseEditScreenState(
                        expense = expense().copy(source = "bill_split_received"),
                        editState = ExpenseEditUiState(readOnly = true),
                    ),
                    actions = ExpenseEditScreenActions(),
                )
            }
        }

        // 来源行不再漏裸 token：bill_split_received → 来源：拆账。
        composeRule.onNodeWithText("来源：拆账").performScrollTo().assertIsDisplayed()
    }

    private fun expenseEditScreenState(
        expense: Expense = expense(),
        editState: ExpenseEditUiState = ExpenseEditUiState(),
        actionAvailability: ExpenseEditActionAvailability = ExpenseEditActionAvailability(),
    ): ExpenseEditScreenState = ExpenseEditScreenState(
        expense = expense,
        editState = editState,
        actionAvailability = actionAvailability,
    )

    private fun capture(name: String) {
        composeRule.waitForIdle()
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(100, 2_000)
        saveConsumerArtPreview(name, requireNotNull(automation.takeScreenshot()))
    }

    private fun expense(): Expense = Expense(
        id = 1L,
        publicId = "pub-1",
        amountCents = 1234L,
        merchant = "QA Merchant",
        category = "其他",
        note = "qa pending edit flow",
        source = "android-qa",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = "qa raw text line 1\nqa raw text line 2",
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = "qa",
        valueScore = 3,
        regretScore = 1,
        status = "pending",
        expenseTime = "2026-05-12T10:15:00Z",
        createdAt = "2026-05-13T13:10:55Z",
        updatedAt = "2026-05-13T13:10:55Z",
        rowVersion = 1L,
        confirmedAt = null,
        rejectedAt = null,
    )
}
