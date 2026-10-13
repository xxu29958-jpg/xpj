package com.ticketbox.data.repository

import com.ticketbox.data.local.MerchantCreationInputDao
import com.ticketbox.data.local.MerchantCreationInputEntity

fun fakeMerchantDraftStore(beforeRemove: () -> Unit = {}): MerchantDraftStore = MerchantDraftStore(object : MerchantCreationInputDao {
    private val rows = mutableListOf<MerchantCreationInputEntity>()
    override suspend fun get(server: String, owner: String, ledger: String) =
        rows.filter { it.serverUrl == server && it.ownerKey == owner && it.ledgerId == ledger }

    override suspend fun put(input: MerchantCreationInputEntity) {
        rows.removeAll { it.serverUrl == input.serverUrl && it.ownerKey == input.ownerKey && it.ledgerId == input.ledgerId && it.kind == input.kind }
        rows += input
    }

    override suspend fun putAll(inputs: List<MerchantCreationInputEntity>) = inputs.forEach { put(it) }

    override suspend fun removeKeys(server: String, owner: String, ledger: String, keys: List<String>) {
        beforeRemove()
        rows.removeAll { it.serverUrl == server && it.ownerKey == owner && it.ledgerId == ledger && it.originalKey in keys }
    }

    override suspend fun remove(server: String, owner: String, ledger: String, kind: String, key: String) {
        beforeRemove()
        rows.removeAll { it.serverUrl == server && it.ownerKey == owner && it.ledgerId == ledger && it.kind == kind && it.originalKey == key }
    }
})
