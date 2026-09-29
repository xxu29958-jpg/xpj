package com.ticketbox.data.repository

import com.ticketbox.data.remote.PortableDownloadRequest
import com.ticketbox.domain.model.LedgerSummary
import java.io.IOException
import java.io.OutputStream
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import okhttp3.ResponseBody
import retrofit2.HttpException
import retrofit2.awaitResponse

data class PortableExportSelection(val binding: LogicalSessionBinding, val ledgerId: String)

interface PortableExportActions {
    fun currentBinding(): LogicalSessionBinding?
    fun observeBinding(): Flow<LogicalSessionBinding?>
    suspend fun ledgers(binding: LogicalSessionBinding): Result<List<LedgerSummary>>
    suspend fun download(selection: PortableExportSelection, open: () -> OutputStream,
        progress: (Long) -> Unit): Result<Long>
}

class PortableExportRepository(private val apiProvider: ApiServiceProvider) : PortableExportActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "PortableExport")

    override fun currentBinding(): LogicalSessionBinding? = guard.captureLogicalBinding()
    override fun observeBinding(): Flow<LogicalSessionBinding?> = apiProvider.observeSession()
        .map { it?.toBoundSessionSnapshotOrNull()?.logicalBinding }.distinctUntilChanged()

    override suspend fun ledgers(binding: LogicalSessionBinding): Result<List<LedgerSummary>> = errors.safeCall {
        guard.bindExact(binding).call { api -> api.portableExportLedgers().ledgers.map {
            LedgerSummary(it.ledgerId, it.name, it.role, it.isDefault, it.createdAt, it.archivedAt)
        } }
    }

    override suspend fun download(selection: PortableExportSelection, open: () -> OutputStream,
        progress: (Long) -> Unit): Result<Long> = errors.safeCall {
        val bound = guard.bindExact(selection.binding)
        bound.call { api ->
            val transfer = PortableDownloadRequest()
            val call = api.portableExport(selection.ledgerId, transfer)
            call.timeout().timeout(5, TimeUnit.MINUTES)
            coroutineScope {
                val cancellation = launch(start = CoroutineStart.UNDISPATCHED) {
                    try { awaitCancellation() } finally { transfer.cancel(); call.cancel() }
                }
                try {
                    val response = call.awaitResponse()
                    if (!response.isSuccessful) throw HttpException(response)
                    val body = response.body() ?: throw RepositoryException("数据包为空，请重新下载。")
                    body.use { copyPackage(it, bound, open, progress) }
                } finally {
                    cancellation.cancel()
                }
            }
        }
    }
}

private suspend fun copyPackage(body: ResponseBody, bound: BoundLedgerRequest, open: () -> OutputStream,
    progress: (Long) -> Unit): Long {
    val expected = body.contentLength()
    if (body.contentType()?.subtype != "zip" || expected <= 0) {
        throw RepositoryException("服务器没有返回完整的数据包，请重新下载。")
    }
    try {
        return open().use { output ->
            val buffer = ByteArray(64 * 1024)
            val input = body.byteStream()
            var total = 0L
            while (true) {
                currentCoroutineContext().ensureActive()
                bound.requireStillActive()
                val count = input.read(buffer)
                if (count == -1) break
                output.write(buffer, 0, count)
                total += count
                progress(total)
            }
            bound.requireStillActive()
            if (total != expected) throw IOException("Incomplete portable package")
            total
        }
    } catch (error: IOException) {
        currentCoroutineContext().ensureActive()
        throw RepositoryException("下载或保存未完成，请检查连接和保存位置后重试。", cause = error)
    }
}
