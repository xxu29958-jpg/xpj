package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * v0.4-alpha4 M1：PendingViewModel ADR-0038 撤销（undo）banner 契约测试。
 *
 * 覆盖 V1/V2/V3/V5/V6/V7/V9/V11/V14 等撤销 banner 不变量：synced/queued
 * reject 的 banner seeding 与保序、undo 恢复 / 404 retention / 瞬时网络
 * 错误重试、忽略重复（ignoreDuplicate）的「保留 vs 改动」拆分、5s 自动
 * 消失计时器以及 viewer 降级中途清理。
 *
 * 共享脚手架（review 计时器卫生 helper、expense / image 样本构造器、
 * FakeReviewActions）见 [PendingViewModelReviewTestBase] /
 * [FakeReviewActions]。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelReviewUndoBannerTest : PendingViewModelReviewTestBase() {

    @Test
    fun syncedRejectSeedsUndoableBannerWithRestoredRow() = review {
        // V3 contract: undoableExpense carries the canonical post-reject
        // Expense (status='rejected', via Sweep#2 fake fidelity fix).
        val target = expense(id = 100L)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectResponder = { Result.success(target) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.reject(target)
        // runCurrent — not advanceUntilIdle — so the VM's 5s undo timer
        // doesn't drain via runTest's virtual-time advancement before we
        // read state.undoableExpense.
        runCurrent()

        val state = vm.uiState.value
        val undoable = assertNotNull(state.undoableExpense, "Synced reject seeds the 撤销 banner")
        assertEquals(100L, undoable.id)
        assertEquals("rejected", undoable.status, "banner row carries server post-transition status")
        assertEquals("已删除", state.message)
    }

    @Test
    fun queuedRejectPreservesPriorSyncedUndoableBanner() = review {
        // V1 contract: an offline reject following an online reject must
        // NOT wipe the prior Synced banner. The earlier row is still
        // server-side undoable within its 5-min window; the Queued
        // mutation is in the outbox with nothing to /undo against.
        val first = expense(id = 200L, merchant = "星巴克", amountCents = 4800L)
        val second = expense(id = 201L, merchant = "便利店", amountCents = 1200L)
        val fake = FakeReviewActions(pending = listOf(first, second))
        fake.rejectResponder = { Result.success(first) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.reject(first)
        runCurrent()
        val sycnedBanner = assertNotNull(vm.uiState.value.undoableExpense, "Synced reject sets banner")
        assertEquals(200L, sycnedBanner.id)
        assertEquals("星巴克", sycnedBanner.merchant)

        // Force a Queued outcome on the follow-up reject.
        fake.rejectOfflineResponder = {
            Result.success(
                com.ticketbox.data.repository.ExpenseStateOutcome.Queued(second.copy(status = "rejected")),
            )
        }
        vm.reject(second)
        runCurrent()

        // Round-2 contract: banner still identifies A (200L / 星巴克),
        // NOT the just-rejected B (201L / 便利店). Without the merchant
        // on the banner the UI would be ambiguous — user could think
        // tapping 撤销 restores their most recent action (B's offline
        // reject), when actually it would restore A.
        val state = vm.uiState.value
        val preserved = assertNotNull(
            state.undoableExpense,
            "Queued reject must preserve prior Synced banner",
        )
        assertEquals(200L, preserved.id, "banner row identity must remain A, not flip to B")
        assertEquals("星巴克", preserved.merchant, "banner carries A's merchant for UI disambiguation")
        assertEquals(4800L, preserved.amountCents, "banner carries A's amount for UI disambiguation")
        assertEquals("已离线删除，联网后同步", state.message)
    }

    @Test
    fun undoRejectRestoresRowAtTopAndClearsBanner() = review {
        // V3 contract: restored row inserted at TOP (server orders by
        // created_at DESC), banner cleared, "已撤销" message shown.
        val keep = expense(id = 300L)
        val target = expense(id = 301L)
        val fake = FakeReviewActions(pending = listOf(target, keep))
        fake.rejectResponder = { Result.success(target) }
        fake.undoRejectResponder = { id ->
            assertEquals(301L, id)
            Result.success(target.copy(status = "pending"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.reject(target)
        runCurrent()
        assertEquals(listOf(300L), vm.uiState.value.items.map { it.id })

        vm.undoReject()
        runCurrent()

        val state = vm.uiState.value
        assertEquals(listOf(301L, 300L), state.items.map { it.id }, "restored row goes to TOP not tail")
        assertNull(state.undoableExpense, "banner cleared after successful undo")
        assertEquals("已撤销，账单已恢复待确认。", state.message)
        assertFalse(state.actionInProgressIds.contains(301L))
    }

    @Test
    fun undoRejectExpenseNotFoundClearsBannerWithRetentionMessage() = review {
        // V5 contract: 404 expense_not_found maps to the undo-specific
        // retention-window message, NOT the generic "账单不存在。" that
        // backendErrorUserMessage emits. Banner stays cleared (window
        // is genuinely closed; retry won't help).
        val target = expense(id = 400L)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectResponder = { Result.success(target) }
        fake.undoRejectResponder = {
            Result.failure(RepositoryException("账单不存在。", errorCode = "expense_not_found"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.reject(target)
        runCurrent()

        vm.undoReject()
        runCurrent()

        val state = vm.uiState.value
        assertEquals("无法撤销：账单已超过 5 分钟保留窗口，或已被清理。", state.message)
        assertNull(state.undoableExpense, "404 means window dead; don't restore banner")
    }

    @Test
    fun undoRejectTransientNetworkErrorRestoresBannerForRetry() = review {
        // V7 contract: IOException / 5xx / unknown errors leave the
        // server-side 5-min window open — banner must come BACK so the
        // user can retry. Distinct from 404 (V5) which clears for good.
        val target = expense(id = 500L)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectResponder = { Result.success(target) }
        fake.undoRejectResponder = {
            Result.failure(RepositoryException("网络断了。", errorCode = null))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.reject(target)
        runCurrent()

        vm.undoReject()
        runCurrent()

        val state = vm.uiState.value
        val restored = assertNotNull(state.undoableExpense, "transient failure restores banner for retry")
        assertEquals(500L, restored.id)
        assertEquals("网络断了。", state.message)
        assertFalse(state.actionInProgressIds.contains(500L), "retry must not stay action-in-progress")
    }

    @Test
    fun ignoreDuplicateRemovesItemWithoutSeedingUndoBanner() = review {
        // V14 de facto behavior change contract.
        //
        // Pre-fork, `onIgnoreDuplicate` was routed through `reject()` —
        // not an intentional design, just a PendingRoute shortcut that
        // reused the same VM method. That shortcut was nevertheless
        // user-visible: 忽略重复 inherited reject()'s row removal +
        // sheet close + 撤销 banner + "已删除" message.
        //
        // Post-fork, `ignoreDuplicate()` splits off as its own VM
        // method. This test pins what stayed vs. what intentionally
        // changed:
        //   - PRESERVED from reject (row disposition unchanged):
        //       * row removed from pending list
        //       * duplicate sheet closes
        //       * same backend call (rejectExpenseAllowingOffline)
        //   - INTENTIONALLY CHANGED (UX wording / affordance):
        //       * NO 撤销 banner (user wasn't trying to delete)
        //       * message "已忽略重复" (not "已删除")
        val target = expense(id = 600L, duplicateStatus = "suspected")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectResponder = { Result.success(target) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openDuplicateAction(target)
        vm.ignoreDuplicate(target)
        runCurrent()

        val state = vm.uiState.value
        // — preserved-from-reject —
        assertTrue(state.items.isEmpty(), "PRESERVED: row leaves pending list (was true under reject shortcut)")
        assertEquals(PendingSheet.None, state.activeSheet, "PRESERVED: duplicate sheet closes")
        assertEquals(1, fake.rejectCalls, "PRESERVED: same backend call (rejectExpenseAllowingOffline)")
        assertFalse(state.actionInProgressIds.contains(600L), "PRESERVED: in-progress cleared")
        // — intentionally changed —
        assertNull(state.undoableExpense, "CHANGED: no 撤销 banner (wasn't a delete from user intent)")
        assertEquals("已忽略重复", state.message, "CHANGED: wording matches 忽略 intent, not 删除")
    }

    @Test
    fun ignoreDuplicateQueuedOfflinePreservesRowDispositionWithOfflineWording() = review {
        // Parallel to ignoreDuplicateRemovesItemWithoutSeedingUndoBanner
        // but exercising the Queued (offline) outcome. Same preserved-vs-
        // changed split: row leaves pending optimistically, sheet
        // closes, NO banner, message reads "已离线忽略，联网后同步".
        val target = expense(id = 601L, duplicateStatus = "suspected")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectOfflineResponder = {
            Result.success(
                com.ticketbox.data.repository.ExpenseStateOutcome.Queued(target.copy(status = "rejected")),
            )
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openDuplicateAction(target)
        vm.ignoreDuplicate(target)
        runCurrent()

        val state = vm.uiState.value
        assertTrue(state.items.isEmpty(), "PRESERVED: optimistic removal even in Queued branch")
        assertEquals(PendingSheet.None, state.activeSheet)
        assertNull(state.undoableExpense, "Queued ignoreDuplicate also doesn't seed banner")
        assertEquals("已离线忽略，联网后同步", state.message)
    }

    @Test
    fun confirmDismissesPriorUndoableBanner() = review {
        // V6 contract: moving to another action (confirm here) clears
        // the prior 撤销 banner so the new "已确认入账" message doesn't
        // sit alongside a stale undo affordance.
        val a = expense(id = 700L)
        val b = expense(id = 701L, amountCents = 100L, merchant = "M")
        val fake = FakeReviewActions(pending = listOf(a, b))
        fake.rejectResponder = { Result.success(a) }
        fake.confirmResponder = { Result.success(b.copy(status = "confirmed")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.reject(a)
        runCurrent()
        assertNotNull(vm.uiState.value.undoableExpense, "banner seeded after reject")

        vm.confirm(b)
        runCurrent()

        val state = vm.uiState.value
        assertNull(state.undoableExpense, "confirm clears prior banner")
        assertEquals("已确认入账", state.message)
    }

    @Test
    fun undoBannerAutoDismissesAfterFiveSeconds() = review {
        // V2 / Sweep#1 contract: 5s timer is owned by the VM, not a
        // Compose LaunchedEffect — so it fires reliably regardless of
        // Composition lifecycle (tab switches / NavHost pops). Advance
        // virtual time past 5s; banner must be cleared.
        val target = expense(id = 800L)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectResponder = { Result.success(target) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.reject(target)
        runCurrent()
        assertNotNull(vm.uiState.value.undoableExpense)

        advanceTimeBy(5_001)
        runCurrent()

        assertNull(vm.uiState.value.undoableExpense, "5s timer must auto-dismiss")
    }

    @Test
    fun viewerDemotionMidBannerClearsUndoableExpense() = review {
        // V11 contract: when the user is demoted to viewer mid-banner,
        // blockReadOnlyWrite() must tear down undoableExpense and the
        // timer — otherwise the banner sits as a dead affordance and
        // each tap loops the read-only toast.
        val target = expense(id = 900L)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectResponder = { Result.success(target) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.reject(target)
        runCurrent()
        assertNotNull(vm.uiState.value.undoableExpense)

        // Backend demoted user — next write attempt should clear the
        // banner via blockReadOnlyWrite's cleanup.
        fake.canModifyLedgerFlag = false

        vm.undoReject()
        runCurrent()

        val state = vm.uiState.value
        assertNull(state.undoableExpense, "demoted user's banner must clear")
        assertEquals(READ_ONLY_LEDGER_MESSAGE, state.message)
    }
}
