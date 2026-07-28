package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals

/** 预算写的账本币种 capability 族（PR#255 R13-7），自 BudgetViewModelTest 拆出以符合
 *  detekt 函数数门（镜像 GlobalSearch / DebtList 的拆分类先例）。 */
class BudgetViewModelCapabilityTest {

    @Test
    fun saveParsesAmountsInLedgerCapability() = budgetTest {
        // R13-7：预算写按账本信封 capability 解析（R6/R12-D 同源）—— JPY 账本 "1200" →
        // 1200 minor（零小数不 ×100），不再硬编 ×100。
        val fake = FakeBudgetActions(budget = budget(configured = false))
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY"),
        )
        val vm = BudgetViewModel(fake, debts, initialMonth = "2026-05")
        advanceUntilIdle()

        vm.updateTotalAmount("1200")
        vm.updateCategoryRow(0, "吃饭", "1200")
        vm.save()
        advanceUntilIdle()

        val request = fake.savedRequests.single()
        assertEquals(1_200L, request.totalAmountCents)
        assertEquals(1_200L, request.categoryBudgets.single().amountCents)
    }

    @Test
    fun saveBlockedWhenCapabilityUnsupported() = budgetTest {
        // R13-7：capability 在支持集外 → 禁写 + 明示文案，repository 不可达。
        val fake = FakeBudgetActions(budget = budget(configured = false))
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "VND"),
        )
        val vm = BudgetViewModel(fake, debts, initialMonth = "2026-05")
        advanceUntilIdle()

        assertEquals(null, vm.uiState.value.ledgerCurrency)
        vm.updateTotalAmount("1200")
        vm.save()
        advanceUntilIdle()

        assertEquals(0, fake.savedRequests.size)
        assertEquals(
            UiText.res(R.string.currency_unconfirmed_write_blocked),
            vm.uiState.value.message,
        )
    }
}
