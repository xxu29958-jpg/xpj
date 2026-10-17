package com.ticketbox.data.repository

import android.net.Uri
import com.ticketbox.data.local.BackgroundImageStore
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

interface BackgroundImageRepository {
    suspend fun importImage(uri: Uri): String
    suspend fun discardImage(path: String): Boolean

    /** Releases orphaned candidates older than [startedAt]; the applied image is always kept. */
    suspend fun discardStale(keep: String?, startedAt: Long) = Unit
}

class LocalBackgroundImageRepository(private val store: BackgroundImageStore) : BackgroundImageRepository {
    override suspend fun importImage(uri: Uri): String = withContext(Dispatchers.IO) {
        store.copyPickedImageToPrivateStorage(uri)
    }

    override suspend fun discardStale(keep: String?, startedAt: Long) {
        withContext(Dispatchers.IO) {
            try {
                store.deleteStaleExcept(keep, startedAt)
            } catch (_: IOException) {
                // A sweep that cannot list the directory leaves files for the next visit.
            }
        }
    }

    override suspend fun discardImage(path: String): Boolean = withContext(Dispatchers.IO) {
        try {
            store.deleteCustomBackground(path)
        } catch (_: IOException) {
            false
        }
    }
}
