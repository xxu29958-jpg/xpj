package com.ticketbox.data.repository

import android.content.Context
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.domain.model.CurrencyCode
import java.security.MessageDigest
import java.util.UUID

data class ManualEntryTemplate(
    val id: String,
    val name: String,
    val amountMinor: Long,
    val currencyCode: String,
    val category: String,
    val note: String,
) {
    fun validated(): ManualEntryTemplate = apply {
        require(UUID.fromString(id).toString() == id)
        require(name.isNotBlank() && category.isNotBlank() && amountMinor >= 0)
        require(CurrencyCode.fromStorageKeyOrNull(currencyCode) != null)
    }
}

/** Local reusable input, not a financial record. Session renewals retain templates; other owners/ledgers do not. */
internal fun templateStorageKey(binding: LogicalSessionBinding): String = MessageDigest.getInstance("SHA-256")
    .digest("${binding.ownerKey}\u0000${binding.ledgerId}".toByteArray(Charsets.UTF_8))
    .joinToString("") { "%02x".format(it) }

internal class ManualEntryTemplateStore(context: Context, binding: LogicalSessionBinding) {
    private val preferences = context.getSharedPreferences("manual_entry_templates", Context.MODE_PRIVATE)
    private val key = templateStorageKey(binding)
    private val adapter = Moshi.Builder().addLast(KotlinJsonAdapterFactory()).build()
        .adapter<List<ManualEntryTemplate>>(Types.newParameterizedType(List::class.java, ManualEntryTemplate::class.java))

    fun read(): List<ManualEntryTemplate> {
        val json = preferences.getString(key, null) ?: return emptyList()
        val entries = requireNotNull(adapter.fromJson(json))
        entries.forEach { it.validated() }
        require(entries.distinctBy { it.id }.size == entries.size)
        return entries
    }

    fun save(entry: ManualEntryTemplate) {
        val entries = read().filterNot { it.id == entry.id } + entry.validated()
        check(preferences.edit().putString(key, adapter.toJson(entries)).commit())
    }

    fun remove(id: String) {
        check(preferences.edit().putString(key, adapter.toJson(read().filterNot { it.id == id })).commit())
    }
}
