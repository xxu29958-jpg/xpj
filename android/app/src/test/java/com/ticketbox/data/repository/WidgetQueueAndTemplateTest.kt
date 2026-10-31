package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.SyncQueueFilter
import com.ticketbox.ui.screens.settings.filteredQueue
import java.util.UUID
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class WidgetQueueAndTemplateTest {
    @Test fun templatesSurviveSessionRenewalButCannotCrossOwnersOrLedgers() {
        val binding = LogicalSessionBinding("https://example.test", "ledger-a", "owner-a", "session-a", "revision-a")
        assertEquals(templateStorageKey(binding), templateStorageKey(binding.copy(sessionGeneration = "session-b", bindingRevision = "revision-b")))
        assertNotEquals(templateStorageKey(binding), templateStorageKey(binding.copy(ownerKey = "owner-b")))
        assertNotEquals(templateStorageKey(binding), templateStorageKey(binding.copy(ledgerId = "ledger-b")))
    }

    @Test fun invalidTemplateMoneyAndCurrencyAreNotSavedAsUsableInput() {
        val template = ManualEntryTemplate(UUID.randomUUID().toString(), "早餐", 1250, "CNY", "餐饮", "豆浆")
        assertEquals(template, template.validated())
        listOf(template.copy(amountMinor = -1), template.copy(currencyCode = "UNKNOWN"), template.copy(name = " "))
            .forEach { assertThrows(IllegalArgumentException::class.java) { it.validated() } }
    }

    @Test fun queueCountsAndFiltersRetainOriginalRowsWhileSeparatingUploadsAndRecords() = runTest {
        val repository = testOutboxRepository(FakePendingMutationDao())
        val upload = repository.enqueue(PendingMutationType.UploadScreenshot, "upload_batch:${UUID.randomUUID()}", "{}", 0)
        val record = repository.enqueue(PendingMutationType.PatchExpense, "expense:10", "{}", 1)
        val failed = repository.enqueue(PendingMutationType.PatchExpense, "expense:20", "{}", 1)
        repository.markFailed(failed, "test rejection")
        val snapshot = repository.observeStatus().first()
        assertEquals(2, snapshot.queueDepth)
        assertEquals(setOf(upload, record), snapshot.queuedRows.map { it.id }.toSet())
        assertEquals(listOf(upload), snapshot.filteredQueue(SyncQueueFilter.Uploads).map { it.id })
        assertEquals(setOf(record, failed), snapshot.filteredQueue(SyncQueueFilter.Records).map { it.id }.toSet())
        assertEquals(listOf(failed), snapshot.filteredQueue(SyncQueueFilter.Failed).map { it.id })
    }
}
