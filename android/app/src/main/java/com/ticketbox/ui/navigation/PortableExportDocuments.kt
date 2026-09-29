package com.ticketbox.ui.navigation

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.viewmodel.PortableExportDestination
import java.io.OutputStream

/** Only ACTION_CREATE_DOCUMENT results owned by unfinished downloads enter this journal. */
internal class PortableExportDocuments(context: Context, private val active: MutableSet<String> = activeDocuments) {
    private val resolver = context.applicationContext.contentResolver
    private val unavailableMessage = context.getString(R.string.portable_export_destination_unavailable)
    private val preferences = context.applicationContext.getSharedPreferences("ticketbox_portable_exports", Context.MODE_PRIVATE)

    fun document(uri: Uri): PortableExportDestination = object : PortableExportDestination {
        override fun prepare() {
            synchronized(active) {
                val entries = pending() + uri.toString()
                check(preferences.edit().putStringSet(PENDING, entries).commit()) { "Cannot record the new export destination" }
                active += uri.toString()
            }
            try { resolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_WRITE_URI_PERMISSION) }
            catch (_: SecurityException) { /* Temporary access still permits the foreground save. */ }
        }

        override fun open(): OutputStream = try {
            resolver.openOutputStream(uri, "wt") ?: throw RepositoryException(unavailableMessage)
        } catch (error: SecurityException) {
            throw RepositoryException(unavailableMessage, cause = error)
        }

        override fun complete() = forget(uri)
        override fun discard(): Boolean = discardDocument(uri)
    }

    /** A new process has no active copies; reopening this screen in the same process must preserve them. */
    fun recoverInterrupted(): Boolean? {
        val interrupted = synchronized(active) { pending() - active }
        if (interrupted.isEmpty()) return null
        return interrupted.map { runCatching { discardDocument(Uri.parse(it)) }.getOrDefault(false) }.all { it }
    }

    private fun discardDocument(uri: Uri): Boolean = try {
        if (DocumentsContract.deleteDocument(resolver, uri)) {
            forget(uri)
            true
        } else false
    } finally {
        synchronized(active) { active -= uri.toString() }
    }

    private fun forget(uri: Uri) {
        synchronized(active) {
            check(preferences.edit().putStringSet(PENDING, pending() - uri.toString()).commit()) {
                "Cannot finish the export destination record"
            }
            active -= uri.toString()
        }
        try { resolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_WRITE_URI_PERMISSION) }
        catch (_: SecurityException) { /* This provider may only grant temporary access. */ }
    }

    private fun pending(): Set<String> = preferences.getStringSet(PENDING, emptySet()).orEmpty().toSet()

    private companion object {
        const val PENDING = "unfinished_documents"
        val activeDocuments = mutableSetOf<String>()
    }
}
