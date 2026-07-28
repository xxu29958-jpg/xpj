package com.ticketbox.viewmodel

import com.ticketbox.domain.model.CurrencyCode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

/**
 * PR#255 R14-1：金额编辑器回填/均分的 record 币种同源钉（独立文件 ——
 * ExpenseEditViewModelTest 已贴 detekt LargeClass 门，新钉不再加码）。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseEditViewModelCurrencyTextTest {

    private fun edit(block: suspend TestScope.(FakeExpenseEditActions) -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block(FakeExpenseEditActions())
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    private fun TestScope.viewModel(fake: FakeExpenseEditActions): ExpenseEditViewModel {
        val vm = ExpenseEditViewModel(expenseId = 7L, repository = fake)
        advanceUntilIdle()
        return vm
    }

    @Test
    fun centsToYuanTextPassesUnknownRecordCodeThroughAsRawMinor() = edit { fake ->
        // 未知码（VND，枚举已回落 CNY）：原 minor 整数原样回填 —— 不冒 CNY 两位口径把
        // 1200 VND 写成 "12.00"；已知零小数码（JPY）不 ÷100；CNY 维持两位。
        val vm = viewModel(fake)

        vm._uiState.update { it.copy(expense = fake.baseExpense.copy(homeCurrencyCode = "VND")) }
        assertEquals("1200", vm.centsToYuanText(1_200L))

        vm._uiState.update {
            it.copy(
                expense = fake.baseExpense.copy(
                    homeCurrency = CurrencyCode.JPY,
                    homeCurrencyCode = "JPY",
                ),
            )
        }
        assertEquals("1200", vm.centsToYuanText(1_200L))

        vm._uiState.update { it.copy(expense = fake.baseExpense) }
        assertEquals("12.00", vm.centsToYuanText(1_200L))
    }

    @Test
    fun evenSplitParsesAndRendersInRecordZeroDecimalCurrency() = edit { fake ->
        // JPY 票据：parent 1201 两人均分 → "601"/"600"（不 ÷100 成 "6.01"）；disabled
        // 固定份额 "600" 也按 JPY 解析（600 minor，非 60000）—— 显示与解析同源才能对平。
        val vm = viewModel(fake)
        vm._uiState.update {
            it.copy(
                expense = fake.baseExpense.copy(
                    homeCurrency = CurrencyCode.JPY,
                    homeCurrencyCode = "JPY",
                ),
                expenseSplits = fake.splits(parentAmountCents = 1_201L),
                splitDrafts = listOf(
                    EditableSplit(memberId = 1L, displayName = "甲", included = true),
                    EditableSplit(memberId = 2L, displayName = "乙", included = true),
                ),
            )
        }

        vm.evenSplitAmounts()

        val drafts = vm.uiState.value.splitDrafts
        assertEquals("601", drafts[0].amountText)
        assertEquals("600", drafts[1].amountText)
    }

    @Test
    fun evenSplitUsesRawMinorSpaceForUnknownRecordCode() = edit { fake ->
        // PR#255 R15b-2：未知码（VND）票据的均分按原 minor 整数口径 —— parent 1201
        // 两人均分 "601"/"600"（旧码落 CNY 兜底解析/渲染，footer 与回填互相放大 100×）。
        val vm = viewModel(fake)
        vm._uiState.update {
            it.copy(
                expense = fake.baseExpense.copy(homeCurrencyCode = "VND"),
                expenseSplits = fake.splits(parentAmountCents = 1_201L),
                splitDrafts = listOf(
                    EditableSplit(memberId = 1L, displayName = "甲", included = true),
                    EditableSplit(memberId = 2L, displayName = "乙", included = true),
                ),
            )
        }

        vm.evenSplitAmounts()

        val drafts = vm.uiState.value.splitDrafts
        assertEquals("601", drafts[0].amountText)
        assertEquals("600", drafts[1].amountText)
    }
}
