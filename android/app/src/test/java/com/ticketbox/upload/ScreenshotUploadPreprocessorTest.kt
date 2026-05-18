package com.ticketbox.upload

import java.io.ByteArrayInputStream
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertNull

class ScreenshotUploadPreprocessorTest {
    @Test
    fun boundedReadRejectsContentBeyondLimit() {
        val source = ByteArrayInputStream(byteArrayOf(1, 2, 3, 4))

        assertNull(source.readBytesWithLimit(3))
    }

    @Test
    fun boundedReadReturnsContentWithinLimit() {
        val bytes = byteArrayOf(1, 2, 3)

        assertContentEquals(bytes, ByteArrayInputStream(bytes).readBytesWithLimit(3))
    }
}
