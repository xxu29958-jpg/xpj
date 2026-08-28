package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseItem
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle

/** A1: 更正明细投影保留隐藏事实，并拒绝无效金额。 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelCorrectionItemsTest : ExpenseFactViewModelTestBase() {

    @Test
    fun `items untouched or unchanged under the editor projection stays out of the intent`() = edit { fake ->
        fake.itemsResult = Result.success(correctionItemsFixture())
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")
        vm.openCorrectionItemsEditor()
        // 打开后未改动就采用：投影相同，不进 intent；商家变化让更正整体成立。
        vm.adoptCorrectionItems()
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "新商家")

        vm.submitCorrection()
        advanceUntilIdle()

        assertNotNull(fake.lastCorrectionDraft)
        assertEquals("新商家", fake.lastCorrectionDraft?.merchant)
        assertNull(fake.lastCorrectionDraft?.items, "投影未变的明细不得进更正意图")
    }

    @Test
    fun `changed item amount enters the composite intent`() = edit { fake ->
        fake.itemsResult = Result.success(correctionItemsFixture())
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "小票金额看错了")
        vm.openCorrectionItemsEditor()
        vm.updateCorrectionItemDraft(0, name = null, amountText = "8.00", kind = null)
        vm.adoptCorrectionItems()

        vm.submitCorrection()
        advanceUntilIdle()

        val items = assertNotNull(fake.lastCorrectionDraft?.items)
        assertEquals(1, items.size)
        assertEquals(800L, items[0].amountCents)
        assertEquals("苹果", items[0].name)
    }

    @Test
    fun `changed item preserves hidden metadata instead of replacing it with defaults`() = edit { fake ->
        fake.itemsResult = Result.success(correctionItemsWithHiddenMetadata())
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "金额识别错了")
        vm.openCorrectionItemsEditor()
        vm.updateCorrectionItemDraft(0, name = null, amountText = "8.00", kind = null)
        vm.adoptCorrectionItems()

        vm.submitCorrection()
        advanceUntilIdle()

        val item = assertNotNull(fake.lastCorrectionDraft?.items).single()
        assertEquals("2个", item.quantityText)
        assertEquals(300L, item.unitPriceCents)
        assertEquals("水果", item.category)
        assertEquals("OCR 苹果 x2", item.rawText)
        assertEquals(0.91, item.confidence)
    }

    @Test
    fun `invalid item amount is rejected instead of becoming zero`() = edit { fake ->
        fake.itemsResult = Result.success(correctionItemsFixture())
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "金额识别错了")
        vm.openCorrectionItemsEditor()
        vm.updateCorrectionItemDraft(0, name = null, amountText = "abc", kind = null)
        vm.adoptCorrectionItems()

        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(0, fake.correctCalls)
        assertEquals(
            R.string.expense_correction_items_amount_invalid,
            (vm.uiState.value.message as? UiText.Res)?.id,
        )
    }
}

private fun correctionItemsFixture(): ExpenseItems = ExpenseItems(
    expenseId = 7L,
    parentAmountCents = 1000L,
    itemsTotalAmountCents = 600L,
    mismatchCents = 400L,
    items = listOf(
        ExpenseItem(
            publicId = "item-1",
            position = 1,
            kind = "product",
            name = "苹果",
            quantityText = "2个",
            unitPriceCents = 300L,
            amountCents = 600L,
            category = "餐饮",
            rawText = null,
            confidence = null,
            isOcrDraft = false,
            createdAt = "2026-08-22T11:38:00Z",
            updatedAt = "2026-08-22T11:38:00Z",
        ),
    ),
)

private fun correctionItemsWithHiddenMetadata(): ExpenseItems = correctionItemsFixture().copy(
    items = listOf(
        correctionItemsFixture().items.single().copy(
            category = "水果",
            rawText = "OCR 苹果 x2",
            confidence = 0.91,
            isOcrDraft = true,
        ),
    ),
)
