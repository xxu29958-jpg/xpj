package com.ticketbox.widget

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ManualEntryTemplate
import com.ticketbox.data.repository.ManualEntryTemplateStore
import com.ticketbox.data.repository.UploadBatchRequest
import com.ticketbox.ui.navigation.LaunchAction
import com.ticketbox.ui.navigation.LaunchActionState
import com.ticketbox.ui.navigation.LaunchIntentRequest
import com.ticketbox.ui.navigation.cancelPendingUploadSelection
import com.ticketbox.ui.navigation.pendingUploadSource
import com.ticketbox.ui.navigation.releaseUploadSourceGrants
import com.ticketbox.upload.ReceiptCaptureStore
import java.util.UUID
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class WidgetInputConnectedTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun savedTemplatesReopenInTheirOriginalLedgerAndUpdateById() {
        val binding = LogicalSessionBinding("https://example.test", UUID.randomUUID().toString(), UUID.randomUUID().toString(), "a", "b")
        val store = ManualEntryTemplateStore(context, binding)
        val template = ManualEntryTemplate(UUID.randomUUID().toString(), "早餐", 1250, "CNY", "餐饮", "豆浆")
        try {
            store.save(template)
            assertEquals(listOf(template), ManualEntryTemplateStore(context, binding.copy(sessionGeneration = "renewed")).read())
            assertTrue(ManualEntryTemplateStore(context, binding.copy(ledgerId = "other-ledger")).read().isEmpty())
            assertTrue(ManualEntryTemplateStore(context, binding.copy(ownerKey = "other-account")).read().isEmpty())
            store.save(template.copy(amountMinor = 1800))
            assertEquals(1, store.read().size)
            assertEquals(1800L, store.read().single().amountMinor)
        } finally { store.remove(template.id) }
        assertTrue(store.read().isEmpty())
    }

    @Test fun cameraOriginalSurvivesRecreationAndOnlyReleasesAfterDurableRoomAcceptance() = runBlocking {
        val fixture = ExpenseCorrectionConnectedFixture(context)
        val capture = ReceiptCaptureStore(context)
        val id = UUID.randomUUID().toString()
        val uri = capture.create(id)
        try {
            fixture.reopen()
            writePhoto(uri)
            val binding = requireNotNull(fixture.uploadIntents.currentUploadBinding())
            val selection = LaunchIntentRequest.ShareImages(id, listOf(uri.toString())).apply { freezeBinding(binding) }
            val original = LaunchActionState().apply { post(LaunchAction.UploadSharedImages(selection)); retryUpload() }
            assertTrue(original.beginUpload(requireNotNull(original.pendingUpload), binding))
            val restored = LaunchActionState.restore(original.snapshot())
            assertTrue(restored.awaitingUploadRetry)
            assertTrue(capture.hasPhoto(uri))
            assertEquals(binding, restored.pendingUpload?.selection?.expectedBinding)
            restored.retryUpload()
            val action = requireNotNull(restored.pendingUpload)
            assertTrue(restored.beginUpload(action, binding))
            val accepted = fixture.uploadIntents.acceptUploadBatch(UploadBatchRequest(id, selection.uris, binding,
                selection.timezone, pendingUploadSource(context))).getOrThrow()
            assertEquals(1, accepted.rowIds.size)
            restored.finishUpload(action, accepted = true)
            releaseUploadSourceGrants(context, restored, selection)
            assertFalse(capture.hasPhoto(uri))
            fixture.reopen()
            val row = fixture.uploadIntents.observeUploadIntents().first { it.uploads.isNotEmpty() }.uploads.single()
            assertEquals(accepted.rowIds.single(), row.row.id)
            assertNotNull(row.payload?.file)
            val record = fixture.outbox.enqueue(PendingMutationType.PatchExpense, "expense:40", "{}", 1)
            val status = fixture.outbox.observeStatus().first()
            assertEquals(2, status.queueDepth)
            assertEquals(setOf(record, row.row.id), status.queuedRows.map { it.id }.toSet())
            fixture.switchLedger()
            assertEquals(0, fixture.outbox.observeStatus().first().queueDepth)
        } finally { capture.release(uri); fixture.close() }
    }

    @Test fun cancelledCaptureReleasesOnlyItsOwnFileAndChangedLedgerCannotAdoptIt() = runBlocking {
        val fixture = ExpenseCorrectionConnectedFixture(context)
        val capture = ReceiptCaptureStore(context)
        val id = UUID.randomUUID().toString()
        val uri = capture.create(id)
        try {
            fixture.reopen()
            writePhoto(uri)
            capture.release(Uri.parse(uri.toString().replace(context.packageName, "other.application")))
            assertTrue(capture.hasPhoto(uri))
            val binding = requireNotNull(fixture.uploadIntents.currentUploadBinding())
            val selection = LaunchIntentRequest.ShareImages(id, listOf(uri.toString())).apply { freezeBinding(binding) }
            fixture.switchLedger()
            assertTrue(fixture.uploadIntents.acceptUploadBatch(UploadBatchRequest(id, selection.uris, binding,
                selection.timezone, pendingUploadSource(context))).isFailure)
            assertTrue(capture.hasPhoto(uri))
            val state = LaunchActionState().apply { post(LaunchAction.UploadSharedImages(selection)) }
            cancelPendingUploadSelection(context, state)
            assertFalse(capture.hasPhoto(uri))
            assertNull(state.pendingUpload)
        } finally { capture.release(uri); fixture.close() }
    }

    private fun writePhoto(uri: Uri) {
        val photo = Bitmap.createBitmap(32, 24, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.WHITE) }
        context.contentResolver.openOutputStream(uri).use { assertTrue(photo.compress(Bitmap.CompressFormat.JPEG, 95, requireNotNull(it))) }
        photo.recycle()
    }
}
