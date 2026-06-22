package com.ticketbox.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import com.ticketbox.domain.model.FxContract

@Entity(
    tableName = "expenses",
    indices = [
        // issue #65 slice 4: ``serverId`` is now nullable — a not-yet-synced
        // offline manual create has no server id until its outbox CreateExpense
        // row drains. SQLite treats NULLs as distinct in a UNIQUE index, so any
        // number of un-synced local rows coexist under one ledger; the index
        // still enforces one cached row per (ledger, real server id).
        Index(value = ["ledgerId", "serverId"], unique = true),
        Index(value = ["publicId"], unique = true),
        // One local-create row per (ledger, clientRef). NULLs (every
        // server-originated row) are distinct, so this only constrains the
        // device-local create rows — the optimistic write is idempotent on its
        // own clientRef and the sync write-back resolves the row by it.
        Index(value = ["ledgerId", "clientRef"], unique = true),
        Index(value = ["status", "expenseTime"]),
        Index(value = ["status", "confirmedAt"]),
        Index(value = ["status", "createdAt"]),
        Index(value = ["ledgerId"]),
    ],
)
data class ExpenseEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val ledgerId: String,
    // issue #65 slice 4: null until the offline CreateExpense outbox row syncs
    // and writes the server-assigned id back (see
    // ExpenseDao.applyLocalCreateServerIdentity). A server-originated row always
    // carries its real id here.
    val serverId: Long?,
    val publicId: String,
    val amountCents: Long?,
    val homeCurrencyCode: String = FxContract.HomeCurrency.storageKey,
    val originalCurrencyCode: String = FxContract.HomeCurrency.storageKey,
    val originalAmountMinor: Long? = null,
    val exchangeRateToCny: String? = null,
    val exchangeRateDate: String? = null,
    val exchangeRateSource: String? = null,
    val fxStatus: String = FxContract.StatusReady,
    val merchant: String?,
    val category: String,
    val note: String?,
    val source: String,
    val thumbnailPath: String?,
    val imageDeletedAt: String? = null,
    val thumbnailDeletedAt: String? = null,
    val imageHash: String?,
    val rawText: String?,
    val confidence: Double? = null,
    val duplicateStatus: String,
    val duplicateOfId: Long?,
    val duplicateReason: String?,
    val tags: String?,
    val valueScore: Int?,
    val regretScore: Int?,
    val status: String,
    val expenseTime: String?,
    val createdAt: String,
    val confirmedAt: String?,
    val updatedAt: String?,
    // ADR-0041: optimistic-concurrency version mirrored from the server.
    // server_default 1 on the backend; cached rows get DEFAULT 1 on the
    // v10→v11 migration and the real value on the next sync refresh.
    @ColumnInfo(defaultValue = "1")
    val rowVersion: Long,
    // issue #65 slice 4: the device-unique client ref minted when this row was
    // created offline (mirrors the body ``client_ref`` the CreateExpense
    // dispatcher POSTs and the backend's ``draft_idempotency_key`` suffix). null
    // for server-originated rows. The outbox addresses an un-synced row as
    // ``expense:local:{clientRef}`` (see OutboxExpenseTarget) so a later edit
    // resolves to it before the server id is known.
    val clientRef: String? = null,
)
