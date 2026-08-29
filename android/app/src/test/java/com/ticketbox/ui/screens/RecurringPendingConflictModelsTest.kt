package com.ticketbox.ui.screens

import com.ticketbox.R
import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringPendingKind
import com.ticketbox.data.repository.RecurringPendingState
import com.ticketbox.ui.screens.recurring.RecurringConflictAction
import com.ticketbox.ui.screens.recurring.RecurringPendingChange
import com.ticketbox.ui.screens.recurring.recurringPendingKindLabelRes
import com.ticketbox.ui.screens.recurring.recurringRowCapabilities
import com.ticketbox.ui.screens.recurring.resolveRecurringDuplicateConflict
import com.ticketbox.ui.screens.recurring.resolveRecurringPendingRow
import com.ticketbox.viewmodel.RecurringDuplicateConflict
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** 待同步 intent 呈现（三态 / 基线解析）、行能力（archived 可恢复不可编辑）与撞单解决。 */
class RecurringPendingConflictModelsTest {

    @Test
    fun archivedRowIsRestorableButNeverEditable() {
        val archived = recurringRowCapabilities("archived")
        assertEquals(false, archived.editable)
        assertEquals(false, archived.lifecycleActions)
        assertEquals(true, archived.restorable)
        val active = recurringRowCapabilities("active")
        assertEquals(true, active.editable)
        assertEquals(true, active.lifecycleActions)
        assertEquals(false, active.restorable)
        val paused = recurringRowCapabilities("paused")
        assertEquals(true, paused.editable)
        assertEquals(true, paused.lifecycleActions)
        val unknown = recurringRowCapabilities("whatever")
        assertEquals(false, unknown.editable)
        assertEquals(false, unknown.lifecycleActions)
        assertEquals(false, unknown.restorable)
    }

    @Test
    fun pendingKindLabelsMapToCopy() {
        assertEquals(R.string.recurring_pending_kind_create, recurringPendingKindLabelRes(RecurringPendingKind.CREATE))
        assertEquals(R.string.recurring_pending_kind_update, recurringPendingKindLabelRes(RecurringPendingKind.UPDATE))
    }

    @Test
    fun pendingCreateRowShowsNewDraftAsWaiting() {
        val model = resolveRecurringPendingRow(
            intent = RecurringPendingIntent(
                kind = RecurringPendingKind.CREATE,
                targetId = "local-1",
                idempotencyKey = "key-1",
                merchant = "宽带",
                baselineAmountCents = 120_00,
            ),
            items = emptyList(),
        )
        assertEquals("宽带", model.title)
        assertEquals(120_00, model.amountCents)
        assertEquals(R.string.recurring_pending_kind_create, model.kindLabelRes)
        assertEquals(R.string.recurring_pending_state_waiting, model.stateLabelRes)
        assertNull(model.stateGuidanceRes)
        // CREATE 行本身就在展示新草稿，不再重复「改为 …」清单。
        assertEquals(emptyList(), model.changes)
    }

    @Test
    fun pendingUpdateRowResolvesBaselineFromPublishedItems() {
        val baseline = recurringItem { publicId = "p1"; merchant = "房租"; baselineAmountCents = 3000_00 }
        val model = resolveRecurringPendingRow(
            intent = RecurringPendingIntent(
                kind = RecurringPendingKind.UPDATE,
                targetId = "p1",
                idempotencyKey = "key-2",
                publicId = "p1",
                baselineAmountCents = 3500_00,
            ),
            items = listOf(baseline),
        )
        // UPDATE payload 只有 changed fields：名称从已发布基线解析，不伪称「未填写商家」。
        assertEquals("房租", model.title)
        assertEquals(3500_00, model.amountCents)
        assertEquals(R.string.recurring_pending_kind_update, model.kindLabelRes)
        assertEquals(listOf(RecurringPendingChange.AmountTo(3500_00)), model.changes)
    }

    @Test
    fun pendingUpdateRowWithoutBaselineUsesHonestFallback() {
        val model = resolveRecurringPendingRow(
            intent = RecurringPendingIntent(
                kind = RecurringPendingKind.UPDATE,
                targetId = "gone",
                idempotencyKey = "key-3",
                publicId = "gone",
                nextExpectedDateChanged = true,
                nextExpectedDate = null,
            ),
            items = emptyList(),
        )
        assertNull(model.title)
        assertEquals(R.string.recurring_pending_update_unknown, model.titleFallbackRes)
        assertNull(model.amountCents)
        assertEquals(listOf(RecurringPendingChange.DateCleared), model.changes)
    }

    @Test
    fun pendingConflictAndFailedCarryHonestStateAndGuidance() {
        val base = RecurringPendingIntent(
            kind = RecurringPendingKind.CREATE,
            targetId = "local-1",
            idempotencyKey = "key-1",
            merchant = "宽带",
        )
        val waiting = resolveRecurringPendingRow(base, emptyList())
        assertEquals(R.string.recurring_pending_state_waiting, waiting.stateLabelRes)
        assertNull(waiting.stateGuidanceRes)
        val conflict = resolveRecurringPendingRow(
            base.copy(state = RecurringPendingState.CONFLICT),
            emptyList(),
        )
        assertEquals(R.string.recurring_pending_state_conflict, conflict.stateLabelRes)
        assertEquals(R.string.recurring_pending_state_guidance, conflict.stateGuidanceRes)
        val failed = resolveRecurringPendingRow(
            base.copy(state = RecurringPendingState.FAILED),
            emptyList(),
        )
        assertEquals(R.string.recurring_pending_state_failed, failed.stateLabelRes)
        assertEquals(R.string.recurring_pending_state_guidance, failed.stateGuidanceRes)
    }

    @Test
    fun duplicateConflictResolvesActionFromRealItem() {
        val items = listOf(
            recurringItem { publicId = "p1"; status = "active"; merchant = "宽带"; rowVersion = 7L },
            recurringItem { publicId = "p2"; status = "archived"; merchant = "旧宽带"; rowVersion = 3L },
        )
        val active = resolveRecurringDuplicateConflict(
            RecurringDuplicateConflict(publicId = "p1", status = "active"),
            items,
        )
        assertEquals(RecurringConflictAction.EditExisting, active?.action)
        assertEquals("宽带", active?.merchant)
        assertEquals(7L, active?.rowVersion)
        val archived = resolveRecurringDuplicateConflict(
            RecurringDuplicateConflict(publicId = "p2", status = "archived"),
            items,
        )
        assertEquals(RecurringConflictAction.RestoreArchived, archived?.action)
        assertEquals(3L, archived?.rowVersion)
        // 列表里解析不到真实记录：不给按钮，只给刷新后查看的诚实文案。
        val missing = resolveRecurringDuplicateConflict(
            RecurringDuplicateConflict(publicId = "ghost", status = "paused"),
            items,
        )
        assertEquals(RecurringConflictAction.Unavailable, missing?.action)
        assertNull(missing?.merchant)
        assertNull(resolveRecurringDuplicateConflict(null, items))
    }
}
