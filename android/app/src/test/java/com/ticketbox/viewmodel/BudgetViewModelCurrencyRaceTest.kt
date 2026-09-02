package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import java.lang.reflect.Proxy
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

/**
 * PR#255 R15a-1/2：BudgetViewModel 回填×save 币种竞态与一次性门闩的钉（独立文件 ——
 * BudgetViewModelTest 已贴 detekt 门类门，镜像 BudgetViewModelCapabilityTest 拆分类先例）。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class BudgetViewModelCurrencyRaceTest {

    @Test
    fun jpyCapabilityBackfillsWithoutScaling() = budgetTest {
        // R15a-1：configured + JPY capability → 回填零缩放（"1200" 不变成 "12"）——
        // init 串行化（先解析币种后 refresh/回填）后，两种落定序都不会产生缩放回填。
        val fake = FakeBudgetActions(budget = budget(totalAmountCents = 1_200L))
        val debts = CapabilityDebtActions(
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY"),
        )
        val vm = BudgetViewModel(fake, debts, initialMonth = "2026-05")
        advanceUntilIdle()

        assertEquals(CurrencyCode.JPY, vm.uiState.value.ledgerCurrency)
        assertEquals("1200", vm.uiState.value.form.totalAmount)
    }

    @Test
    fun offlineStartLeavesFormEmptyAndSaveRecoversViaReresolution() = budgetTest {
        // R15a-1+2：离线冷启动（listDebts 失败）→ 不按 CNY 兜底缩放回填（空表单 + 禁写）；
        // 网络恢复后写尝试自带重解析 —— 一次 save：重解析 JPY → 未触碰表单重回填 →
        // 按 JPY 零缩放保存 1200 minor（一次性门闩解除）。
        val fake = FakeBudgetActions(budget = budget(totalAmountCents = 1_200L))
        val debts = RecoverableDebtActions(online = false)
        val vm = BudgetViewModel(fake, debts, initialMonth = "2026-05")
        advanceUntilIdle()

        assertEquals(null, vm.uiState.value.ledgerCurrency)
        assertEquals("", vm.uiState.value.form.totalAmount)
        assertNotNull(vm.uiState.value.budget, "读面不受币种门闩影响（budget 可读）")

        debts.online = true
        vm.save()
        advanceUntilIdle()

        assertEquals(CurrencyCode.JPY, vm.uiState.value.ledgerCurrency)
        assertEquals("1200", vm.uiState.value.form.totalAmount)
        assertEquals(1_200L, fake.savedRequests.single().totalAmountCents)
    }

    @Test
    fun ledgerSwitchDoesNotReuseStaleCurrencyForBackfill() = budgetTest {
        // R15a-1 账本切换变体：CNY 账本回填 "3000" 后切 JPY 账本 —— 状态重置清旧币种
        // 重解析，回填按 JPY 零缩放（"300000"），旧 CNY 口径（"3000"）不得残留。
        val accessFlow = MutableStateFlow(raceAccess(ledgerId = "ledger-a"))
        val fake = FakeBudgetActions(
            budget = budget(totalAmountCents = 300_000L),
            activeAccessFlow = accessFlow,
        )
        val debts = RecoverableDebtActions(
            online = true,
            page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "CNY"),
        )
        val vm = BudgetViewModel(fake, debts, initialMonth = "2026-05")
        advanceUntilIdle()
        assertEquals("3000", vm.uiState.value.form.totalAmount)

        debts.page = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY")
        accessFlow.value = raceAccess(ledgerId = "ledger-b")
        advanceUntilIdle()

        assertEquals(CurrencyCode.JPY, vm.uiState.value.ledgerCurrency)
        assertEquals("300000", vm.uiState.value.form.totalAmount)
    }
}

/** 可切换在线态的账本币种 fake（R15a 钉）：offline 时 listDebts 失败，online 时返回 page。 */
private class RecoverableDebtActions(
    var online: Boolean,
    var page: DebtListPage = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY"),
) : DebtActions by unsupportedRaceDebtActions() {
    override fun canModifyLedger(): Boolean = true

    override suspend fun listDebts(lens: com.ticketbox.domain.model.DebtListLens): Result<DebtListPage> =
        if (online) Result.success(page) else Result.failure(IllegalStateException("offline"))
}

private fun raceAccess(ledgerId: String): LedgerAccessContext = LedgerAccessContext(
    binding = LogicalSessionBinding(
        serverUrl = "https://api.example.com",
        ledgerId = ledgerId,
        ownerKey = "owner",
        sessionGeneration = "session-$ledgerId",
        bindingRevision = "binding-$ledgerId",
    ),
    canModify = true,
)

@Suppress("UNCHECKED_CAST")
private fun unsupportedRaceDebtActions(): DebtActions = Proxy.newProxyInstance(
    DebtActions::class.java.classLoader,
    arrayOf(DebtActions::class.java),
) { _, method, _ ->
    when (method.name) {
        "toString" -> "UnsupportedRaceDebtActions"
        else -> throw UnsupportedOperationException(method.name)
    }
} as DebtActions
