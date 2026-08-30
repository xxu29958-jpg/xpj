package com.ticketbox.ui.screens

import com.ticketbox.R
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SheetValue
import com.ticketbox.data.repository.RecurringDateEdit
import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringPendingKind
import com.ticketbox.data.repository.RecurringPendingState
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.screens.recurring.RecurringConflictAction
import com.ticketbox.ui.screens.recurring.RecurringEditField
import com.ticketbox.ui.screens.recurring.RecurringEditorRebase
import com.ticketbox.ui.screens.recurring.RecurringEditorRebaseDraft
import com.ticketbox.ui.screens.recurring.RecurringPendingChange
import com.ticketbox.ui.screens.recurring.RecurringRebaseStage
import com.ticketbox.ui.screens.recurring.RecurringRebaseUi
import com.ticketbox.ui.screens.recurring.RecurringOverlapComparison
import com.ticketbox.ui.screens.recurring.RecurringOverlapDraft
import com.ticketbox.ui.screens.recurring.RecurringOverlapValue
import com.ticketbox.ui.screens.recurring.RecurringSubmitSettle
import com.ticketbox.ui.screens.recurring.RecurringSubmitUi
import com.ticketbox.ui.screens.recurring.buildRecurringItemPatch
import com.ticketbox.ui.screens.recurring.newRecurringEditorSession
import com.ticketbox.ui.screens.recurring.rebaseRecurringEditorDraft
import com.ticketbox.ui.screens.recurring.recurringEditorDraftEnabled
import com.ticketbox.ui.screens.recurring.recurringEditorOwnerState
import com.ticketbox.ui.screens.recurring.recurringEditorSheetAllowsTransition
import com.ticketbox.ui.screens.recurring.recurringEditorSheetNeedsAttemptRescue
import com.ticketbox.ui.screens.recurring.recurringOverlapDisplayOwner
import com.ticketbox.ui.screens.recurring.recurringOverlapComparisons
import com.ticketbox.ui.screens.recurring.recurringPendingKindLabelRes
import com.ticketbox.ui.screens.recurring.recurringRowCapabilities
import com.ticketbox.ui.screens.recurring.recurringSubmitStep
import com.ticketbox.ui.screens.recurring.resolveRecurringDuplicateConflict
import com.ticketbox.ui.screens.recurring.resolveRecurringPendingRow
import com.ticketbox.viewmodel.RecurringDuplicateConflict
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringManualSaveFeedback
import com.ticketbox.viewmodel.RecurringManualSaveSettlement
import com.ticketbox.viewmodel.RecurringUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** 待同步 intent 呈现（三态 / 基线解析）、行能力（archived 可恢复不可编辑）与撞单解决。 */
@OptIn(ExperimentalMaterial3Api::class)
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
            ownerLoaded = true,
        )
        assertEquals(RecurringConflictAction.EditExisting, active?.action)
        assertEquals("宽带", active?.merchant)
        assertEquals(7L, active?.rowVersion)
        val archived = resolveRecurringDuplicateConflict(
            RecurringDuplicateConflict(publicId = "p2", status = "archived"),
            items,
            ownerLoaded = true,
        )
        assertEquals(RecurringConflictAction.RestoreArchived, archived?.action)
        assertEquals(3L, archived?.rowVersion)
        // 列表里解析不到真实记录：不给按钮，只给刷新后查看的诚实文案。
        val missing = resolveRecurringDuplicateConflict(
            RecurringDuplicateConflict(publicId = "ghost", status = "paused"),
            items,
            ownerLoaded = true,
        )
        assertEquals(RecurringConflictAction.Unavailable, missing?.action)
        assertNull(missing?.merchant)
        assertNull(resolveRecurringDuplicateConflict(null, items, ownerLoaded = true))

        val stale = resolveRecurringDuplicateConflict(
            RecurringDuplicateConflict(publicId = "p1", status = "archived"),
            items,
            ownerLoaded = false,
        )
        assertEquals("archived", stale?.status)
        assertEquals(RecurringConflictAction.Unavailable, stale?.action)
        assertNull(stale?.merchant)
        assertNull(stale?.rowVersion)
    }

    @Test
    fun conflictRebaseAdoptsUntouchedOwnerFieldsWithoutLosingUserIntent() {
        val stale = recurringItem {
            publicId = "p1"
            rowVersion = 1L
            baselineAmountCents = 3000_00
            nextExpectedDate = "2026-09-01"
        }
        val fresh = recurringItem {
            publicId = "p1"
            rowVersion = 2L
            baselineAmountCents = 3200_00
            nextExpectedDate = "2026-09-01"
        }

        val rebase = rebaseRecurringEditorDraft(
            previousBaseline = stale,
            freshOwner = fresh,
            draft = RecurringEditorRebaseDraft(
                merchant = stale.merchant,
                baselineAmountCents = stale.baselineAmountCents,
                nextExpectedDate = "2026-09-15",
            ),
        )
        val retryPatch = buildRecurringItemPatch(
            baseline = rebase.baseline,
            merchant = rebase.merchant,
            baselineAmountCents = rebase.baselineAmountCents,
            dateTouched = rebase.dateTouched,
            nextExpectedDate = rebase.nextExpectedDate,
        )

        assertEquals(3200_00, rebase.baselineAmountCents)
        assertNull(retryPatch?.baselineAmountCents, "an untouched remote amount must not be replayed")
        assertEquals(RecurringDateEdit.changed("2026-09-15"), retryPatch?.nextExpectedDate)
        assertEquals(emptySet(), rebase.overlappingFields)

        val overlapping = rebaseRecurringEditorDraft(
            previousBaseline = stale,
            freshOwner = fresh,
            draft = RecurringEditorRebaseDraft(
                merchant = stale.merchant,
                baselineAmountCents = 3100_00,
                nextExpectedDate = stale.nextExpectedDate,
            ),
        )
        assertEquals(setOf(RecurringEditField.Amount), overlapping.overlappingFields)

        assertSubsequentOwnerRefreshAdvancesOccBaseline(fresh, overlapping)

        assertEquals(false, recurringEditorDraftEnabled(awaiting = false, RecurringRebaseStage.LoadingOwner))
        assertEquals(false, recurringEditorDraftEnabled(awaiting = false, RecurringRebaseStage.OwnerUnavailable))
        assertEquals(true, recurringEditorDraftEnabled(awaiting = false, RecurringRebaseStage.Ready))
        assertEquals(false, recurringEditorDraftEnabled(awaiting = true, RecurringRebaseStage.Ready))
    }

    @Test
    fun savingSheetRejectsHiddenButAllowsVisibleTransitions() {
        val session = newRecurringEditorSession(baseline = null, currency = CurrencyCode.CNY)
        fun hiddenAllowed() = recurringEditorSheetAllowsTransition(
            session = session,
            manualSaveInFlight = false,
            targetValue = SheetValue.Hidden,
        )
        assertEquals(true, hiddenAllowed())
        session.submitUi = RecurringSubmitUi(attemptId = 1L, awaiting = true)
        assertEquals(
            false,
            hiddenAllowed(),
        )
        assertEquals(
            true,
            recurringEditorSheetNeedsAttemptRescue(
                awaiting = true,
                currentValue = SheetValue.Expanded,
                targetValue = SheetValue.Hidden,
            ),
        )
        assertEquals(
            true,
            recurringEditorSheetNeedsAttemptRescue(
                awaiting = true,
                currentValue = SheetValue.Hidden,
                targetValue = SheetValue.Hidden,
            ),
        )
        assertEquals(
            false,
            recurringEditorSheetNeedsAttemptRescue(
                awaiting = true,
                currentValue = SheetValue.Expanded,
                targetValue = SheetValue.Expanded,
            ),
        )
        assertEquals(
            true,
            recurringEditorSheetAllowsTransition(
                session = session,
                manualSaveInFlight = true,
                targetValue = SheetValue.Expanded,
            ),
        )
        session.submitUi = RecurringSubmitUi(attemptId = 1L, awaiting = false, error = "网络错误")
        assertEquals(true, hiddenAllowed())
        assertEquals(
            false,
            recurringEditorSheetNeedsAttemptRescue(
                awaiting = false,
                currentValue = SheetValue.Hidden,
                targetValue = SheetValue.Hidden,
            ),
        )
        // VM 侧在途同样锁 Hidden，与 session 无关。
        assertEquals(
            false,
            recurringEditorSheetAllowsTransition(
                session = session,
                manualSaveInFlight = true,
                targetValue = SheetValue.Hidden,
            ),
        )
    }

    @Test
    fun overlappingConflictCarriesCurrentAndDraftValuesForTheSurface() {
        val stale = recurringItem {
            merchant = "旧房租"
            baselineAmountCents = 3000_00
            rowVersion = 1L
        }
        val fresh = recurringItem {
            merchant = "当前房租"
            baselineAmountCents = 3200_00
            nextExpectedDate = "2026-09-20"
            rowVersion = 2L
        }

        assertEquals(fresh, recurringOverlapDisplayOwner(freshOwner = fresh, editingBaseline = stale))
        assertEquals(stale, recurringOverlapDisplayOwner(freshOwner = null, editingBaseline = stale))
        assertNull(recurringOverlapDisplayOwner(freshOwner = null, editingBaseline = null))

        val comparisons = recurringOverlapComparisons(
            freshOwner = fresh,
            overlappingFields = setOf(RecurringEditField.Amount, RecurringEditField.Date),
            draft = RecurringOverlapDraft(
                merchant = "我的房租",
                amountCents = 3100_00,
                amountText = "3100.00",
                nextExpectedDate = "2026-09-15",
            ),
        )

        assertEquals(
            listOf(
                RecurringOverlapValue.Amount(currentCents = 3200_00, draftCents = 3100_00),
                RecurringOverlapValue.Date(currentIso = "2026-09-20", draftIso = "2026-09-15"),
            ),
            comparisons.map(RecurringOverlapComparison::value),
        )
    }

    @Test
    fun submitSettlementRequiresExplicitMutationOutcome() {
        val inFlight = recurringSubmitStep(
            awaitingAttemptId = 7L,
            feedback = RecurringManualSaveFeedback(
                attemptId = 7L,
                settlement = RecurringManualSaveSettlement.InFlight,
            ),
        )
        assertNull(inFlight)
        val explicitSuccess = recurringSubmitStep(
            awaitingAttemptId = 7L,
            feedback = RecurringManualSaveFeedback(
                attemptId = 7L,
                settlement = RecurringManualSaveSettlement.Accepted,
            ),
        )
        assertEquals(RecurringSubmitSettle.Accepted, explicitSuccess)

        val settlement = recurringSubmitStep(
            awaitingAttemptId = 7L,
            feedback = RecurringManualSaveFeedback(
                attemptId = 7L,
                settlement = RecurringManualSaveSettlement.Failed,
            ),
        )
        assertEquals(
            RecurringSubmitSettle.Failure,
            settlement,
            "an unresolved conflict must never settle the editor as accepted",
        )

        val unrelatedDanger = recurringSubmitStep(
            awaitingAttemptId = 7L,
            feedback = RecurringManualSaveFeedback(
                attemptId = 8L,
                settlement = RecurringManualSaveSettlement.Failed,
            ),
        )
        assertNull(
            unrelatedDanger,
            "a refresh failure without manual-attempt ownership cannot settle the editor",
        )
    }
}

