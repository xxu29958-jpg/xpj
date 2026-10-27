package com.ticketbox.data.repository

import android.app.Application
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtBillCaptureDto
import com.ticketbox.data.remote.dto.DebtBillCaptureReceiptDto
import com.ticketbox.data.remote.dto.DebtBillParseOutcomeDto
import com.ticketbox.data.remote.dto.DebtBillParseRequestDto
import com.ticketbox.upload.PreparedUploadImage
import java.io.IOException
import java.util.UUID
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okio.Buffer
import okio.ByteString.Companion.toByteString
import org.robolectric.RuntimeEnvironment

internal class DebtBillRoomFixture : AutoCloseable {
    val context: Application = RuntimeEnvironment.getApplication()
    val name = "debt-bill-${UUID.randomUUID()}.db"
    val session = TestSessionFixture().apply { saveToken("source-session") }
    val api = DebtBillApiProbe()
    val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val files = UploadIntentFileStore(context)
    var db = Room.databaseBuilder(context, AppDatabase::class.java, name).build()
    val adapters = OutboxAdapterGraph()
    lateinit var outbox: OutboxRepository
    lateinit var repository: DebtBillRepository
    var schedules = 0
    init { wire() }

    private fun wire() {
        outbox = OutboxRepository(dao = db.pendingMutationDao(), onRowsDeleted = { collectOriginals() },
            bindingProvider = { provider.currentSession().toOutboxBinding() }, onEnqueued = { schedules++ })
        repository = DebtBillRepository(provider, db.debtBillInputDao(), outbox, files)
    }

    fun reopen() { db.close(); db = Room.databaseBuilder(context, AppDatabase::class.java, name).build(); wire() }
    suspend fun capture(): DebtBillInput = repository.capture(binding, "original-create", UUID.randomUUID().toString(),
        "original raw draft", PreparedUploadImage("bank.png", "image/png", byteArrayOf(1, 2, 3), 3)).getOrThrow()
    fun engine() = OutboxDrainEngine(outbox, listOf(DebtBillCaptureDispatcher({ api }, files::read)))
    suspend fun collectOriginals() = UploadIntentRepository(provider, outbox, files, adapters.upload,
        FakeTicketboxSettingsStore(), UploadOriginalInputs(db.expenseDao(), db.debtBillInputDao())).collectOrphans()
    override fun close() { db.close(); context.deleteDatabase(name) }
}

internal class DebtBillApiProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    var source: DebtBillCaptureDto? = null
    var loseReply = false
    var rejection: Exception? = null
    val captures = mutableListOf<Pair<String, String>>()
    val parses = mutableListOf<Pair<DebtBillParseRequestDto, String>>()
    override suspend fun captureDebtBill(file: MultipartBody.Part, creationKey: RequestBody,
        captureKey: String): DebtBillCaptureReceiptDto {
        rejection?.let { throw it }
        val task = Buffer().also(creationKey::writeTo).readUtf8()
        val bytes = Buffer().also(file.body::writeTo).readByteArray()
        val hash = bytes.toByteString().sha256().hex()
        captures += task to captureKey
        source = source ?: DebtBillCaptureDto("source-id", task, captureKey, 1, "pending", hash, hash, "bank.png", "verified")
        if (loseReply) { loseReply = false; throw IOException("accepted but reply lost") }
        return DebtBillCaptureReceiptDto("source-id", task, captureKey, 1, hash, hash)
    }
    override suspend fun debtBillByKey(captureKey: String) = requireNotNull(source).also { check(it.captureKey == captureKey) }
    override suspend fun discardDebtBill(publicId: String, request: DebtBillParseRequestDto, key: String): DebtBillCaptureDto =
        requireNotNull(source).copy(status = "rejected", rowVersion = request.expectedRowVersion + 1).also { source = it }
    override suspend fun parseDebtBillSource(publicId: String, request: DebtBillParseRequestDto, key: String): DebtBillParseOutcomeDto {
        parses += request to key
        return DebtBillParseOutcomeDto(publicId, key, request.expectedRowVersion + 1, "failed", "mock",
            errorCode = "debt_bill_provider_unavailable").also { source = requireNotNull(source).copy(rowVersion = it.rowVersion, parseOutcome = it) }
    }
}
