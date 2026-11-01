package com.ticketbox.widget

import android.content.Context
import com.ticketbox.security.LocalSessionVersion

/** Display consent only. Financial data stays in the existing repository cache. */
internal class WidgetPreferences(context: Context) {
    private val preferences = context.getSharedPreferences("home_widgets", Context.MODE_PRIVATE)

    fun allowsSummary(id: Int, version: LocalSessionVersion?): Boolean =
        version != null && preferences.getString("summary.$id", null) == consentKey(version)

    fun save(id: Int, version: LocalSessionVersion?) {
        preferences.edit().apply {
            if (version == null) remove("summary.$id") else putString("summary.$id", consentKey(version))
        }.apply()
    }

    fun remove(ids: IntArray) {
        preferences.edit().apply { ids.forEach { remove("summary.$it") } }.apply()
    }

    private fun consentKey(version: LocalSessionVersion): String =
        "${version.sessionGeneration}:${version.bindingRevision}"
}
