package com.ticketbox.data.repository

import com.ticketbox.data.local.MerchantCreationInputDao
import com.ticketbox.data.local.MerchantCreationInputEntity

fun fakeMerchantCreationDraftStore(beforeRemove: () -> Unit = {}): MerchantCreationDraftStore = MerchantCreationDraftStore(object : MerchantCreationInputDao {
    private val rows = mutableListOf<MerchantCreationInputEntity>()
    override suspend fun get(server: String, owner: String, ledger: String) =
        rows.filter { it.serverUrl == server && it.ownerKey == owner && it.ledgerId == ledger }

    override suspend fun put(input: MerchantCreationInputEntity) {
        rows.removeAll { it.serverUrl == input.serverUrl && it.ownerKey == input.ownerKey && it.ledgerId == input.ledgerId && it.kind == input.kind }
        rows += input
    }

    override suspend fun remove(server: String, owner: String, ledger: String, kind: String, key: String) {
        beforeRemove()
        rows.removeAll { it.serverUrl == server && it.ownerKey == owner && it.ledgerId == ledger && it.kind == kind && it.originalKey == key }
    }
})
