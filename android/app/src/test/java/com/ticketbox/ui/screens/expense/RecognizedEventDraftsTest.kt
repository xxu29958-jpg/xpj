package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.RecognitionFieldCandidate
import com.ticketbox.domain.model.RecognitionTime
import com.ticketbox.domain.model.RecognitionTimeCandidate
import org.junit.Assert.assertEquals
import org.junit.Test

class RecognizedEventDraftsTest {
    @Test
    fun bundlesKeepSourceAndEventIdentityAndExcludeUnresolvedFields() {
        val amount = RecognitionFieldCandidate("amount_cents", "money", "2800", "第2笔 · 实付", "28.00", "原文", "payment",
            true, "fact", "receipt-fields-v6", "CNY", 2, "second", eventSelected = true)
        val merchant = amount.copy(field = "merchant", id = "merchant", value = "青禾超市", role = "merchant")
        val clock = RecognitionTimeCandidate("clock", "图片 · 第2笔 · 支付时间", "原文", "09:20", "2026-10-21T09:20",
            "minute", "Asia/Shanghai", 28800, true, "fact", "image", "receipt-fields-v6", eventId = "second", eventSelected = true)
        val time = RecognitionTime("fact", "receipt-fields-v6", "ambiguous", listOf(
            clock.copy(evidencePublicId = "capture", source = "notification"), clock.copy(eventId = "first"), clock))
        val fields = listOf(amount, merchant, amount.copy(id = "balance", value = "90000", role = "balance", eventSelected = false))
        val selected = recognizedEventDrafts(fields, time).single()
        assertEquals(listOf(amount, merchant), selected.fields)
        assertEquals(clock, selected.time)
        assertEquals(null, recognizedEventDrafts(fields, time.copy(candidates = listOf(clock.copy(requiresYear = true)))).single().time)
        assertEquals(emptyList<RecognizedEventDraft>(), recognizedEventDrafts(fields.map { it.copy(eventSelected = false) }, time))
    }
}
