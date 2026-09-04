package com.ticketbox.viewmodel

import android.net.Uri
import com.ticketbox.data.repository.BackgroundImageRepository

internal class FakeBackgroundImages : BackgroundImageRepository {
    val discarded = mutableListOf<String>()

    override suspend fun importImage(uri: Uri): String = error("This test does not pick images")

    override suspend fun discardImage(path: String): Boolean {
        discarded += path
        return true
    }
}
