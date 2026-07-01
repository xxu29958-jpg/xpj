package com.ticketbox.ui.screens

import kotlin.test.Test
import kotlin.test.assertEquals

class TodayNextActionTest {
    @Test
    fun readOnlyPendingShowsReviewInsteadOfWriteAction() {
        val action = todayNextAction(
            pendingCount = 3,
            missingAmountCount = 2,
            duplicateCount = 1,
            readyToConfirmCount = 1,
            readOnly = true,
        )

        assertEquals(TodayNextAction.ReviewPending, action)
    }

    @Test
    fun readOnlyWithoutPendingOpensLedger() {
        val action = todayNextAction(
            pendingCount = 0,
            missingAmountCount = 0,
            duplicateCount = 0,
            readyToConfirmCount = 0,
            readOnly = true,
        )

        assertEquals(TodayNextAction.OpenLedger, action)
    }

    @Test
    fun missingAmountWinsOverDuplicateAndReady() {
        val action = todayNextAction(
            pendingCount = 5,
            missingAmountCount = 1,
            duplicateCount = 1,
            readyToConfirmCount = 3,
            readOnly = false,
        )

        assertEquals(TodayNextAction.MissingAmount, action)
    }

    @Test
    fun duplicateWinsBeforeReadyWork() {
        val action = todayNextAction(
            pendingCount = 4,
            missingAmountCount = 0,
            duplicateCount = 1,
            readyToConfirmCount = 3,
            readOnly = false,
        )

        assertEquals(TodayNextAction.Duplicate, action)
    }

    @Test
    fun readyWorkBecomesConfirmAction() {
        val action = todayNextAction(
            pendingCount = 3,
            missingAmountCount = 0,
            duplicateCount = 0,
            readyToConfirmCount = 3,
            readOnly = false,
        )

        assertEquals(TodayNextAction.Ready, action)
    }

    @Test
    fun emptyWritableDeskPromptsUpload() {
        val action = todayNextAction(
            pendingCount = 0,
            missingAmountCount = 0,
            duplicateCount = 0,
            readyToConfirmCount = 0,
            readOnly = false,
        )

        assertEquals(TodayNextAction.UploadReceipt, action)
    }
}
