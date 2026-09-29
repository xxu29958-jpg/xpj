package com.ticketbox.ui.navigation

import android.app.Application
import android.content.Context
import android.content.pm.ProviderInfo
import android.database.MatrixCursor
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import android.provider.DocumentsProvider
import java.io.File
import java.io.IOException
import java.nio.file.Files
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
class PortableExportDocumentsTest {
    private val context: Context get() = RuntimeEnvironment.getApplication()
    private lateinit var directory: File
    private lateinit var provider: ExportDocumentsProvider
    private val uri = DocumentsContract.buildDocumentUri("portable.test", "new.zip")

    @BeforeTest fun setUp() {
        directory = Files.createTempDirectory("portable-system-documents").toFile()
        context.getSharedPreferences("ticketbox_portable_exports", Context.MODE_PRIVATE).edit().clear().commit()
        provider = ExportDocumentsProvider(directory).also {
            it.attachInfo(context, ProviderInfo().apply {
                authority = "portable.test"
                exported = true
                grantUriPermissions = true
                readPermission = "android.permission.MANAGE_DOCUMENTS"
                writePermission = "android.permission.MANAGE_DOCUMENTS"
            })
            ShadowContentResolver.registerProviderInternal("portable.test", it)
        }
    }

    @AfterTest fun cleanUp() { directory.deleteRecursively() }

    @Test fun processInterruptionRemovesOnlyTheNewPartialAndKeepsPreviouslySavedFiles() {
        val prior = File(directory, "previous.zip").apply { writeText("previous complete package") }
        val firstProcess = PortableExportDocuments(context, mutableSetOf())
        val document = firstProcess.document(uri)
        document.prepare()
        document.open().use { it.write(byteArrayOf(80, 75, 3, 4)) }
        // No completion or cancellation callback runs when the process dies.
        val nextProcess = PortableExportDocuments(context, mutableSetOf())
        assertEquals(true, nextProcess.recoverInterrupted())
        assertFalse(File(directory, "new.zip").exists())
        assertEquals("previous complete package", prior.readText())
        assertNull(nextProcess.recoverInterrupted())
    }

    @Test fun screenReentryPreservesTheActiveCopyAndCompletionRemovesItFromRestartCleanup() {
        val activeInProcess = mutableSetOf<String>()
        val document = PortableExportDocuments(context, activeInProcess).document(uri)
        document.prepare()
        document.open().use { it.write("complete package".toByteArray()) }
        assertNull(PortableExportDocuments(context, activeInProcess).recoverInterrupted())
        document.complete()
        assertNull(PortableExportDocuments(context, mutableSetOf()).recoverInterrupted())
        assertEquals("complete package", File(directory, "new.zip").readText())
    }

    @Test fun providerRefusalKeepsTheUnfinishedRecordAndReportsFailureUntilItCanBeRemoved() {
        val document = PortableExportDocuments(context, mutableSetOf()).document(uri)
        document.prepare()
        document.open().use { it.write(80) }
        provider.refuseDelete = true
        val restarted = PortableExportDocuments(context, mutableSetOf())
        assertEquals(false, restarted.recoverInterrupted())
        assertTrue(File(directory, "new.zip").exists())
        provider.refuseDelete = false
        assertEquals(true, restarted.recoverInterrupted())
        assertFalse(File(directory, "new.zip").exists())
    }
}

private class ExportDocumentsProvider(private val directory: File) : DocumentsProvider() {
    var refuseDelete = false
    override fun onCreate() = true
    override fun queryRoots(projection: Array<out String>?) = MatrixCursor(emptyArray())
    override fun queryDocument(documentId: String?, projection: Array<out String>?) = MatrixCursor(emptyArray())
    override fun queryChildDocuments(parentDocumentId: String?, projection: Array<out String>?, sortOrder: String?) =
        MatrixCursor(emptyArray())
    override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor =
        ParcelFileDescriptor.open(File(directory, documentId), ParcelFileDescriptor.parseMode(mode))
    override fun deleteDocument(documentId: String) {
        if (refuseDelete || !File(directory, documentId).delete()) throw IOException("Provider refused deletion")
    }
}
