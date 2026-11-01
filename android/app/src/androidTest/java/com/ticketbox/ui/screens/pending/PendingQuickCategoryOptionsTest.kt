package com.ticketbox.ui.screens.pending

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.DefaultExpenseCategories
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.PendingReviewValues
import com.ticketbox.viewmodel.PendingSheet
import com.ticketbox.viewmodel.PendingUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** 收件快速分类: 账本分类还没读到或读取失败时, 仍有默认分类可点; 点选后保存的就是所点分类。 */
class PendingQuickCategoryOptionsTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun quickCategoryOffersDefaultsBeforeTheLedgerListArrives() {
        val saved = mutableListOf<String>()
        var input by mutableStateOf(PendingReviewValues())
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                PendingReviewSheetHost(
                    state = PendingReviewSheetHostState(PendingSheet.QuickCategory(uncategorized()),
                        PendingUiState().categoryOptions, emptySet(), 0, 0, 0, false, 0, 0, 1, null,
                        inputValues = input),
                    actions = PendingReviewSheetHostActions(onSaveQuickCategory = { _, value -> saved += value },
                        onSaveQuickMerchant = { _, _ -> }, onSaveAmountDraft = { _, _ -> },
                        onSaveAmountAndConfirm = { _, _ -> }, onSkipReviewField = {}, onKeepBoth = {},
                        onIgnoreCurrent = {}, onConfirmReady = {}, onDismiss = {},
                        onReviewInputChange = { input = it }),
                )
            }
        }
        compose.onNodeWithText(DefaultExpenseCategories.TRANSIT).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.quick_category_save_button)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals(listOf(DefaultExpenseCategories.TRANSIT), saved) }
    }

    private fun uncategorized() = Expense(
        id = 7L, publicId = "quick-category-defaults", amountCents = 1280L, merchant = "街角小馆",
        category = "", note = null, source = ExpenseSourceValues.ANDROID_SCREENSHOT, imagePath = null,
        thumbnailPath = null, imageHash = null, rawText = null, confidence = null,
        duplicateStatus = "", duplicateOfId = null, duplicateReason = null, tags = null,
        valueScore = null, regretScore = null, status = "pending", expenseTime = null,
        createdAt = "2026-10-01T01:00:00Z", updatedAt = "2026-10-01T01:00:00Z",
        rowVersion = 1L, confirmedAt = null, rejectedAt = null,
    )
}
