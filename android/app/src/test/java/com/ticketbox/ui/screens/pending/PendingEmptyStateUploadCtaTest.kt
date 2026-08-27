package com.ticketbox.ui.screens.pending

import com.ticketbox.R
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PendingEmptyStateUploadCtaTest {
    @Test
    fun readOnlyQueueHasNoUploadCta() {
        assertNull(
            emptyPendingUploadCta(uploading = false, loading = false, readOnly = true),
        )
        assertNull(
            emptyPendingUploadCta(uploading = true, loading = false, readOnly = true),
        )
    }

    @Test
    fun idleEmptyQueueOffersAnEnabledUploadCta() {
        val cta = emptyPendingUploadCta(uploading = false, loading = false, readOnly = false)

        assertEquals(R.string.pending_top_cta_upload, cta?.labelRes)
        assertTrue(cta?.enabled == true)
    }

    @Test
    fun uploadingQueueDisablesTheCtaAndSwitchesLabel() {
        val cta = emptyPendingUploadCta(uploading = true, loading = false, readOnly = false)

        assertEquals(R.string.pending_top_cta_uploading, cta?.labelRes)
        assertFalse(cta?.enabled == true)
    }

    @Test
    fun loadingQueueKeepsUploadLabelButDisablesTheCta() {
        val cta = emptyPendingUploadCta(uploading = false, loading = true, readOnly = false)

        assertEquals(R.string.pending_top_cta_upload, cta?.labelRes)
        assertFalse(cta?.enabled == true)
    }
}
