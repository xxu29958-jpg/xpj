package com.ticketbox.data.repository

import android.net.Uri
import com.ticketbox.data.local.BackgroundImageStore
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

interface BackgroundImageRepository {
    suspend fun importImage(uri: Uri): String
    suspend fun discardImage(path: String): Boolean
}

class LocalBackgroundImageRepository(private val store: BackgroundImageStore) : BackgroundImageRepository {
    override suspend fun importImage(uri: Uri): String = withContext(Dispatchers.IO) {
        store.copyPickedImageToPrivateStorage(uri)
    }

    override suspend fun discardImage(path: String): Boolean = withContext(Dispatchers.IO) {
        try {
            store.deleteCustomBackground(path)
        } catch (_: IOException) {
            false
        }
    }
}