private fun assertSubsequentOwnerRefreshAdvancesOccBaseline(
    fresh: RecurringItem,
    overlapping: RecurringEditorRebase,
) {
    val session = newRecurringEditorSession(fresh, CurrencyCode.CNY).apply {
        amountText = "3100.00"
        submitUi = RecurringSubmitUi(attemptId = 42L)
        rebaseUi = RecurringRebaseUi(42L, overlapping.overlappingFields)
    }
    val newer = fresh.copy(rowVersion = 3L, baselineAmountCents = 3300_00)
    val ownerState = recurringEditorOwnerState(
        session = session,
        uiState = RecurringUiState(
            items = listOf(newer),
            itemsLoadState = RecurringListLoadState.Loaded,
            manualSaveFeedback = RecurringManualSaveFeedback(
                attemptId = 42L,
                settlement = RecurringManualSaveSettlement.Failed,
                requiresOwnerReload = true,
            ),
        ),
    )
    assertEquals(
        RecurringRebaseStage.LoadingOwner,
        ownerState.stage,
        "a newer displayed owner must advance the retry OCC baseline before submit",
    )

    val secondRebase = rebaseRecurringEditorDraft(
        previousBaseline = fresh,
        freshOwner = newer,
        draft = RecurringEditorRebaseDraft(
            merchant = overlapping.merchant,
            baselineAmountCents = overlapping.baselineAmountCents,
            nextExpectedDate = overlapping.nextExpectedDate,
            previousOverlappingFields = overlapping.overlappingFields,
        ),
    )
    assertEquals(3L, secondRebase.baseline.rowVersion)
    assertEquals(3100_00, secondRebase.baselineAmountCents)
    assertEquals(setOf(RecurringEditField.Amount), secondRebase.overlappingFields)

    val matchingOwner = newer.copy(rowVersion = 4L, baselineAmountCents = 3100_00)
    val resolvedRebase = rebaseRecurringEditorDraft(
        previousBaseline = newer,
        freshOwner = matchingOwner,
        draft = RecurringEditorRebaseDraft(
            merchant = secondRebase.merchant,
            baselineAmountCents = secondRebase.baselineAmountCents,
            nextExpectedDate = secondRebase.nextExpectedDate,
            previousOverlappingFields = secondRebase.overlappingFields,
        ),
    )
    assertEquals(emptySet(), resolvedRebase.overlappingFields)
}
