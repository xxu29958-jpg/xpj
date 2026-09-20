package com.ticketbox.data.repository

import okio.ByteString.Companion.toByteString
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class OriginalMediaEvidenceTest {
    @Test fun onlyStrongEtagMatchingActuallyReceivedBytesCanBeReviewed() {
        val bytes = "reviewed original".encodeToByteArray()
        val digest = bytes.toByteString().sha256().hex()
        assertEquals(digest, reviewedOriginalDigest(bytes, "\"$digest\""))
        assertNull(reviewedOriginalDigest(bytes, "W/\"$digest\""))
        assertNull(reviewedOriginalDigest("different file".encodeToByteArray(), "\"$digest\""))
        assertNull(reviewedOriginalDigest(bytes, null))
        assertNull(reviewedOriginalDigest(bytes, "\"legacy-stat-etag\""))
    }
}
