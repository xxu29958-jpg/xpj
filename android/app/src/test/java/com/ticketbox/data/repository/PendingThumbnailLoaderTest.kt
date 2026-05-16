package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertSame
import kotlin.test.assertTrue

class PendingThumbnailLoaderTest {
    @Test
    fun loadMissingSkipsItemsWithoutImagesAndExistingThumbnails() = runTest {
        val existingImage = image("existing")
        val missingImage = image("loaded")
        val actions = ThumbnailFakeReviewActions(
            thumbnails = mapOf(2L to missingImage),
        )
        val loader = PendingThumbnailLoader(actions)

        val loaded = loader.loadMissing(
            expenses = listOf(
                expense(id = 1L, imagePath = null),
                expense(id = 2L, imagePath = "uploads/two.jpg"),
                expense(id = 3L, imagePath = "uploads/three.jpg"),
            ),
            existing = mapOf(3L to existingImage),
        )

        assertEquals(listOf(2L), actions.thumbnailCalls)
        assertEquals(setOf(2L), loaded.keys)
        assertSame(missingImage, loaded[2L])
    }

    @Test
    fun loadMissingDropsFailedThumbnailRequests() = runTest {
        val actions = ThumbnailFakeReviewActions(
            thumbnails = mapOf(1L to image("one")),
            failures = setOf(2L),
        )
        val loader = PendingThumbnailLoader(actions, concurrency = 2)

        val loaded = loader.loadMissing(
            expenses = listOf(
                expense(id = 1L, imagePath = "uploads/one.jpg"),
                expense(id = 2L, imagePath = "uploads/two.jpg"),
            ),
            existing = emptyMap(),
        )

        assertEquals(setOf(1L, 2L), actions.thumbnailCalls.toSet())
        assertEquals(setOf(1L), loaded.keys)
    }

    @Test
    fun loadMissingReturnsEmptyMapWhenNothingNeedsFetching() = runTest {
        val actions = ThumbnailFakeReviewActions()
        val loader = PendingThumbnailLoader(actions)

        val loaded = loader.loadMissing(
            expenses = listOf(expense(id = 1L, imagePath = null)),
            existing = emptyMap(),
        )

        assertTrue(loaded.isEmpty())
        assertTrue(actions.thumbnailCalls.isEmpty())
    }
}

private class ThumbnailFakeReviewActions(
    private val thumbnails: Map<Long, ProtectedImage> = emptyMap(),
    private val failures: Set<Long> = emptySet(),
) : PendingReviewActions {
    val thumbnailCalls = mutableListOf<Long>()

    override suspend fun fetchPending(): Result<List<Expense>> = Result.success(emptyList())

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> {
        thumbnailCalls += id
        if (id in failures) {
            return Result.failure(IllegalStateException("missing thumbnail"))
        }
        return thumbnails[id]?.let { Result.success(it) }
            ?: Result.failure(IllegalStateException("unexpected thumbnail id $id"))
    }

    override suspend fun updateExpense(id: Long, draft: ExpenseDraft): Result<Expense> =
        Result.failure(IllegalStateException("not exercised"))

    override suspend fun confirmExpense(id: Long): Result<Expense> =
        Result.failure(IllegalStateException("not exercised"))

    override suspend fun rejectExpense(id: Long): Result<Expense> =
        Result.failure(IllegalStateException("not exercised"))

    override suspend fun markNotDuplicate(id: Long): Result<Expense> =
        Result.failure(IllegalStateException("not exercised"))

    override suspend fun categories(): Result<List<String>> = Result.success(emptyList())

    override suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long?,
        sourceSizeBytes: Long?,
    ): Result<Long> = Result.failure(IllegalStateException("not exercised"))
}

private fun image(label: String): ProtectedImage =
    ProtectedImage(bytes = label.encodeToByteArray(), contentType = "image/jpeg")

private fun expense(
    id: Long,
    imagePath: String?,
): Expense = Expense(
    id = id,
    publicId = "pub-$id",
    amountCents = 100L,
    merchant = "商家",
    category = "其他",
    note = null,
    source = "android",
    imagePath = imagePath,
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    confidence = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "pending",
    expenseTime = null,
    createdAt = "2026-05-01T00:00:00Z",
    updatedAt = "2026-05-01T00:00:00Z",
    confirmedAt = null,
    rejectedAt = null,
)
